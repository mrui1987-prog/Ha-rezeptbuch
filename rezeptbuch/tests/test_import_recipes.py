"""Tests: Vorlagen-Import .xlsx (Modul 05, Teil C3, docs/rezepte.md Abschnitt 6.2).

Die Testvorlagen erzeugt ``template_factory`` mit denselben Spalten wie die echte
Importvorlage (inklusive Formelspalten), aber ohne Betriebsdaten.
"""

import io

import pytest

pytest.importorskip("openpyxl")

from openpyxl import Workbook  # noqa: E402

from app.errors import ConflictError, PayloadTooLargeError, ValidationError  # noqa: E402
from app.imports.recipe_template import header_key, import_recipe_template  # noqa: E402
from app.raw_materials import service as rm_service  # noqa: E402
from app.recipes import service  # noqa: E402
from template_factory import build, conv_only, line, raw, recipe  # noqa: E402

BASE_RAW = [raw("Weizenmehl 550", typ="flour", tol=20, unit="g"), raw("Wasser", tol=2, unit="percent"),
            raw("Hefe", tol=5, unit="g"), raw("Salz", tol=2, unit="g"), raw("Ei", size=50, label="Ei"),
            raw("Öl"), raw("Zimt", tol=0, unit="g")]


def run(conn, data, **kw):
    return import_recipe_template(conn, data, mode=kw.pop("mode", "run"), **kw)


def simple(**kw):
    return build([recipe("R1", "Weizenbrot", group="Brot", slow=5, fast=6)],
                 [line("R1", "Weizenmehl 550", 1000, schritt="Teig"), line("R1", "Wasser", 0.6, "kg", schritt="Teig"),
                  line("R1", "Salz", 20)], BASE_RAW, **kw)


def recipe_by_name(conn, name):
    for r in service.list_recipes(conn, include_locked=True, include_archived=True):
        if r["name"] == name:
            return service.get_recipe(conn, r["id"])
    return None


# -- Grundablauf --------------------------------------------------------------------

def test_header_key_ignores_brackets():
    assert header_key("Rezeptnummer (Vorschlag)") == "rezeptnummer"
    assert header_key("Toleranz (Pflicht)") == "toleranz"
    assert header_key("  Hinweis anzeigen (Beginn/Ende) ") == "hinweis anzeigen"


def test_check_changes_nothing_and_run_imports(conn):
    report = run(conn, simple(), mode="check")
    assert report["ok"] and not report["imported"]
    assert report["counts"]["recipes"] == 1 and report["counts"]["new"] == len(BASE_RAW)
    assert service.list_recipes(conn, include_locked=True) == []
    assert rm_service.list_raw_materials(conn) == []

    report = run(conn, simple())
    assert report["imported"]
    r = recipe_by_name(conn, "Weizenbrot")
    assert r["locked"] is True                                 # M05-12: importierte Rezepte gesperrt
    assert r["group_name"] == "Brot" and report["groups_created"] == ["Brot"]
    assert r["knead"] == "5+6"
    assert [i["amount_g"] for i in r["items"]] == [1000, 600, 20]
    assert [s["name"] for s in r["steps"]] == ["Teig"]
    assert [i["step_no"] for i in r["items"]] == [1, 1, None]


def test_check_equals_run(conn):
    data = simple()
    check = run(conn, data, mode="check")
    done = run(conn, data)
    for key in ("errors", "recipes", "created", "zero_percent"):
        assert check[key] == done[key]


def test_change_log_source_import(conn):
    run(conn, simple())
    rows = conn.execute("SELECT DISTINCT source FROM change_log WHERE entity IN ('recipe', 'recipe_group')").fetchall()
    assert [r[0] for r in rows] == ["import"]


def test_existing_group_is_reused(conn):
    conn.execute("INSERT INTO recipe_group (name, sort_order) VALUES ('brot', 1)")
    report = run(conn, simple())
    assert report["groups_created"] == []
    assert recipe_by_name(conn, "Weizenbrot")["group_name"] == "brot"


def test_numbers_given_and_free(conn):
    data = build([recipe("A", "Eins", number=50), recipe("B", "Zwei"), recipe("C", "Drei", number=7)],
                 [line("A", "Salz", 1), line("B", "Salz", 1), line("C", "Salz", 1)], BASE_RAW)
    run(conn, data)
    numbers = {r["name"]: r["number"] for r in service.list_recipes(conn, include_locked=True)}
    assert numbers == {"Eins": 50, "Zwei": 51, "Drei": 7}


# -- Vorhandene Rezepte: neue Version auf Bestätigung (C3-E5) ------------------------------

def versions(conn, name):
    return service.get_recipe(conn, recipe_by_name(conn, name)["id"])


