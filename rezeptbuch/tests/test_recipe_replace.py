"""Tests: Rohstoff in Rezepten austauschen (Modul 05, Ergänzung C3-E9, 0.5.9)."""

from decimal import Decimal

import pytest

from app.errors import ConflictError, ValidationError
from app.raw_materials import archive_raw_material, create_raw_material, get_raw_material
from app.recipes import create_recipe, get_recipe, get_version, save_recipe
from app.recipes.replace import parse_factor, replace_raw_material, scaled
from conftest import add_order


@pytest.fixture
def rm(conn):
    def make(name, **kw):
        return create_raw_material(conn, {"name": name, "tolerance": "5", **kw})["id"]
    return {"butter": make("Butter"), "marg": make("Margarine"), "wasser": make("Wasser"), "salz": make("Salz"),
            "mehl": make("Weizenmehl 550", type="flour"), "milch": make("Milch")}


def line(rid, amount, **kw):
    return {"type": "raw_material", "raw_material_id": rid, "amount_g": amount, **kw}


def make(conn, name, items, steps=()):
    return create_recipe(conn, {"name": name, "steps": list(steps), "items": items})["id"]


def amounts(conn, rid):
    return [(i["raw_material"]["name"] if i["type"] == "raw_material" else i["sub_recipe"]["name"], i["amount_g"])
            for i in get_recipe(conn, rid)["items"]]


def run(conn, rm, recipes, **kw):
    payload = {"old_raw_material_id": rm["butter"], "new_raw_material_id": rm["marg"], "factor": "0,82",
               "mode": "run", "confirm": True, "recipes": recipes, **kw}
    return replace_raw_material(conn, payload)


# -- Rechnen und Eingaben -------------------------------------------------------------------

@pytest.mark.parametrize("amount, factor, expected", [
    (1000, "0.82", 820), (125, "0.5", 63), (124, "0.5", 62), (0, "2", 0), (1, "0.1", 1), (3, "0.001", 1),
    (1000, "1", 1000), (333, "1.5", 500),
])
def test_scaled(amount, factor, expected):
    assert scaled(amount, Decimal(factor)) == expected


@pytest.mark.parametrize("value", ["0", "-1", "abc", "", None, "0,0001", "1001", True])
def test_bad_factor(value):
    with pytest.raises(ValidationError):
        parse_factor(value, "factor")


def test_factor_with_comma():
    assert parse_factor("0,825", "factor") == Decimal("0.825") and parse_factor(2, "factor") == 2


def test_rules(conn, rm):
    base = {"old_raw_material_id": rm["butter"], "new_raw_material_id": rm["marg"], "factor": 1}
    with pytest.raises(ValidationError, match="unterscheiden"):
        replace_raw_material(conn, {**base, "new_raw_material_id": rm["butter"]})
    with pytest.raises(ValidationError, match="Höchstens 2"):
        replace_raw_material(conn, {**base, "extras": [{"raw_material_id": rm["wasser"], "factor": 1}] * 3})
    with pytest.raises(ValidationError, match="nicht der auszutauschende"):
        replace_raw_material(conn, {**base, "extras": [{"raw_material_id": rm["butter"], "factor": 1}]})
    with pytest.raises(ValidationError, match="Faktor"):
        replace_raw_material(conn, {**base, "extras": [{"raw_material_id": rm["wasser"], "factor": 0}]})
    archive_raw_material(conn, rm["salz"])
    with pytest.raises(ValidationError, match="archiviert"):
        replace_raw_material(conn, {**base, "new_raw_material_id": rm["salz"]})
    with pytest.raises(ValidationError, match="archiviert"):
        replace_raw_material(conn, {**base, "extras": [{"raw_material_id": rm["salz"], "factor": 1}]})
    with pytest.raises(ValidationError, match="auswählen"):
        replace_raw_material(conn, {**base, "mode": "run", "confirm": True})
    assert not conn.in_transaction


def test_empty_extra_rows_are_ignored(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 100)])
    result = run(conn, rm, [{"id": a}], extras=[{"raw_material_id": None, "factor": ""}, {}])
    assert result["counts"]["done"] == 1 and amounts(conn, a) == [("Margarine", 82)]


