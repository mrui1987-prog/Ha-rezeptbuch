"""Tests: Export der Rezepte als .xlsx (Modul 05, Teil C3, docs/rezepte.md Abschnitt 6.3, K05-1)."""

import io

import pytest

pytest.importorskip("openpyxl")

from openpyxl import load_workbook  # noqa: E402

from app.db import init_database  # noqa: E402
from app.exports import build_workbook  # noqa: E402
from app.imports.recipe_template import import_recipe_template  # noqa: E402
from app.raw_materials import service as rm_service  # noqa: E402
from app.recipes import groups, service  # noqa: E402


@pytest.fixture
def filled(conn):
    """Kleiner Bestand: Gruppe, Rohstoffe, Unterrezept, Hauptrezept mit allem."""
    g = groups.create_group(conn, "Brot")
    mehl = rm_service.create_raw_material(conn, {"name": "Weizenmehl 550", "type": "flour", "tolerance": "20"})
    wasser = rm_service.create_raw_material(conn, {"name": "Wasser", "tolerance": "2,5", "tolerance_unit": "percent",
                                                   "display_name": "H2O"})
    salz = rm_service.create_raw_material(conn, {"name": "Salz", "tolerance": "0"})
    rm_service.create_raw_material(conn, {"name": "Unbenutzt", "tolerance": "1"})
    vorteig = service.create_recipe(conn, {"name": "Vorteig", "items": [
        {"type": "raw_material", "raw_material_id": mehl["id"], "amount_g": 500},
        {"type": "raw_material", "raw_material_id": wasser["id"], "amount_g": 500}]})
    brot = service.create_recipe(conn, {
        "name": "Weizenbrot", "group_id": g["id"], "knead_slow_min": 5, "knead_fast_min": 6,
        "note": "=nicht rechnen, - mit Mohn", "note_display": "start", "internal_note": "Ofen 2 nehmen",
        "steps": [{"name": "Vorteig"}, {"name": "Hauptteig"}],
        "items": [{"type": "sub_recipe", "sub_recipe_id": vorteig["id"], "amount_g": 1000, "step_no": 1},
                  {"type": "raw_material", "raw_material_id": mehl["id"], "amount_g": 1500, "step_no": 2},
                  {"type": "raw_material", "raw_material_id": salz["id"], "amount_g": 0,
                   "tolerance": "2", "tolerance_unit": "g", "step_no": 2},
                  {"type": "raw_material", "raw_material_id": wasser["id"], "amount_g": 900,
                   "tolerance": "1,5", "tolerance_unit": "percent"}]})
    service.set_piece_weights(conn, brot["id"], [{"label": "Laib", "weight_g": 1000}, {"label": "Klein", "weight_g": 500}])
    service.set_batch_sizes(conn, brot["id"], [{"label": "3 Laibe", "kind": "pieces", "value": 3, "piece_weight_label": "Laib"},
                                               {"label": "Teig", "kind": "weight", "value": 3400}])
    service.unlock_recipe(conn, brot["id"], confirm=True)
    return {"brot": brot["id"], "vorteig": vorteig["id"]}


def sheets(data):
    wb = load_workbook(io.BytesIO(data))
    return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}


def snapshot(conn, recipe_id):
    r = service.get_recipe(conn, recipe_id)
    return {
        "number": r["number"], "name": r["name"], "group": r["group_name"], "knead": r["knead"], "note": r["note"],
        "note_display": r["note_display"], "internal_note": r["internal_note"],
        "steps": [s["name"] for s in r["steps"]],
        "items": [(i["type"], (i.get("raw_material") or i.get("sub_recipe"))["name"], i["amount_g"],
                   i["tolerance_override"], i["step_no"], i["needs_review"]) for i in r["items"]],
        "pieces": [(p["label"], p["weight_g"]) for p in r["piece_weights"]],
        "batches": [(b["label"], b["kind"], b["value"], b["piece_weight_label"]) for b in r["batch_sizes"]],
    }