def test_existing_by_name_gets_new_version_after_confirmation(conn):
    run(conn, simple())
    before = recipe_by_name(conn, "Weizenbrot")
    data = build([recipe("X", "WEIZENBROT")], [line("X", "Salz", 1), line("X", "Wasser", 2)], BASE_RAW)
    check = run(conn, data, mode="check")
    assert check["ok"] and check["needs_confirmation"]
    assert check["counts"]["recipes_new_version"] == 1 and check["counts"]["recipes"] == 0
    assert check["recipes_updated"][0]["old_version"] == 1 and check["recipes_updated"][0]["new_version"] == 2
    with pytest.raises(ConflictError):                              # ohne Bestätigung nichts gespeichert
        run(conn, data)
    assert service.get_recipe(conn, before["id"])["version_no"] == 1
    run(conn, data, confirm_overwrite=True)
    rec = service.get_recipe(conn, before["id"])
    assert rec["version_no"] == 2 and len(rec["items"]) == 2 and rec["number"] == 1
    assert [v["version_no"] for v in rec["versions"]] == [2, 1] or len(rec["versions"]) == 2
    old = service.get_version(conn, rec["id"], 1)
    assert len(old["items"]) == 3                                    # alte Version bleibt erhalten
    assert len(service.list_recipes(conn, include_locked=True)) == 1  # kein zweites Rezept


def test_existing_by_number_keeps_number_and_group(conn):
    run(conn, simple())
    data = build([recipe("X", "Weizenbrot neu", number=1)], [line("X", "Salz", 5)], BASE_RAW)
    run(conn, data, confirm_overwrite=True)
    rec = service.get_recipe(conn, service.list_recipes(conn, include_locked=True)[0]["id"])
    assert rec["number"] == 1 and rec["name"] == "Weizenbrot neu" and rec["version_no"] == 2
    assert rec["group_name"] == "Brot"                               # Gruppe leer in der Datei = unverändert


def test_same_content_is_unchanged(conn):
    run(conn, simple())
    check = run(conn, simple(), mode="check")
    assert check["ok"] and not check["needs_confirmation"] and check["counts"]["recipes_unchanged"] == 1
    run(conn, simple())
    assert service.get_recipe(conn, recipe_by_name(conn, "Weizenbrot")["id"])["version_no"] == 1


def test_frozen_version_always_new(conn):
    run(conn, simple())
    rid = recipe_by_name(conn, "Weizenbrot")["id"]
    conn.execute("UPDATE recipe_version SET frozen_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
                 "WHERE id = (SELECT current_version_id FROM recipe WHERE id = ?)", (rid,))   # schon verwogen
    data = build([recipe("X", "Weizenbrot")], [line("X", "Salz", 9)], BASE_RAW)
    run(conn, data, confirm_overwrite=True)
    assert service.get_recipe(conn, rid)["version_no"] == 2


def test_number_and_name_of_different_recipes_is_error(conn):
    run(conn, build([recipe("A", "Brot", number=1), recipe("B", "Kuchen", number=2)],
                    [line("A", "Salz", 1), line("B", "Salz", 1)], BASE_RAW))
    data = build([recipe("X", "Kuchen", number=1)], [line("X", "Salz", 1)], BASE_RAW)
    report = run(conn, data, mode="check")
    assert not report["ok"] and "Nummer 1 gehört zu" in report["errors"][0]["message"]


def test_archived_recipe_is_error(conn):
    run(conn, simple())
    rid = recipe_by_name(conn, "Weizenbrot")["id"]
    service.unlock_recipe(conn, rid, confirm=True)
    service.archive_recipe(conn, rid)
    data = build([recipe("X", "Anderes", number=1)], [line("X", "Salz", 1)], BASE_RAW)
    report = run(conn, data, mode="check")
    assert not report["ok"] and "archiviert" in report["errors"][0]["message"]


def test_update_keeps_internal_note_when_column_empty(conn):
    run(conn, simple())
    rid = recipe_by_name(conn, "Weizenbrot")["id"]
    conn.execute("UPDATE recipe SET internal_note = 'wichtig' WHERE id = ?", (rid,))
    data = build([recipe("X", "Weizenbrot")], [line("X", "Salz", 7)], BASE_RAW)
    run(conn, data, confirm_overwrite=True)
    assert service.get_recipe(conn, rid)["internal_note"] == "wichtig"


def test_update_with_review_mark_locks_recipe(conn):
    run(conn, simple())
    rid = recipe_by_name(conn, "Weizenbrot")["id"]
    service.unlock_recipe(conn, rid, confirm=True)
    data = build([recipe("X", "Weizenbrot")], [line("X", "Salz", 7, flag="*")], BASE_RAW)
    run(conn, data, confirm_overwrite=True)
    rec = service.get_recipe(conn, rid)
    assert rec["locked"] is True and rec["review_count"] == 1


