"""Tests Modul 06 Teil C3 mit Datenbank: Haken „aktiv (Obergrenze)“, Anfrage, Kombinieren, Faktor, Teige,
validate_basis, build_batch_items je Teig, sub_order_targets (docs/berechnung.md Abschnitt 17).
"""

import io

import pytest

from app.calculation.models import parse_factor, validate_request
from app.calculation.service import (
    basis_options,
    build_batch_items,
    calculate,
    sub_order_targets,
    validate_basis,
)
from app.errors import ValidationError
from app.raw_materials import create_raw_material
from app.recipes import copy_recipe, create_recipe, get_recipe, set_batch_sizes, set_piece_weights

from conftest import add_order


def item(raw_material_id, amount):
    return {"type": "raw_material", "raw_material_id": raw_material_id, "amount_g": amount}


@pytest.fixture
def rm(conn):
    def make(name, **kw):
        return create_raw_material(conn, {"name": name, "tolerance": "10", **kw})["id"]
    return {"mehl": make("Weizenmehl 550", type="flour"), "roggen": make("Roggenmehl 1150", type="flour"),
            "wasser": make("Wasser"), "salz": make("Speisesalz"), "hefe": make("Hefe")}


@pytest.fixture
def teig(conn, rm):
    """Brötchenteig G = 10 000 g; Stück 65 g; Chargengrößen „Großer Teig“ 12 kg, „Kessel“ 20 kg (aktiv), „Blech“ 30 Stück."""
    recipe = create_recipe(conn, {"name": "Brötchenteig", "items": [
        item(rm["mehl"], 6000), item(rm["wasser"], 3800), item(rm["salz"], 120), item(rm["hefe"], 80)]})
    recipe = set_piece_weights(conn, recipe["id"], [{"label": "Stück", "weight_g": 65}])
    return set_batch_sizes(conn, recipe["id"], [
        {"label": "Großer Teig", "kind": "weight", "value": 12000},
        {"label": "Kessel", "kind": "weight", "value": 20000, "is_limit": True},
        {"label": "Blech", "kind": "pieces", "value": 30, "piece_weight_id": recipe["piece_weights"][0]["id"]}])


@pytest.fixture
def brot(conn, rm):
    """Mischbrot mit Vorteig 3 000 g, G = 14 800 g, ohne Chargengröße."""
    vorteig = create_recipe(conn, {"name": "Vorteig", "items": [item(rm["roggen"], 1500), item(rm["wasser"], 1500)]})
    return create_recipe(conn, {"name": "Mischbrot", "items": [
        {"type": "sub_recipe", "sub_recipe_id": vorteig["id"], "amount_g": 3000},
        item(rm["mehl"], 7000), item(rm["wasser"], 4500), item(rm["salz"], 200), item(rm["hefe"], 100)]})


def sizes(recipe):
    return {b["label"]: b for b in recipe["batch_sizes"]}


# -- Haken in der Rezeptverwaltung (Modul 05) ---------------------------------------------------------

def test_batch_size_flag_saved_moved_and_kept(conn, teig):
    assert [b["is_limit"] for b in teig["batch_sizes"]] == [False, True, False]
    rev = get_recipe(conn, teig["id"])["revision"]
    # Haken umsetzen in einem Speichern (eindeutiger Index darf nicht stören)
    data = [dict(b, is_limit=b["label"] == "Großer Teig") for b in teig["batch_sizes"]]
    moved = set_batch_sizes(conn, teig["id"], data)
    assert [b["is_limit"] for b in moved["batch_sizes"]] == [True, False, False]
    assert moved["revision"] == rev + 1
    # Feld fehlt (ältere Seite/Datei): bisheriger Haken bleibt
    kept = set_batch_sizes(conn, teig["id"], [{k: v for k, v in b.items() if k != "is_limit"}
                                              for b in moved["batch_sizes"]])
    assert [b["is_limit"] for b in kept["batch_sizes"]] == [True, False, False]