# -- Vorschau -------------------------------------------------------------------------------

def test_preview_lists_candidates_and_changes_nothing(conn, rm):
    a = make(conn, "Butterkuchen", [line(rm["mehl"], 1000), line(rm["butter"], 1000, step_no=1)], steps=["Teig"])
    b = make(conn, "Streusel", [line(rm["butter"], 250), line(rm["butter"], 50)])
    make(conn, "Brot", [line(rm["mehl"], 1000)])                                # ohne Butter
    archived = make(conn, "Alt", [line(rm["butter"], 100)])
    from app.recipes import archive_recipe
    archive_recipe(conn, archived)
    result = replace_raw_material(conn, {"old_raw_material_id": rm["butter"], "new_raw_material_id": rm["marg"],
                                         "factor": "0,82", "extras": [{"raw_material_id": rm["wasser"], "factor": "0,16"}]})
    assert not result["executed"] and [r["id"] for r in result["recipes"]] == [a, b]     # E9-5
    first = result["recipes"][0]
    assert first["selected"] and first["status"] == "done"
    assert first["changes"] == [{"position": 2, "step": "Teig", "old_g": 1000, "new_g": 820,
                                 "extras": [{"name": "Wasser", "number": get_raw_material(conn, rm["wasser"])["number"],
                                             "amount_g": 160}], "tolerance_override": None}]
    assert len(result["recipes"][1]["changes"]) == 2                            # mehrfache Zeilen alle
    assert result["factor"] == "0,82" and result["extras"][0]["factor"] == "0,16"
    assert "2 Rezepte bekommen eine neue Version (Vorschau)" in result["summary"]
    assert amounts(conn, a) == [("Weizenmehl 550", 1000), ("Butter", 1000)]      # nichts gespeichert
    assert not conn.in_transaction


def test_run_needs_confirmation(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 100)])
    with pytest.raises(ConflictError) as exc:
        replace_raw_material(conn, {"old_raw_material_id": rm["butter"], "new_raw_material_id": rm["marg"],
                                    "factor": 1, "mode": "run", "recipes": [{"id": a}]})
    assert exc.value.code == "confirmation_required" and exc.value.extra["result"]["counts"]["done"] == 1
    assert amounts(conn, a) == [("Butter", 100)]


# -- Ausführen ------------------------------------------------------------------------------

def test_replace_with_extras_new_version_and_position(conn, rm):
    a = make(conn, "Butterkuchen", [line(rm["mehl"], 1000, step_no=1), line(rm["butter"], 1000, step_no=2),
                                    line(rm["salz"], 20, step_no=2)], steps=["Teig", "Belag"])
    before = get_recipe(conn, a)
    result = run(conn, rm, [{"id": a, "revision": before["revision"]}],
                 extras=[{"raw_material_id": rm["wasser"], "factor": "0,16"}, {"raw_material_id": rm["salz"], "factor": "0,01"}])
    assert result["executed"] and result["done"] == [{"id": a, "number": before["number"], "name": "Butterkuchen",
                                                      "old_version": 1, "new_version": 2}]
    after = get_recipe(conn, a)
    assert after["version_no"] == 2 and after["locked"] is True                          # Status bleibt (E9-6)
    assert [(i["raw_material"]["name"], i["amount_g"], i["step_no"]) for i in after["items"]] == [
        ("Weizenmehl 550", 1000, 1), ("Margarine", 820, 2), ("Wasser", 160, 2), ("Salz", 10, 2), ("Salz", 20, 2)]
    assert [i["position"] for i in after["items"]] == [1, 2, 3, 4, 5]
    assert all(not i["needs_review"] for i in after["items"])
    assert any("„Salz“ steht schon im Rezept" in h for h in result["recipes"][0]["hints"])
    assert get_version(conn, a, 1)["items"][1]["raw_material"]["name"] == "Butter"       # alte Version bleibt