def test_sheets_and_content(conn, filled):
    data = sheets(build_workbook(conn))
    assert list(data) == ["Info", "Rezepte", "Rezeptzeilen", "Stückgewichte", "Chargengrößen", "Rohstoffe"]
    recipes = data["Rezepte"]
    assert recipes[0][:3] == ["Import-ID", "Rezeptnummer", "Rezeptname"]
    assert [r[0] for r in recipes[1:]] == ["R1", "R2"]
    brot = recipes[2]
    assert brot[2:9] == ["Weizenbrot", "Brot", 5, 6, "=nicht rechnen, - mit Mohn", "Beginn", "Ofen 2 nehmen"]
    assert brot[9] == "öffentlich"
    lines = [r for r in data["Rezeptzeilen"][1:] if r[0] == "R2"]
    assert lines[0][4:8] == ["Unterrezept", "Vorteig", None, "R1"]
    assert lines[2][8:12] == [0, "g", 1, 0]                       # Handzugabe als 0
    assert lines[3][12:14] == ["percent", 1.5]
    rohstoffe = data["Rohstoffe"]
    assert [r[1] for r in rohstoffe[1:]] == ["Weizenmehl 550", "Wasser", "Salz"]    # nur verwendete
    assert rohstoffe[2][2:6] == ["H2O", "Standard", 2.5, "%"]


def test_text_starting_with_equals_is_text(conn, filled):
    wb = load_workbook(io.BytesIO(build_workbook(conn)))
    cell = wb["Rezepte"]["G3"]
    assert cell.value == "=nicht rechnen, - mit Mohn"
    assert cell.data_type == "s"                                    # keine Formel (B2)


def test_old_name_with_equals_exported_as_text(conn, filled):
    conn.execute("UPDATE raw_material SET name = '=SUMME(A1)' WHERE name = 'Salz'")
    wb = load_workbook(io.BytesIO(build_workbook(conn)))
    names = [c for c in wb["Rohstoffe"]["B"] if c.value == "=SUMME(A1)"]
    assert names and all(c.data_type == "s" for c in names)


def test_archived_only_on_request(conn, filled):
    extra = service.create_recipe(conn, {"name": "Altes Brot"})
    service.archive_recipe(conn, extra["id"])
    assert "Altes Brot" not in [r[2] for r in sheets(build_workbook(conn))["Rezepte"]]
    rows = sheets(build_workbook(conn, include_archived=True))["Rezepte"]
    old = next(r for r in rows if r[2] == "Altes Brot")
    assert old[9] == "archiviert"


def test_reimport_into_empty_database_is_identical(conn, filled, tmp_path):
    data = build_workbook(conn)
    target = init_database(tmp_path / "leer.db")
    report = import_recipe_template(target, data, mode="run")
    assert report["ok"] and report["counts"]["recipes"] == 2
    for name in ("Vorteig", "Weizenbrot"):
        src = next(r for r in service.list_recipes(conn, include_locked=True) if r["name"] == name)
        dst = next(r for r in service.list_recipes(target, include_locked=True) if r["name"] == name)
        assert snapshot(conn, src["id"]) == snapshot(target, dst["id"])
    # Rohstoffe mit gleichen Werten
    keys = ("number", "name", "display_name", "type", "tolerance_unit", "tolerance", "unit_size_g", "unit_label")
    used = {"Weizenmehl 550", "Wasser", "Salz"}
    a = [{k: r[k] for k in keys} for r in rm_service.list_raw_materials(conn) if r["name"] in used]
    b = [{k: r[k] for k in keys} for r in rm_service.list_raw_materials(target)]
    assert a == b
    target.close()


def test_reimport_into_same_database_is_unchanged(conn, filled):
    report = import_recipe_template(conn, build_workbook(conn), mode="check")
    assert report["ok"] and not report["needs_confirmation"]       # gleicher Inhalt: keine neue Version
    assert report["counts"]["recipes_unchanged"] == 2 and report["counts"]["recipes_new_version"] == 0
    assert report["counts"]["unchanged"] == 3                     # Rohstoffe unverändert


def test_empty_database(conn):
    data = sheets(build_workbook(conn))
    assert data["Rezepte"] == [data["Rezepte"][0]]


def test_raw_material_sheet_has_empty_conversion_columns(conn, filled):
    """C3-E7: Umrechnung im Blatt „Rohstoffe“ (leer, wird nicht gespeichert); kein Blatt „Umrechnung“ mehr."""
    rows = sheets(build_workbook(conn))["Rohstoffe"]
    header = rows[0]
    assert header[8].startswith("Umrechnung Einheit") and header[9] == "Gramm je Einheit"
    assert all(r[8] is None and r[9] is None for r in rows[1:])
    info = " ".join(str(r[0]) for r in sheets(build_workbook(conn))["Info"])
    assert "neue Version" in info and "dürfen in der Zieldatenbank" not in info
