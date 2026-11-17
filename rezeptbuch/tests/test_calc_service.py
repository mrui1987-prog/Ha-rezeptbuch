"""Tests Modul 06 mit Datenbank: Laden, Bezugsgrößen, B4, build_batch_items (docs/berechnung.md Abschnitt 5, 7, 11).

Die Rezepte werden über die Rezeptverwaltung (Modul 05) angelegt, wie im Betrieb.
"""

import pytest

from app.calculation.loader import load_recipe
from app.calculation.service import basis_options, build_batch_items, calculate, validate_basis
from app.errors import NotFoundError, ValidationError
from app.raw_materials import archive_raw_material, create_raw_material
from app.recipes import create_recipe, get_recipe, save_recipe, set_batch_sizes, set_piece_weights

from conftest import add_order


@pytest.fixture
def rm(conn):
    def make(name, **kw):
        data = {"name": name, "tolerance": "10"}
        data.update(kw)
        return create_raw_material(conn, data)["id"]
    return {
        "mehl": make("Weizenmehl 550", type="flour", tolerance="2", tolerance_unit="percent"),
        "roggen": make("Roggenmehl 1150", type="flour", tolerance="2", tolerance_unit="percent"),
        "wasser": make("Wasser", tolerance="50"),
        "salz": make("Speisesalz", display_name="Salz", tolerance="2"),
        "hefe": make("Hefe frisch", tolerance="5"),
        "ei": make("Vollei", unit_size_g="55", unit_label="Ei"),
        "quark": make("Speisequark", display_name="Quark", tolerance="1", tolerance_unit="percent"),
        "zucker": make("Zucker"),
    }


def item(raw_material_id, amount, step_no=None):
    data = {"type": "raw_material", "raw_material_id": raw_material_id, "amount_g": amount}
    if step_no:
        data["step_no"] = step_no
    return data


@pytest.fixture
def brot(conn, rm):
    """Mischbrot mit Vorteig (Unterrezept): G = 14 800 g, Mehl inkl. Vorteig 8 500 g."""
    vorteig = create_recipe(conn, {"name": "Vorteig", "items": [item(rm["roggen"], 1500), item(rm["wasser"], 1500)]})
    brot = create_recipe(conn, {
        "name": "Mischbrot", "knead_slow_min": 5, "knead_fast_min": 6,
        "steps": [{"name": "Vorteig"}, {"name": "Hauptteig"}],
        "items": [{"type": "sub_recipe", "sub_recipe_id": vorteig["id"], "amount_g": 3000, "step_no": 1},
                  item(rm["mehl"], 7000, 2), item(rm["wasser"], 4500, 2), item(rm["salz"], 200, 2),
                  item(rm["hefe"], 100, 2)]})
    brot = set_piece_weights(conn, brot["id"], [{"label": "Laib", "weight_g": 1250}, {"label": "Kasten", "weight_g": 900}])
    brot = set_batch_sizes(conn, brot["id"], [
        {"label": "Halbe Charge", "kind": "weight", "value": 7400},
        {"label": "10 Laibe", "kind": "pieces", "value": 10, "piece_weight_id": brot["piece_weights"][0]["id"]}])
    return {"brot": brot, "vorteig": vorteig}


def req(recipe, **kw):
    data = {"recipe_id": recipe["id"]}
    data.update(kw)
    return data


def targets(result):
    return [i["target_g"] for i in result["items"]]


# -- Laden -----------------------------------------------------------------------------

def test_loader_builds_tree_with_steps_and_sub_recipe(conn, brot):
    tree = load_recipe(conn, brot["brot"]["id"])
    assert tree.name == "Mischbrot" and tree.version_no == 1 and tree.knead_slow_min == 5
    assert tree.lines[0].sub.name == "Vorteig"
    assert tree.lines[1].step_name == "Hauptteig"
    assert [p.label for p in tree.piece_weights] == ["Laib", "Kasten"]
    assert tree.lines[3].material.station_name == "Salz"