def test_only_one_flag(conn, teig):
    data = [dict(b, is_limit=True) for b in teig["batch_sizes"]]
    with pytest.raises(ValidationError, match="Nur eine Chargengröße"):
        set_batch_sizes(conn, teig["id"], data)
    with pytest.raises(ValidationError, match="ja oder nein"):
        set_batch_sizes(conn, teig["id"], [dict(teig["batch_sizes"][0], is_limit="ja")])


def test_copy_keeps_flag(conn, teig):
    copy = copy_recipe(conn, teig["id"])
    assert [b["is_limit"] for b in get_recipe(conn, copy["id"])["batch_sizes"]] == [False, True, False]


def test_export_has_limit_column(conn, teig):
    openpyxl = pytest.importorskip("openpyxl")
    from app.exports import build_workbook
    wb = openpyxl.load_workbook(io.BytesIO(build_workbook(conn, include_archived=True)))
    rows = list(wb["Chargengrößen"].iter_rows(values_only=True))
    assert rows[0][-1] == "Obergrenze (ja = aktiv)"
    assert [r[-1] for r in rows[1:]] == [None, "ja", None]


# -- basis-options ------------------------------------------------------------------------------

def test_basis_options_limit(conn, teig, brot):
    options = basis_options(conn, teig["id"])
    assert options["limit"] == {"batch_size_id": sizes(teig)["Kessel"]["id"], "label": "Kessel", "limit_g": 20000}
    assert [b["is_limit"] for b in options["batch_sizes"]] == [False, True, False]
    assert options["factor_allowed"] is True
    assert basis_options(conn, brot["id"])["limit"] is None


def test_pieces_batch_size_as_limit_in_grams(conn, teig):
    """Klärung 4: Chargengröße „Stück“ als Obergrenze = 30 × 65 g = 1 950 g."""
    data = [dict(b, is_limit=b["label"] == "Blech") for b in teig["batch_sizes"]]
    set_batch_sizes(conn, teig["id"], data)
    assert basis_options(conn, teig["id"])["limit"]["limit_g"] == 1950


# -- Anfrage (P06-11 bis P06-18) -----------------------------------------------------------------

@pytest.mark.parametrize("text, hundredths", [("1,5", 150), ("1.5", 150), ("2", 200), ("0,01", 1), ("100", 10000),
                                              (0.75, 75)])
def test_parse_factor(text, hundredths):
    assert parse_factor(text) == hundredths


@pytest.mark.parametrize("text", ["0", "0,001", "1,555", "100,01", "abc", "-1", None, True])
def test_parse_factor_invalid(text):
    with pytest.raises(ValidationError) as exc:
        parse_factor(text)
    assert exc.value.code == "factor_invalid"


@pytest.mark.parametrize("payload, field, code", [
    ({"basis_type": "flour_total", "value": "5", "input_unit": "kg", "factor": "2"}, "basis_type", "sole_basis"),
    ({"basis_type": "raw_material", "value": "5", "raw_material_id": 1, "total_part": "1000"}, "basis_type", "sole_basis"),
    ({"basis_type": "total", "value": "5000", "factor": "2"}, "basis_type", "combine_required"),
    ({"basis_type": "combined"}, "basis_type", "demand_missing"),
    ({"basis_type": "combined", "pieces": [{"piece_weight_id": 1, "count": 0}]}, "basis_type", "demand_missing"),
    ({"basis_type": "combined", "batch_sizes": [{"batch_size_id": 1, "count": 101}]}, "batch_sizes", "batch_count_invalid"),
    ({"basis_type": "combined", "batch_sizes": [{"batch_size_id": 1, "count": 1}, {"batch_size_id": 1, "count": 2}]},
     "batch_sizes", "batch_sizes_duplicate"),
    ({"basis_type": "factor", "factor": "0"}, "factor", "factor_invalid"),
    ({"basis_type": "total", "value": "5000", "dough_count": 51}, "dough_count", "too_many_doughs"),
    ({"basis_type": "total", "value": "5000", "order_limit": "7,5"}, "order_limit", "order_limit_invalid"),
    ({"basis_type": "total", "value": "5000", "order_limit": {"value": "1001", "input_unit": "kg"}}, "order_limit",
     "order_limit_invalid"),
    ({"basis_type": "total", "value": "5000", "split_mode": "half"}, "split_mode", "split_mode_invalid"),
    ({"basis_type": "total", "value": "5000", "split": "ja"}, "split", "split_invalid"),
    ({"basis_type": "total", "value": "5000", "sub_modes": [{"position": 1, "mode": "x"}]}, "sub_modes",
     "sub_mode_invalid"),
])
def test_request_errors(payload, field, code):
    with pytest.raises(ValidationError) as exc:
        validate_request({"recipe_id": 1, **payload})
    assert (exc.value.field, exc.value.code) == (field, code)