def test_duplicates_in_file(conn):
    data = build([recipe("A", "Brot", number=3), recipe("A", "Kuchen"), recipe("B", "brot", number=3)],
                 [line("A", "Salz", 1)], BASE_RAW)
    report = run(conn, data, mode="check")
    messages = " | ".join(e["message"] for e in report["errors"])
    assert "Import-ID „A“ steht mehrfach" in messages
    assert "Rezeptnummer 3 steht mehrfach" in messages
    assert "Rezeptname „brot“ steht mehrfach" in messages


def test_formula_start_name_rejected(conn):
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(build([recipe("A", "Platzhalter")], [line("A", "Salz", 1)], BASE_RAW)))
    cell = wb["Rezepte"]["C2"]
    cell.value = "=HYPERLINK(1)"
    cell.data_type = "s"                 # Textzelle (in Excel: Apostroph davor), keine Formel
    out = io.BytesIO()
    wb.save(out)
    report = run(conn, out.getvalue(), mode="check")
    assert any("darf nicht mit" in e["message"] for e in report["errors"])


# -- Mengen (K05-6) ---------------------------------------------------------------------

def test_amount_conversion_and_rounding(conn):
    data = build([recipe("R", "Biskuit")],
                 [line("R", "Ei", 36, "Stück"), line("R", "Öl", 100, "ml", flag="*"), line("R", "Salz", 2.5),
                  line("R", "Weizenmehl 550", 1.2345, "kg"), line("R", "Zimt", None, "Maß")],
                 BASE_RAW, units=[("Stück Ei", 50), ("ml Öl", 0.92), ("Maß Zimt", None)])
    run(conn, data)
    r = recipe_by_name(conn, "Biskuit")
    assert [i["amount_g"] for i in r["items"]] == [1800, 92, 3, 1235, 0]     # kaufmännisch gerundet
    assert r["items"][4]["hand_addition"] is True                              # leer = Handzugabe
    # seit 0.5.8 (C3-E7): jede umgerechnete Zeile bekommt „*“, g/kg und Handzugabe nicht
    assert [i["needs_review"] for i in r["items"]] == [True, True, False, False, False]


def test_missing_factor_is_error(conn):
    data = build([recipe("R", "Kompott")], [line("R", "Zimt", 2, "Maß")], BASE_RAW, units=[("Maß Zimt", None)])
    report = run(conn, data, mode="check")
    assert not report["ok"]
    err = report["errors"][0]
    assert err["sheet"] == "Rezeptzeilen" and err["line"] == 2 and "Maß Zimt" in err["message"]


def test_unknown_unit_is_error(conn):
    data = build([recipe("R", "Kompott")], [line("R", "Zimt", 2, "Prise")], BASE_RAW)
    report = run(conn, data, mode="check")
    assert "fehlt" in report["errors"][0]["message"]


def test_cached_formula_value_differs_gives_hint(conn):
    data = build([recipe("R", "Brot")], [line("R", "Salz", 20)], BASE_RAW, cached_grams={2: 25})
    report = run(conn, data, mode="check")
    assert report["ok"]
    assert any("berechnet 20 g" in h["message"] and "25" in h["message"] for h in report["hints"])


def test_text_number_with_comma(conn):
    data = build([recipe("R", "Brot")], [line("R", "Wasser", "0,75", "kg")], BASE_RAW)
    run(conn, data)
    assert recipe_by_name(conn, "Brot")["items"][0]["amount_g"] == 750


def test_negative_amount_is_error(conn):
    data = build([recipe("R", "Brot")], [line("R", "Salz", -5)], BASE_RAW)
    assert not run(conn, data, mode="check")["ok"]


# -- Rohstoffe -------------------------------------------------------------------------------

def test_unknown_raw_material_is_error(conn):
    data = build([recipe("R", "Brot")], [line("R", "Roggenmehl 1150", 100)], BASE_RAW)
    report = run(conn, data, mode="check")
    err = report["errors"][0]
    assert err["sheet"] == "Rezeptzeilen" and "Roggenmehl 1150" in err["message"] and err["column"] == "Zutat"


def test_raw_material_from_database_without_sheet(conn):
    rm_service.create_raw_material(conn, {"name": "Roggenmehl 1150", "type": "flour", "tolerance": "10"})
    data = build([recipe("R", "Roggenbrot")], [line("R", "roggenmehl 1150", 500)], skip=("Rohstoffe",))
    report = run(conn, data)
    assert report["counts"]["new"] == 0
    assert recipe_by_name(conn, "Roggenbrot")["sums"]["flour_g"] == 500


def test_archived_raw_material_is_error(conn):
    rm = rm_service.create_raw_material(conn, {"name": "Alte Hefe", "tolerance": "5"})
    rm_service.archive_raw_material(conn, rm["id"])
    data = build([recipe("R", "Brot")], [line("R", "Alte Hefe", 10)], skip=("Rohstoffe",))
    report = run(conn, data, mode="check")
    assert "archiviert" in report["errors"][0]["message"]