def test_unknown_recipe_and_version(conn, brot):
    with pytest.raises(NotFoundError):
        calculate(conn, {"recipe_id": 999, "basis_type": "total", "value": 100})
    with pytest.raises(NotFoundError):
        calculate(conn, req(brot["brot"], version_no=5, basis_type="total", value=100))


# -- Bezugsgrößen ------------------------------------------------------------------------

def test_total_in_kg(conn, brot):
    result = calculate(conn, req(brot["brot"], basis_type="total", value="7,4", input_unit="kg"))
    assert targets(result) == [1500, 3500, 2250, 100, 50]
    assert result["basis"]["target_g"] == 7400 and result["basis"]["input_unit"] == "kg"
    assert result["totals"]["knead"] == "5+6"
    # Stückhinweis (R06-17): 7 400 / 1 250 = 5,92 → 5,9 Laib; 7 400 / 900 = 8,2 Kasten
    assert [h["count_tenths"] for h in result["piece_hints"]] == [59, 82]


def test_pieces(conn, brot):
    laib, kasten = brot["brot"]["piece_weights"]
    result = calculate(conn, req(brot["brot"], basis_type="pieces",
                                 pieces=[{"piece_weight_id": laib["id"], "count": 4},
                                         {"piece_weight_id": kasten["id"], "count": "3"}]))
    assert result["basis"]["target_g"] == 4 * 1250 + 3 * 900     # 7 700 g
    assert result["piece_hints"] == []
    assert sum(targets(result)) >= 7700


def test_batch_sizes(conn, brot):
    half, ten = brot["brot"]["batch_sizes"]
    result = calculate(conn, req(brot["brot"], basis_type="batch_size", batch_size_id=half["id"]))
    assert targets(result) == [1500, 3500, 2250, 100, 50]
    assert result["piece_hints"]                                  # Chargengröße „Gewicht“: Hinweis ja
    result = calculate(conn, req(brot["brot"], basis_type="batch_size", batch_size_id=ten["id"]))
    assert result["basis"]["target_g"] == 12500
    assert result["piece_hints"] == []                            # Chargengröße „Stück“: kein Hinweis


def test_flour_total_and_leading_material(conn, brot, rm):
    flour = calculate(conn, req(brot["brot"], basis_type="flour_total", value=4250))
    water = calculate(conn, req(brot["brot"], basis_type="raw_material", raw_material_id=rm["wasser"],
                                value="3", input_unit="l"))       # 3 l = 3 000 g Wasser gesamt (M02-1e)
    assert targets(flour) == targets(water) == [1500, 3500, 2250, 100, 50]
    line = calculate(conn, req(brot["brot"], basis_type="raw_material", raw_material_id=rm["wasser"],
                               item_position=3, value=3000))
    assert targets(line) == [2000, 4667, 3000, 134, 67]


def test_overrides(conn, brot):
    result = calculate(conn, req(brot["brot"], basis_type="total", value=14900,
                                 overrides=[{"position": 4, "amount_g": 300}]))      # Salz 200 → 300
    assert targets(result) == [3000, 7000, 4500, 300, 100]


# -- Plausibilität (P06-1 bis P06-10, B4) -----------------------------------------------