def test_request_combined_fields():
    req = validate_request({"recipe_id": 1, "basis_type": "combined",
                            "total_part": {"value": "5", "input_unit": "kg"}, "factor": "0,5",
                            "pieces": [{"piece_weight_id": 3, "count": 100}, {"piece_weight_id": 4, "count": 0}],
                            "batch_sizes": [{"batch_size_id": 7, "count": 2}, {"batch_size_id": 8, "count": 0}],
                            "order_limit": {"value": "15", "input_unit": "kg"}, "dough_count": "3",
                            "split_mode": "even", "sub_modes": [{"position": 1, "mode": "all"}]})
    assert (req.total_part_g, req.factor_hundredths, req.pieces, req.batch_sizes) == (5000, 50, ((3, 100),), ((7, 2),))
    assert (req.order_limit_g, req.dough_count, req.split_mode, req.sub_modes) == (15000, 3, "even", {1: "all"})


# -- calculate über die Datenbank ---------------------------------------------------------------------

def test_calculate_combined_example(conn, teig):
    """5 kg + 100 Stück + 2 × Großer Teig + Faktor 0,5 = 40 500 g; Kessel 20 kg aktiv → 20 000 + 20 000 + 500 g."""
    s = sizes(teig)
    result = calculate(conn, {"recipe_id": teig["id"], "basis_type": "combined",
                              "total_part": {"value": "5", "input_unit": "kg"}, "factor": "0,5",
                              "pieces": [{"piece_weight_id": teig["piece_weights"][0]["id"], "count": 100}],
                              "batch_sizes": [{"batch_size_id": s["Großer Teig"]["id"], "count": 2}]})
    assert result["demand"]["target_g"] == 40500
    assert [p["kind"] for p in result["demand"]["parts"]] == ["total", "pieces", "batch_size", "factor"]
    assert result["split"]["limit_source"] == "recipe" and result["split"]["limit_label"] == "Kessel"
    assert [d["target_g"] for d in result["doughs"]] == [20000, 20000, 500]
    assert any(w["code"] == "last_dough_small" for w in result["warnings"])
    assert [b["count"] for b in result["basis"]["batch_sizes"]] == [2]


def test_same_batch_size_twice_and_one_limit_dough(conn, teig):
    """R06-19: dieselbe Chargengröße mehrmals (2 × Großer Teig = 24 kg → 2 Teige); 1 × Kessel = genau ein Teig."""
    s = sizes(teig)
    twice = calculate(conn, {"recipe_id": teig["id"], "basis_type": "combined",
                             "batch_sizes": [{"batch_size_id": s["Großer Teig"]["id"], "count": 2}]})
    assert [d["target_g"] for d in twice["doughs"]] == [20000, 4000]
    once = calculate(conn, {"recipe_id": teig["id"], "basis_type": "batch_size", "batch_size_id": s["Kessel"]["id"]})
    assert [d["target_g"] for d in once["doughs"]] == [20000]