def test_raw_materials_overwritten_need_confirmation(conn):
    rm_service.create_raw_material(conn, {"name": "Salz", "tolerance": "5", "display_name": "Salz fein"})
    data = simple()
    with pytest.raises(ConflictError) as exc:
        run(conn, data)
    assert exc.value.code == "overwrite_confirmation_required"
    assert exc.value.message.startswith("1 Rohstoff wird überschrieben")  # B2 (0.5.11)
    assert service.list_recipes(conn, include_locked=True) == []         # nichts gespeichert
    report = run(conn, data, confirm_overwrite=True)
    assert report["imported"] and report["counts"]["overwritten"] == 1
    salz = rm_service.list_raw_materials(conn, search="Salz")[0]
    assert salz["tolerance"] == 2 and salz["display_name"] is None       # K05-2b: leerer Kurzname wird geleert


def test_new_raw_material_empty_tolerance_zero_percent(conn):
    report = run(conn, simple(), mode="check")
    names = {z["name"] for z in report["zero_percent"]}
    assert names == {"Ei", "Öl"}


def test_footnote_rows_are_skipped(conn):
    report = run(conn, simple(), mode="check")
    assert report["ok"]
    assert sum(1 for h in report["hints"] if "Anmerkung" in h["message"]) == 2


# -- Unterrezepte und Kreise (R05-10) ------------------------------------------------------

def test_sub_recipe_created_first(conn):
    data = build([recipe("M", "Marmorkuchen"), recipe("K", "Kakaomasse")],
                 [line("M", "Kakaomasse", 400, art="Unterrezept", sub="K"), line("M", "Ei", 6, "Stück"),
                  line("K", "Öl", 100, "ml")],
                 BASE_RAW, units=[("Stück Ei", 50), ("ml Öl", 0.92)])
    run(conn, data)
    main = recipe_by_name(conn, "Marmorkuchen")
    assert main["items"][0]["type"] == "sub_recipe" and main["items"][0]["sub_recipe"]["name"] == "Kakaomasse"
    assert main["number"] == 1 and recipe_by_name(conn, "Kakaomasse")["number"] == 2


def test_cycle_in_file(conn):
    data = build([recipe("A", "Hauptteig"), recipe("B", "Vorteig"), recipe("C", "Brot")],
                 [line("A", "x", 100, art="Unterrezept", sub="B"), line("B", "x", 100, art="Unterrezept", sub="A"),
                  line("C", "Salz", 10)], BASE_RAW)
    report = run(conn, data, mode="check")
    assert not report["ok"]
    assert any("Kreis bei Unterrezepten: Hauptteig → Vorteig → Hauptteig" in e["message"] for e in report["errors"])
    assert [r["name"] for r in report["recipes"]] == ["Brot"]


def test_unknown_sub_recipe(conn):
    data = build([recipe("A", "Hauptteig")], [line("A", "x", 100, art="Unterrezept", sub="Z")], BASE_RAW)
    report = run(conn, data, mode="check")
    assert "Unterrezept „Z“" in report["errors"][0]["message"]


def test_parent_of_failed_sub_recipe_not_created(conn):
    data = build([recipe("A", "Hauptteig"), recipe("B", "Vorteig")],
                 [line("A", "x", 100, art="Unterrezept", sub="B"), line("B", "Gibtsnicht", 10)], BASE_RAW)
    report = run(conn, data, mode="check")
    messages = [e["message"] for e in report["errors"]]
    assert any("Gibtsnicht" in m for m in messages)
    assert any("Unterrezept „B“ hat Fehler" in m for m in messages)


# -- Zeilen, Schritte, Toleranz ----------------------------------------------------------------

def test_positions_and_steps(conn):
    data = build([recipe("R", "Brot")],
                 [line("R", "Salz", 20, schritt="Hauptteig", pos=3), line("R", "Hefe", 10, schritt="Vorteig", pos=1),
                  line("R", "Wasser", 300, schritt="Hauptteig", pos=2)], BASE_RAW)
    run(conn, data)
    r = recipe_by_name(conn, "Brot")
    assert [i["raw_material"]["name"] for i in r["items"]] == ["Hefe", "Wasser", "Salz"]
    assert [s["name"] for s in r["steps"]] == ["Vorteig", "Hauptteig"]
    assert [i["step_no"] for i in r["items"]] == [1, 2, 2]


def test_line_tolerance(conn):
    data = build([recipe("R", "Brot")],
                 [line("R", "Salz", 20, tol_unit="percent", tol=2.5), line("R", "Hefe", 10, tol=3)], BASE_RAW)
    run(conn, data)
    items = recipe_by_name(conn, "Brot")["items"]
    assert items[0]["tolerance_override"] == {"unit": "percent", "value": 2.5}
    assert items[1]["tolerance_override"] == {"unit": "g", "value": 3}