@pytest.mark.parametrize("changes, field", [
    ({"basis_type": "total", "value": "0"}, "value"),                                   # P06-1
    ({"basis_type": "total", "value": "-5"}, "value"),
    ({"basis_type": "total", "value": "7,5"}, "value"),                                 # keine ganzen Gramm
    ({"basis_type": "total", "value": "abc"}, "value"),
    ({"basis_type": "total", "value": "1001", "input_unit": "kg"}, "value"),            # P06-2
    ({"basis_type": "total", "value": 100, "input_unit": "l"}, "input_unit"),           # P06-8
    ({"basis_type": "flour_total", "value": 100, "input_unit": "pcs"}, "input_unit"),
    ({"basis_type": "pieces", "pieces": []}, "pieces"),                                 # P06-7
    ({"basis_type": "pieces", "pieces": [{"piece_weight_id": 1, "count": "1,5"}]}, "pieces"),
    ({"basis_type": "pieces", "pieces": [{"piece_weight_id": 1, "count": 100001}]}, "pieces"),
    ({"basis_type": "batch_size"}, "batch_size_id"),
    ({"basis_type": "raw_material", "value": 100}, "raw_material_id"),
    ({"basis_type": "total", "value": 100, "overrides": [{"position": 9, "amount_g": 1}]}, "overrides"),  # P06-10
    ({"basis_type": "total", "value": 100, "overrides": [{"position": 2, "amount_g": -1}]}, "overrides"),
    ({"basis_type": "egal", "value": 100}, "basis_type"),
])
def test_input_errors(conn, brot, changes, field):
    with pytest.raises(ValidationError) as exc:
        calculate(conn, req(brot["brot"], **changes))
    assert exc.value.field == field


def test_piece_weight_and_batch_size_of_other_recipe(conn, brot, rm):
    """B4: Stückgewicht und Chargengröße müssen zum Rezept gehören (P06-6)."""
    other = create_recipe(conn, {"name": "Anderes", "items": [item(rm["mehl"], 1000)]})
    other = set_piece_weights(conn, other["id"], [{"label": "Stück", "weight_g": 100}])
    other = set_batch_sizes(conn, other["id"], [{"label": "1 kg", "kind": "weight", "value": 1000}])
    with pytest.raises(ValidationError) as exc:
        calculate(conn, req(brot["brot"], basis_type="pieces",
                            pieces=[{"piece_weight_id": other["piece_weights"][0]["id"], "count": 1}]))
    assert exc.value.field == "pieces"
    with pytest.raises(ValidationError) as exc:
        calculate(conn, req(brot["brot"], basis_type="batch_size", batch_size_id=other["batch_sizes"][0]["id"]))
    assert exc.value.field == "batch_size_id"


def test_leading_material_not_in_recipe(conn, brot, rm):
    with pytest.raises(ValidationError, match="nicht vor"):
        calculate(conn, req(brot["brot"], basis_type="raw_material", raw_material_id=rm["quark"], value=100))


def test_flour_total_offered_only_with_flour(conn, rm):
    cake = create_recipe(conn, {"name": "Käsekuchen", "items": [item(rm["quark"], 5000), item(rm["zucker"], 800),
                                                                  item(rm["ei"], 1160)]})
    options = basis_options(conn, cake["id"])
    assert options["flour_total_available"] is False
    with pytest.raises(ValidationError, match="kein Mehl"):
        calculate(conn, req(cake, basis_type="flour_total", value=1000))
    result = calculate(conn, req(cake, basis_type="raw_material", raw_material_id=rm["quark"], value="7,5",
                                 input_unit="kg"))
    assert result["items"][2]["units"] == {"size_g": 55, "label": "Ei", "count": 31, "rest_g": 35}


# -- Auswahl für die Vorwahl --------------------------------------------------------------

def test_basis_options(conn, brot, rm):
    options = basis_options(conn, brot["brot"]["id"])
    assert options["total_g"] == 14800 and options["flour_g"] == 8500 and options["flour_total_available"]
    assert [p["label"] for p in options["piece_weights"]] == ["Laib", "Kasten"]
    assert [b["weight_g"] for b in options["batch_sizes"]] == [7400, 12500]
    water = next(o for o in options["raw_materials"] if o["raw_material_id"] == rm["wasser"])
    assert water["amount_g"] == 6000
    assert water["lines"] == [{"position": 3, "step_name": "Hauptteig", "amount_g": 4500}]
    assert options["knead"] == "5+6"