def test_order_limit_rules(conn, teig, brot):
    """K06-6: mit aktiver Chargengröße nur senken; ohne frei."""
    with pytest.raises(ValidationError) as exc:
        calculate(conn, {"recipe_id": teig["id"], "basis_type": "total", "value": "30000", "order_limit": "25000"})
    assert exc.value.field == "order_limit" and "höchstens 20 000 g" in exc.value.message
    lower = calculate(conn, {"recipe_id": teig["id"], "basis_type": "total", "value": "30000",
                             "order_limit": {"value": "15", "input_unit": "kg"}})
    assert lower["split"]["limit_source"] == "order" and [d["target_g"] for d in lower["doughs"]] == [15000, 15000]
    free = calculate(conn, {"recipe_id": brot["id"], "basis_type": "total", "value": "29600", "order_limit": "20000"})
    assert [d["target_g"] for d in free["doughs"]] == [20000, 9600]
    none = calculate(conn, {"recipe_id": brot["id"], "basis_type": "total", "value": "29600"})
    assert len(none["doughs"]) == 1 and none["split"]["limit_g"] is None


def test_flag_without_haken_is_no_limit(conn, teig):
    """Klärung 3: Chargengrößen ohne Haken sind keine Obergrenze."""
    set_batch_sizes(conn, teig["id"], [dict(b, is_limit=False) for b in teig["batch_sizes"]])
    result = calculate(conn, {"recipe_id": teig["id"], "basis_type": "total", "value": "40000"})
    assert len(result["doughs"]) == 1


def test_factor_via_service(conn, teig):
    result = calculate(conn, {"recipe_id": teig["id"], "basis_type": "factor", "factor": "1,5"})
    assert [i["target_g"] for i in result["items"]] == [9000, 5700, 180, 120]
    assert result["basis"]["factor_hundredths"] == 150


# -- validate_basis, build_batch_items, sub_order_targets (Modul 09) --------------------------------------

def test_validate_combined_order(conn, teig):
    s = sizes(teig)
    base = {"basis_type": "combined", "basis_value": 40500, "total_part_g": 5000, "factor_hundredths": 50,
            "pieces": [{"piece_weight_id": teig["piece_weights"][0]["id"], "count": 100}],
            "batch_sizes": [{"batch_size_id": s["Großer Teig"]["id"], "count": 2}],
            "limit_g": 20000, "limit_source": "recipe", "dough_count": 3, "split_mode": "fill",
            "doughs": [20000, 20000, 500]}
    result = validate_basis(conn, teig["id"], base)
    assert result["demand"]["target_g"] == 40500
    for change, field in [
        ({"basis_value": 40000}, "basis_value"),
        ({"doughs": [20000, 20000, 501]}, "doughs"),
        ({"dough_count": 2, "doughs": [20000, 20500]}, "dough_count"),
        ({"limit_g": 21000}, "limit_g"),
        ({"limit_g": None, "limit_source": None}, "limit_g"),
        ({"split_mode": None}, "split_mode"),
        ({"basis_type": "total"}, "pieces"),
        ({"batch_sizes": [{"batch_size_id": 99999, "count": 1}]}, "batch_sizes"),
    ]:
        with pytest.raises(ValidationError) as exc:
            validate_basis(conn, teig["id"], {**base, **change})
        assert exc.value.field == field, change


def test_validate_factor_and_order_limit(conn, teig):
    validate_basis(conn, teig["id"], {"basis_type": "factor", "basis_value": 15000, "factor_hundredths": 150,
                                      "limit_g": 20000, "limit_source": "recipe"})
    with pytest.raises(ValidationError) as exc:
        validate_basis(conn, teig["id"], {"basis_type": "factor", "basis_value": 15000, "limit_g": 20000,
                                          "limit_source": "recipe"})
    assert exc.value.field == "factor_hundredths"
    with pytest.raises(ValidationError) as exc:
        validate_basis(conn, teig["id"], {"basis_type": "total", "basis_value": 30000, "limit_g": 25000,
                                          "limit_source": "order", "dough_count": 2, "split_mode": "even"})
    assert exc.value.field == "order_limit"
    validate_basis(conn, teig["id"], {"basis_type": "total", "basis_value": 30000, "limit_g": 15000,
                                      "limit_source": "order", "dough_count": 2, "split_mode": "even",
                                      "doughs": [15000, 15000]})