def test_tolerance_unit_without_value_is_error(conn):
    data = build([recipe("R", "Brot")], [line("R", "Salz", 20, tol_unit="g")], BASE_RAW)
    report = run(conn, data, mode="check")
    assert report["errors"][0]["column"] == "Toleranzwert"


def test_service_error_located_on_line(conn):
    data = build([recipe("R", "Brot")], [line("R", "Salz", 20), line("R", "Hefe", 10, tol_unit="percent", tol=150)],
                 BASE_RAW)
    report = run(conn, data, mode="check")
    err = report["errors"][0]
    assert err["sheet"] == "Rezeptzeilen" and err["line"] == 3 and "100" in err["message"]


def test_note_display_values(conn):
    data = build([recipe("A", "Eins", note="- mit Mohn", display="Beginn"), recipe("B", "Zwei", display="nur am Ende"),
                  recipe("C", "Drei", display="am Anfang und am Ende"), recipe("D", "Vier")],
                 [line("A", "Salz", 1)], BASE_RAW)
    run(conn, data)
    assert recipe_by_name(conn, "Eins")["note"] == "- mit Mohn"           # Hinweistext darf mit „-“ beginnen
    assert [recipe_by_name(conn, n)["note_display"] for n in ("Eins", "Zwei", "Drei", "Vier")] == \
        ["start", "end", "start", "end"]


def test_bad_note_display(conn):
    data = build([recipe("A", "Eins", display="Mitte")], [line("A", "Salz", 1)], BASE_RAW)
    assert not run(conn, data, mode="check")["ok"]


def test_recipe_without_lines_is_hint(conn):
    data = build([recipe("A", "Entwurf")], [], BASE_RAW)
    report = run(conn, data)
    assert report["imported"] and any("keine Zeilen" in h["message"] for h in report["hints"])


def test_line_with_unknown_import_id(conn):
    data = build([recipe("A", "Eins")], [line("B", "Salz", 1)], BASE_RAW)
    assert "„B“ gibt es im Blatt „Rezepte“ nicht" in run(conn, data, mode="check")["errors"][0]["message"]


# -- Stückgewichte und Chargengrößen ------------------------------------------------------------

def test_pieces_and_batches(conn):
    data = build([recipe("R", "Brötchenteig")],
                 [line("R", "Weizenmehl 550", 2000), line("R", "Wasser", 1200)], BASE_RAW,
                 pieces=[("R", "Ballen", 1550, 2), ("R", "Stück", 65, 1)],
                 batches=[("R", "1 Teig", "Gewicht", None, None, 1), ("R", "30 Stück", "Stück", 30, "Stück", 2),
                          ("R", "5 kg", "Gewicht", 5000, None, 3)])
    run(conn, data)
    r = recipe_by_name(conn, "Brötchenteig")
    assert [(p["label"], p["weight_g"]) for p in r["piece_weights"]] == [("Stück", 65), ("Ballen", 1550)]
    assert [(b["label"], b["kind"], b["value"], b["piece_weight_label"]) for b in r["batch_sizes"]] == [
        ("1 Teig", "weight", 3200, None), ("30 Stück", "pieces", 30, "Stück"), ("5 kg", "weight", 5000, None)]


def test_batch_with_unknown_piece_weight(conn):
    data = build([recipe("R", "Brot")], [line("R", "Salz", 1)], BASE_RAW,
                 batches=[("R", "10 Stück", "Stück", 10, "Gibtsnicht")])
    report = run(conn, data, mode="check")
    assert report["errors"][0]["sheet"] == "Chargengrößen"


def test_duplicate_piece_label(conn):
    data = build([recipe("R", "Brot")], [line("R", "Salz", 1)], BASE_RAW,
                 pieces=[("R", "Stück", 65), ("R", "stück", 70)])
    report = run(conn, data, mode="check")
    assert report["errors"][0]["sheet"] == "Stückgewichte"


# -- Alles oder nichts ------------------------------------------------------------------------

def test_all_or_nothing(conn):
    data = build([recipe("A", "Gut"), recipe("B", "Schlecht")],
                 [line("A", "Salz", 1), line("B", "Gibtsnicht", 1)], BASE_RAW)
    with pytest.raises(ValidationError) as exc:
        run(conn, data)
    assert exc.value.code == "import_failed"
    assert service.list_recipes(conn, include_locked=True) == []
    assert rm_service.list_raw_materials(conn) == []
    assert conn.execute("SELECT count(*) FROM recipe_group").fetchone()[0] == 0