def test_always_new_version_even_if_not_weighed(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 100)])
    run(conn, rm, [{"id": a}])
    run(conn, rm, [], old_raw_material_id=rm["marg"], new_raw_material_id=rm["butter"])  # nichts gewählt
    assert get_recipe(conn, a)["version_no"] == 2
    assert [v["label"] for v in get_recipe(conn, a)["versions"]] == ["aktuell", "old (1)"]


def test_frozen_version_also_new(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 100)])
    recipe = get_recipe(conn, a)
    version_id = conn.execute("SELECT current_version_id FROM recipe WHERE id = ?", (a,)).fetchone()[0]
    add_order(conn, a, version_id)                         # fixiert die Version (wie Modul 09)
    assert get_recipe(conn, a)["frozen"] is True
    run(conn, rm, [{"id": a, "revision": recipe["revision"]}])
    assert get_recipe(conn, a)["version_no"] == 2 and get_version(conn, a, 1)["items"][0]["amount_g"] == 100


def test_deselected_recipe_unchanged(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 100)])
    b = make(conn, "B", [line(rm["butter"], 200)])
    result = run(conn, rm, [{"id": a}])
    assert [r["status"] for r in result["recipes"]] == ["done", "not_selected"]
    assert amounts(conn, b) == [("Butter", 200)] and get_recipe(conn, b)["version_no"] == 1


def test_changed_elsewhere_is_skipped(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 100)])
    b = make(conn, "B", [line(rm["butter"], 200)])
    old_rev = get_recipe(conn, a)["revision"]
    save_recipe(conn, a, {"name": "A2", "items": [line(rm["butter"], 150)]}, revision=old_rev, version_mode="overwrite")
    result = run(conn, rm, [{"id": a, "revision": old_rev}, {"id": b, "revision": get_recipe(conn, b)["revision"]}])
    assert [s["id"] for s in result["skipped"]] == [a] and "anderen Gerät" in result["skipped"][0]["reason"]
    assert amounts(conn, a) == [("Butter", 150)] and amounts(conn, b) == [("Margarine", 164)]


def test_recipe_without_old_raw_material_is_skipped(conn, rm):
    a = make(conn, "A", [line(rm["mehl"], 100)])
    result = run(conn, rm, [{"id": a}])
    assert result["skipped"][0]["id"] == a and "nicht (mehr)" in result["skipped"][0]["reason"]


def test_tolerance_kept_and_hand_addition(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 500, tolerance="2,5", tolerance_unit="percent"), line(rm["butter"], 0)])
    result = run(conn, rm, [{"id": a}], extras=[{"raw_material_id": rm["wasser"], "factor": "0,2"}])
    items = get_recipe(conn, a)["items"]
    assert items[0]["tolerance_override"] == {"unit": "percent", "value": 2.5}         # E9-6
    assert items[1]["tolerance_override"] is None and items[1]["amount_g"] == 100
    assert items[2]["amount_g"] == 0 and items[2]["hand_addition"] and items[3]["amount_g"] == 0   # Handzugabe
    hints = " ".join(result["recipes"][0]["hints"])
    assert "eigene Toleranz (2,5 %)" in hints and "Handzugabe" in hints


def test_mark_review(conn, rm):
    a = make(conn, "A", [line(rm["mehl"], 1000), line(rm["butter"], 100)])
    run(conn, rm, [{"id": a}], mark_review=True, extras=[{"raw_material_id": rm["wasser"], "factor": "0,1"}])
    assert [i["needs_review"] for i in get_recipe(conn, a)["items"]] == [False, True, True]
    assert get_recipe(conn, a)["review_count"] == 2


def test_existing_review_marks_are_kept(conn, rm):
    """„*“ anderer Zeilen bleibt erhalten (Austausch setzt sie wie gespeichert fort)."""
    a = make(conn, "A", [line(rm["mehl"], 1000), line(rm["butter"], 100)])
    conn.execute("UPDATE recipe_item SET needs_review = 1 WHERE position = 1 AND recipe_version_id = "
                 "(SELECT current_version_id FROM recipe WHERE id = ?)", (a,))
    run(conn, rm, [{"id": a}])
    assert [i["needs_review"] for i in get_recipe(conn, a)["items"]] == [True, False]