def test_validate_flour_split(conn, teig):
    """Mehl gesamt 12 kg → Teig 20 kg; mit Kessel 15 kg (Auftrag) und „teilen“: 15 000 + 5 000 g."""
    validate_basis(conn, teig["id"], {"basis_type": "flour_total", "basis_value": 12000, "limit_g": 15000,
                                      "limit_source": "order", "dough_count": 2, "split_mode": "fill",
                                      "doughs": [15000, 5000]})


def _fixed_order(conn, recipe, **cols):
    version = conn.execute("SELECT current_version_id FROM recipe WHERE id = ?", (recipe["id"],)).fetchone()[0]
    order = add_order(conn, recipe["id"], version_id=version, **cols)
    return order, version


def test_build_batch_items_per_dough(conn, teig):
    order, version = _fixed_order(conn, teig, basis_type="total", basis_value=32000, dough_count=2, limit_g=20000,
                                  limit_source="recipe", split_mode="fill")
    conn.executemany("INSERT INTO order_dough (order_id, dough_index, target_g) VALUES (?, ?, ?)",
                     [(order, 1, 20000), (order, 2, 12000)])
    first = build_batch_items(conn, order, version, 1)
    second = build_batch_items(conn, order, version, 2)
    assert [r["target_g"] for r in first] == [12000, 7600, 240, 160]
    assert [r["target_g"] for r in second] == [7200, 4560, 144, 96]
    with pytest.raises(ValidationError) as exc:
        build_batch_items(conn, order, version)
    assert exc.value.field == "dough_index"
    with pytest.raises(ValidationError) as exc:
        build_batch_items(conn, order, version, 3)
    assert exc.value.code == "dough_index_invalid"


def test_build_batch_items_single_factor_and_combined(conn, teig):
    order, version = _fixed_order(conn, teig, basis_type="factor", basis_value=15000, factor_hundredths=150)
    assert [r["target_g"] for r in build_batch_items(conn, order, version)] == [9000, 5700, 180, 120]
    assert [r["target_g"] for r in build_batch_items(conn, order, version, 1)] == [9000, 5700, 180, 120]
    combo, _ = _fixed_order(conn, teig, basis_type="combined", basis_value=7500, total_part_g=7500)
    assert [r["target_g"] for r in build_batch_items(conn, combo, version)] == [4500, 2850, 90, 60]


def test_sub_order_targets(conn, brot):
    """2 × 14 801 g (gleichmäßig): Vorteig je Teig 3 001 g, für alle 6 002 g; ein Teig: 3 000 g."""
    order = add_order(conn, brot["id"], basis_type="total", basis_value=29601, dough_count=2, limit_g=14801,
                      limit_source="order", split_mode="even")
    conn.executemany("INSERT INTO order_dough (order_id, dough_index, target_g) VALUES (?, ?, ?)",
                     [(order, 1, 14801), (order, 2, 14801)])
    per = sub_order_targets(conn, order)
    assert [(t["position"], t["mode"], t["dough_index"], t["target_g"]) for t in per] == [
        (1, "per_dough", 1, 3001), (1, "per_dough", 2, 3001)]
    for_all = sub_order_targets(conn, order, {1: "all"})
    assert [(t["mode"], t["dough_index"], t["target_g"]) for t in for_all] == [("all", None, 6002)]
    with pytest.raises(ValidationError, match="kein Unterrezept"):
        sub_order_targets(conn, order, {2: "all"})
    single = add_order(conn, brot["id"], basis_type="total", basis_value=14800)
    assert [(t["mode"], t["dough_index"], t["target_g"]) for t in sub_order_targets(conn, single)] == [
        ("all", None, 3000)]