def test_internal_note_imported(conn):
    wb_data = build([recipe("A", "Eins")], [line("A", "Salz", 1)], BASE_RAW)
    # Spalte „Notiz intern“ anhängen
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(wb_data))
    ws = wb["Rezepte"]
    ws.cell(row=1, column=ws.max_column + 1, value="Notiz intern")
    ws.cell(row=2, column=ws.max_column, value="nur für mich")
    out = io.BytesIO()
    wb.save(out)
    run(conn, out.getvalue())
    assert recipe_by_name(conn, "Eins")["internal_note"] == "nur für mich"


# -- Datei -------------------------------------------------------------------------------------

def test_not_an_xlsx(conn):
    with pytest.raises(ValidationError, match="kann nicht gelesen"):
        run(conn, b"Nummer;Name\n1;Salz\n", mode="check")


def test_xlsb_is_refused(conn):
    import zipfile
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("xl/workbook.bin", b"x")
    with pytest.raises(ValidationError, match="xlsb"):
        run(conn, out.getvalue(), mode="check")


def test_empty_file(conn):
    with pytest.raises(ValidationError, match="leer"):
        run(conn, b"", mode="check")


def test_too_large(conn):
    with pytest.raises(PayloadTooLargeError):
        run(conn, b"x" * (5 * 1024 * 1024 + 1), mode="check")


def test_missing_sheets(conn):
    wb = Workbook()
    wb.active.title = "Irgendwas"
    out = io.BytesIO()
    wb.save(out)
    report = run(conn, out.getvalue(), mode="check")
    assert {e["message"] for e in report["errors"]} == {"Das Blatt „Rezepte“ fehlt.", "Das Blatt „Rezeptzeilen“ fehlt."}


def test_bad_mode(conn):
    with pytest.raises(ValidationError):
        run(conn, simple(), mode="los")


# -- Umrechnung im Blatt „Rohstoffe“ (C3-E7, 0.5.8) ------------------------------------------

CONV_RAW = [raw("Weizenmehl 550", typ="flour", tol=20, unit="g"), raw("Eier", conv_unit="Stück", conv=65),
            raw("Öl", conv_unit="ml", conv=0.92), raw("Salz", tol=2, unit="g")]


def test_conversion_from_raw_material_sheet(conn):
    data = build([recipe("R", "Biskuit")],
                 [line("R", "Eier", 20, "Stück"), line("R", "Öl", 1.5, "l"), line("R", "Öl", 100, "ml"),
                  line("R", "Weizenmehl 550", 0.5, "kg"), line("R", "Salz", 5)],
                 CONV_RAW, skip=("Umrechnung",))
    report = run(conn, data)
    r = recipe_by_name(conn, "Biskuit")
    assert [i["amount_g"] for i in r["items"]] == [1300, 1380, 92, 500, 5]          # l über ml × 1 000 (E7c)
    assert [i["needs_review"] for i in r["items"]] == [True, True, True, False, False]
    assert [c["text"] for c in report["conversions"]] == [
        "20 Stück × 65 g = 1 300 g", "1,5 l × 920 g = 1 380 g", "100 ml × 0,92 g = 92 g"]
    assert {c["source"] for c in report["conversions"]} == {"Rohstoffe"}
    assert report["conversions"][0]["recipe"] == "Biskuit" and report["conversions"][0]["line"] == 2
    assert report["counts"]["conversions"] == 3
    assert any("3 Zeilen umgerechnet" in h["message"] for h in report["hints"])
    assert not any("veraltet" in h["message"] for h in report["hints"])
    # Faktor wird nicht gespeichert (M02-2): der Rohstoff hat keine neuen Felder
    eier = rm_service.list_raw_materials(conn, search="Eier")[0]
    assert "conv" not in " ".join(eier.keys())


def test_liter_factor_gives_milliliter(conn):
    data = build([recipe("R", "Suppe")], [line("R", "Milch", 250, "ml")],
                 [raw("Milch", conv_unit="l", conv=1030)], skip=("Umrechnung",))
    run(conn, data)
    assert recipe_by_name(conn, "Suppe")["items"][0]["amount_g"] == 258        # 250 × 1,03 = 257,5 → 258


def test_missing_conversion_names_raw_material_sheet(conn):
    data = build([recipe("R", "Biskuit")], [line("R", "Eier", 4, "Stück")], [raw("Eier")], skip=("Umrechnung",))
    report = run(conn, data, mode="check")
    err = report["errors"][0]
    assert err["sheet"] == "Rezeptzeilen" and err["column"] == "Einheit Original"
    assert "Blatt „Rohstoffe“" in err["message"] and "Eier" in err["message"]


def test_conversion_for_other_unit_is_missing(conn):
    data = build([recipe("R", "Biskuit")], [line("R", "Eier", 4, "Maß")], CONV_RAW, skip=("Umrechnung",))
    assert "fehlt" in run(conn, data, mode="check")["errors"][0]["message"]