def test_archived_raw_material_and_locked_recipe_hints(conn, brot, rm):
    archive_raw_material(conn, rm["hefe"])
    result = calculate(conn, req(brot["brot"], basis_type="total", value=14800))
    codes = {w["code"] for w in result["warnings"]}
    assert {"archived", "recipe_locked"} <= codes          # neue Rezepte starten gesperrt (K05-4)


def test_old_version_can_be_calculated(conn, brot, rm):
    recipe = get_recipe(conn, brot["brot"]["id"])
    payload = {"name": recipe["name"], "steps": [{"name": s["name"]} for s in recipe["steps"]],
               "items": [{"id": i["id"], "type": i["type"], "amount_g": i["amount_g"], "step_no": i["step_no"],
                          **({"raw_material_id": i["raw_material"]["id"]} if i["type"] == "raw_material"
                             else {"sub_recipe_id": i["sub_recipe"]["id"]})} for i in recipe["items"]]}
    payload["items"][3]["amount_g"] = 250
    save_recipe(conn, recipe["id"], payload, revision=recipe["revision"], version_mode="new")
    old = calculate(conn, req(brot["brot"], version_no=1, basis_type="total", value=14800))
    new = calculate(conn, req(brot["brot"], basis_type="total", value=14850))
    assert old["recipe"]["current_version"] is False and old["items"][3]["target_g"] == 200
    assert new["recipe"]["version_no"] == 2 and new["items"][3]["target_g"] == 250


# -- validate_basis (B4) -----------------------------------------------------------------

def test_validate_basis_accepts_valid_orders(conn, brot, rm):
    rid = brot["brot"]["id"]
    laib = brot["brot"]["piece_weights"][0]
    ten = brot["brot"]["batch_sizes"][1]
    validate_basis(conn, rid, {"basis_type": "total", "basis_value": 7400, "basis_input_unit": "kg"})
    validate_basis(conn, rid, {"basis_type": "raw_material", "basis_value": 3000, "basis_input_unit": "l",
                               "basis_raw_material_id": rm["wasser"], "basis_item_position": 3})
    validate_basis(conn, rid, {"basis_type": "pieces", "basis_value": 5000, "basis_input_unit": "pcs",
                               "pieces": [{"piece_weight_id": laib["id"], "count": 4}]})
    validate_basis(conn, rid, {"basis_type": "batch_size", "basis_value": 12500, "basis_input_unit": "pcs",
                               "batch_size_id": ten["id"]})


@pytest.mark.parametrize("order, field", [
    ({"basis_type": "total", "basis_value": 0}, "basis_value"),
    ({"basis_type": "total", "basis_value": 100, "basis_input_unit": "l"}, "input_unit"),
    ({"basis_type": "total", "basis_value": 100, "basis_raw_material_id": 1}, "basis_raw_material_id"),
    ({"basis_type": "flour_total", "basis_value": 2_000_000}, "basis_value"),
    ({"basis_type": "raw_material", "basis_value": 100}, "raw_material_id"),
    ({"basis_type": "pieces", "basis_value": 999, "basis_input_unit": "pcs", "pieces": "LAIB4"}, "basis_value"),
    ({"basis_type": "batch_size", "basis_value": 7400, "basis_input_unit": "pcs", "batch_size_id": "HALF"},
     "basis_input_unit"),
    ({"basis_type": "batch_size", "basis_value": 7000, "batch_size_id": "HALF"}, "basis_value"),
])
def test_validate_basis_refuses(conn, brot, order, field):
    laib = brot["brot"]["piece_weights"][0]
    if order.get("pieces") == "LAIB4":
        order = dict(order, pieces=[{"piece_weight_id": laib["id"], "count": 4}])     # ergibt 5 000, nicht 999
    if order.get("batch_size_id") == "HALF":
        order = dict(order, batch_size_id=brot["brot"]["batch_sizes"][0]["id"])
    with pytest.raises(ValidationError) as exc:
        validate_basis(conn, brot["brot"]["id"], order)
    assert exc.value.field == field