def test_sub_recipe_lines_kept_and_sub_recipe_is_own_candidate(conn, rm):
    sub = make(conn, "Streusel", [line(rm["butter"], 250), line(rm["mehl"], 300)])
    main = make(conn, "Kuchen", [line(rm["mehl"], 1000), {"type": "sub_recipe", "sub_recipe_id": sub, "amount_g": 550}])
    result = run(conn, rm, [{"id": sub}])
    assert [r["id"] for r in result["recipes"]] == [sub]                               # nur direkt enthalten
    assert amounts(conn, main) == [("Weizenmehl 550", 1000), ("Streusel", 550)]
    assert amounts(conn, sub) == [("Margarine", 205), ("Weizenmehl 550", 300)]


def test_archived_old_raw_material_can_be_replaced(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 100)])
    archive_raw_material(conn, rm["butter"])
    result = run(conn, rm, [{"id": a}])
    assert result["counts"]["done"] == 1 and amounts(conn, a) == [("Margarine", 82)]


def test_archive_old_when_unused(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 100)])
    b = make(conn, "B", [line(rm["butter"], 200)])
    result = run(conn, rm, [{"id": a}], archive_old=True)
    assert result["archive_old"]["done"] is False and "noch in 1 Rezept" in result["archive_old"]["reason"]
    assert get_raw_material(conn, rm["butter"])["archived"] is False
    result = run(conn, rm, [{"id": b}], archive_old=True)
    assert result["archive_old"]["done"] is True and get_raw_material(conn, rm["butter"])["archived"] is True


def test_archive_old_not_requested(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 100)])
    result = run(conn, rm, [{"id": a}])
    assert result["archive_old"]["requested"] is False and get_raw_material(conn, rm["butter"])["archived"] is False


def test_too_large_amount_is_skipped(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 900_000)])
    b = make(conn, "B", [line(rm["butter"], 100)])
    result = run(conn, rm, [{"id": a}, {"id": b}], factor="2")
    assert [s["id"] for s in result["skipped"]] == [a] and result["counts"]["done"] == 1
    assert amounts(conn, a) == [("Butter", 900_000)] and amounts(conn, b) == [("Margarine", 200)]


def test_change_log(conn, rm):
    a = make(conn, "A", [line(rm["butter"], 100)])
    run(conn, rm, [{"id": a}])
    row = conn.execute("SELECT source, action FROM change_log WHERE entity = 'recipe' AND entity_id = ? "
                       "ORDER BY id DESC LIMIT 1", (a,)).fetchone()
    assert tuple(row) == ("admin", "new_version")


# -- Versionsvergleich (C3-E10) --------------------------------------------------------------

def test_old_version_shows_current_amounts(conn, rm):
    a = make(conn, "A", [line(rm["mehl"], 1000), line(rm["butter"], 100), line(rm["salz"], 20), line(rm["salz"], 5)])
    run(conn, rm, [{"id": a}], extras=[{"raw_material_id": rm["wasser"], "factor": "0,5"}])
    rev = get_recipe(conn, a)["revision"]
    save_recipe(conn, a, {"name": "A", "items": [line(rm["mehl"], 1100), line(rm["marg"], 82), line(rm["wasser"], 50),
                                                 line(rm["salz"], 20), line(rm["salz"], 5), line(rm["milch"], 300)]},
                revision=rev, version_mode="new")
    old = get_version(conn, a, 1)
    assert [i["current"] for i in old["items"]] == [
        {"amount_g": 1100, "same": False, "missing": False},      # Mehl geändert
        {"amount_g": None, "same": False, "missing": True},       # Butter entfällt
        {"amount_g": 20, "same": True, "missing": False},         # Salz der Reihe nach
        {"amount_g": 5, "same": True, "missing": False},
    ]
    assert [(c["name"], c["amount_g"]) for c in old["current_only"]] == [("Margarine", 82), ("Wasser", 50), ("Milch", 300)]
    assert old["current_version_no"] == 3


def test_current_version_has_no_comparison(conn, rm):
    a = make(conn, "A", [line(rm["mehl"], 1000)])
    current = get_version(conn, a, 1)
    assert "current_only" not in current and "current" not in current["items"][0]