@pytest.mark.parametrize("unit, factor, column, text", [
    (None, 65, "Umrechnung Einheit", "Umrechnung Einheit fehlt"),
    ("Stück", None, "Gramm je Einheit", "Gramm je Einheit fehlt"),
    ("Stück", 0, "Gramm je Einheit", "größer 0"),
    ("Stück", "viel", "Gramm je Einheit", "Zahl"),
])
def test_bad_conversion_values(conn, unit, factor, column, text):
    data = build([recipe("R", "Brot")], [line("R", "Salz", 5)], [raw("Salz", tol=2, unit="g"),
                 raw("Eier", conv_unit=unit, conv=factor)], skip=("Umrechnung",))
    report = run(conn, data, mode="check")
    err = report["errors"][0]
    assert err["sheet"] == "Rohstoffe" and err["line"] == 3 and err["column"] == column and text in err["message"]


def test_conversion_for_g_is_ignored_with_hint(conn):
    data = build([recipe("R", "Brot")], [line("R", "Salz", 5)], [raw("Salz", tol=2, unit="g", conv_unit="g", conv=1)],
                 skip=("Umrechnung",))
    report = run(conn, data, mode="check")
    assert report["ok"] and any("nicht nötig" in h["message"] for h in report["hints"])


def test_row_with_only_conversion_keeps_existing_raw_material(conn):
    """E7b: Name + Umrechnung ändert einen vorhandenen Rohstoff nicht (Kurzname, Gebinde bleiben)."""
    rm_service.create_raw_material(conn, {"name": "Eier", "tolerance": "5", "display_name": "Ei",
                                          "unit_size_g": "55", "unit_label": "Ei"})
    data = build([recipe("R", "Biskuit")], [line("R", "eier", 10, "Stück")], [conv_only("Eier", "Stück", 60)],
                 skip=("Umrechnung",))
    report = run(conn, data)                                       # keine Bestätigung nötig
    assert report["imported"] and report["counts"]["overwritten"] == 0 and report["counts"]["unchanged"] == 1
    eier = rm_service.list_raw_materials(conn, search="Eier")[0]
    assert eier["display_name"] == "Ei" and eier["unit_size_g"] == 55
    assert recipe_by_name(conn, "Biskuit")["items"][0]["amount_g"] == 600


def test_row_with_only_conversion_by_number(conn):
    rm = rm_service.create_raw_material(conn, {"name": "Eier", "tolerance": "5", "display_name": "Ei"})
    data = build([recipe("R", "Biskuit")], [line("R", "Eier", 2, "Stück")],
                 [conv_only(None, "Stück", 50, number=rm["number"])], skip=("Umrechnung",))
    run(conn, data)
    assert recipe_by_name(conn, "Biskuit")["items"][0]["amount_g"] == 100
    assert rm_service.list_raw_materials(conn, search="Eier")[0]["display_name"] == "Ei"


def test_row_with_only_conversion_creates_new_raw_material(conn):
    data = build([recipe("R", "Biskuit")], [line("R", "Wachteleier", 12, "Stück")],
                 [conv_only("Wachteleier", "Stück", 10)], skip=("Umrechnung",))
    report = run(conn, data)
    assert report["counts"]["new"] == 1 and {z["name"] for z in report["zero_percent"]} == {"Wachteleier"}
    assert recipe_by_name(conn, "Biskuit")["items"][0]["amount_g"] == 120


def test_full_row_with_conversion_still_overwrites(conn):
    rm_service.create_raw_material(conn, {"name": "Eier", "tolerance": "5", "display_name": "Ei"})
    data = build([recipe("R", "Biskuit")], [line("R", "Eier", 2, "Stück")],
                 [raw("Eier", tol=5, unit="g", conv_unit="Stück", conv=50)], skip=("Umrechnung",))
    with pytest.raises(ConflictError):
        run(conn, data)                                            # Kurzname würde geleert → Bestätigung (K05-2)
    run(conn, data, confirm_overwrite=True)
    assert rm_service.list_raw_materials(conn, search="Eier")[0]["display_name"] is None


def test_old_conversion_sheet_still_read_with_hint(conn):
    """E7a: alte Vorlagen mit Blatt „Umrechnung“ bleiben importierbar (ToDo Modul 14: entfernen)."""
    data = build([recipe("R", "Biskuit")], [line("R", "Ei", 3, "Stück")], BASE_RAW, units=[("Stück Ei", 50)])
    report = run(conn, data)
    assert recipe_by_name(conn, "Biskuit")["items"][0]["amount_g"] == 150
    assert report["conversions"][0]["source"] == "Umrechnung"
    assert recipe_by_name(conn, "Biskuit")["items"][0]["needs_review"] is True
    assert any("veraltet" in h["message"] for h in report["hints"])