# -- build_batch_items (B2) ----------------------------------------------------------------

def _version_id(conn, recipe_id, version_no=1):
    return conn.execute("SELECT id FROM recipe_version WHERE recipe_id = ? AND version_no = ?",
                        (recipe_id, version_no)).fetchone()[0]


def test_build_batch_items_from_fixed_version(conn, brot, rm):
    rid = brot["brot"]["id"]
    version = _version_id(conn, rid)
    order = add_order(conn, rid, version_id=version, basis_type="flour_total", basis_value=4250, status="in_progress")
    conn.execute("INSERT INTO order_item_override (order_id, item_position, amount_g) VALUES (?, 4, 300)", (order,))
    rows = build_batch_items(conn, order, version)
    assert [r["target_g"] for r in rows] == [1500, 3500, 2250, 150, 50]
    assert rows[0]["item_type"] == "sub_recipe" and rows[0]["sub_recipe_id"] == brot["vorteig"]["id"]
    assert rows[0]["tolerance_g"] == 0 and rows[0]["rest_target_g"] == 1500
    assert rows[1]["tolerance_g"] == 70                       # 2 % von 3 500 g
    assert rows[3]["raw_material_name"] == "Speisesalz" and rows[3]["station_name"] == "Salz"

    # Die Werte passen in die Tabelle batch_item (Prüfregeln und Trigger B2)
    batch = conn.execute("INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status) "
                         "VALUES ('T-1', ?, 1, ?, 'running')", (order, version)).lastrowid
    columns = ["position", "recipe_item_id", "item_type", "raw_material_id", "raw_material_number",
               "raw_material_name", "sub_order_id", "target_g", "tolerance_g", "unit_size_g", "unit_label",
               "units_target", "rest_target_g"]
    for row in rows:
        conn.execute(f"INSERT INTO batch_item (batch_id, {', '.join(columns)}) VALUES (?, {', '.join('?' * len(columns))})",
                     [batch] + [row[c] for c in columns])
    assert conn.execute("SELECT count(*) FROM batch_item WHERE batch_id = ?", (batch,)).fetchone()[0] == 5


def test_build_batch_items_with_units_and_hand_addition(conn, rm):
    vanille = create_raw_material(conn, {"name": "Vanille", "tolerance": "0"})["id"]
    cake = create_recipe(conn, {"name": "Käsekuchen", "items": [item(rm["quark"], 5000), item(rm["ei"], 1160),
                                                                  item(vanille, 0)]})
    version = _version_id(conn, cake["id"])
    order = add_order(conn, cake["id"], version_id=version, basis_type="raw_material", basis_value=7500,
                      basis_raw_material_id=rm["quark"], basis_item_position=1, status="in_progress")
    rows = build_batch_items(conn, order, version)
    assert (rows[1]["units_target"], rows[1]["rest_target_g"], rows[1]["unit_label"]) == (31, 35, "Ei")
    assert rows[2]["kind"] == "hand" and rows[2]["target_g"] == 0 and rows[2]["tolerance_g"] == 0


def test_build_batch_items_only_from_order_version(conn, brot):
    rid = brot["brot"]["id"]
    version = _version_id(conn, rid)
    open_order = add_order(conn, rid, basis_type="total", basis_value=1000)
    with pytest.raises(ValidationError, match="nicht fixiert"):
        build_batch_items(conn, open_order, version)
    order = add_order(conn, rid, version_id=version, basis_type="total", basis_value=1000, status="in_progress")
    other_version = _version_id(conn, brot["vorteig"]["id"])
    with pytest.raises(ValidationError) as exc:
        build_batch_items(conn, order, other_version)
    assert exc.value.code == "version_mismatch"
    with pytest.raises(NotFoundError):
        build_batch_items(conn, 999, version)