def test_empty_old_conversion_sheet_gives_no_hint(conn):
    report = run(conn, simple(footnotes=False), mode="check")
    assert not any("veraltet" in h["message"] for h in report["hints"])


def test_raw_material_sheet_wins_over_old_sheet(conn):
    data = build([recipe("R", "Biskuit")], [line("R", "Eier", 2, "Stück")], [raw("Eier", conv_unit="Stück", conv=65)],
                 units=[("Stück Eier", 50)])
    report = run(conn, data)
    assert recipe_by_name(conn, "Biskuit")["items"][0]["amount_g"] == 130
    assert report["conversions"][0]["source"] == "Rohstoffe"


def test_review_column_still_works_without_conversion(conn):
    data = build([recipe("R", "Brot")], [line("R", "Salz", 5, flag="*"), line("R", "Weizenmehl 550", 100)], BASE_RAW)
    run(conn, data)
    assert [i["needs_review"] for i in recipe_by_name(conn, "Brot")["items"]] == [True, False]


# -- Musterdaten (C3-E11, 0.5.8) -----------------------------------------------------------------

def _with_samples(extra_recipes=(), extra_lines=(), extra_raw=()):
    """Vorlage mit den Musterdaten der Mustervorlage und optional eigenen Zeilen."""
    return build([recipe("M1", "Schoko-Biskuit (Muster)"), recipe("M2", "Schwarzwälder Kirschtorte (Muster)"),
                  *extra_recipes],
                 [line("M1", "Muster Zucker", 180), line("M2", "Schoko-Biskuit (Muster)", 720, art="Unterrezept", sub="M1"),
                  line("M2", "Muster Ei", 2, "Stück"), *extra_lines],
                 [raw("Muster Zucker"), raw("Muster Ei", conv_unit="Stück", conv=50), *extra_raw],
                 pieces=[("M2", "Stück (1/16)", 170)], batches=[("M2", "16 Stück", "Stück", 16, "Stück (1/16)")],
                 skip=("Umrechnung",))


def test_sample_data_is_ignored(conn):
    report = run(conn, _with_samples(), mode="check")
    assert report["ok"] and report["nothing_to_import"]
    assert report["counts"]["samples_recipes"] == 2 and report["counts"]["samples_raw_materials"] == 2
    messages = " ".join(h["message"] for h in report["hints"])
    assert "2 Musterrezepte und 2 Musterrohstoffe" in messages and "nur Musterdaten" in messages
    run(conn, _with_samples())
    assert service.list_recipes(conn, include_locked=True) == [] and rm_service.list_raw_materials(conn) == []


def test_own_rows_next_to_sample_data_are_imported(conn):
    data = _with_samples([recipe("R1", "Weizenbrot")], [line("R1", "Weizenmehl 550", 1000)],
                         [raw("Weizenmehl 550", typ="flour", tol=20, unit="g")])
    report = run(conn, data)
    assert report["imported"] and not report["nothing_to_import"]
    assert [r["name"] for r in service.list_recipes(conn, include_locked=True)] == ["Weizenbrot"]
    assert [m["name"] for m in rm_service.list_raw_materials(conn)] == ["Weizenmehl 550"]
    assert not any("nur Musterdaten" in h["message"] for h in report["hints"])


def test_include_samples_imports_them(conn):
    report = run(conn, _with_samples(), include_samples=True)
    assert report["counts"]["samples_recipes"] == 0 and len(report["recipes"]) == 2
    torte = recipe_by_name(conn, "Schwarzwälder Kirschtorte (Muster)")
    assert [i["amount_g"] for i in torte["items"]] == [720, 100] and len(torte["batch_sizes"]) == 1


def test_already_imported_samples_are_left_alone(conn):
    run(conn, _with_samples(), include_samples=True)
    torte = recipe_by_name(conn, "Schwarzwälder Kirschtorte (Muster)")
    report = run(conn, _with_samples())                           # erneuter Import: keine neue Version (E11-5)
    assert report["recipes_updated"] == [] and report["changes"] == []
    assert recipe_by_name(conn, "Schwarzwälder Kirschtorte (Muster)")["version_no"] == torte["version_no"]


def test_own_recipe_using_sample_as_sub_recipe_is_error(conn):
    data = _with_samples([recipe("R1", "Torte groß")], [line("R1", "x", 500, art="Unterrezept", sub="M1")])
    report = run(conn, data, mode="check")
    assert any("Musterrezept" in e["message"] for e in report["errors"])


def test_sample_name_matching_ignores_case(conn):
    data = build([recipe("X", "schwarzwälder kirschtorte (muster)")], [line("X", "Salz", 5)], BASE_RAW)
    report = run(conn, data, mode="check")
    assert report["counts"]["samples_recipes"] == 1 and report["recipes"] == []
