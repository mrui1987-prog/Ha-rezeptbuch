"""Tests: Rohstoff-CSV-Import mit Überschreiben (Modul 05, Teil C1; docs/rezepte.md 6.1, K05-2, M05-13)."""

import pytest

from app.errors import ConflictError, PayloadTooLargeError, ValidationError
from app.imports import import_raw_materials_csv, parse_csv
from app.raw_materials import (
    archive_raw_material,
    build_csv,
    create_raw_material,
    get_raw_material,
    list_raw_materials,
)

from conftest import add_item, add_recipe

HEADER = ("Nummer;Name;Kurzname;Typ;Toleranz;Toleranzeinheit;Gebindegröße g;Gebindebezeichnung;"
          "Herkunft;archiviert;geändert am")


def csv_bytes(*lines, header=HEADER, encoding="utf-8", bom=False):
    text = "\r\n".join([header, *lines]) + "\r\n"
    data = text.encode(encoding)
    return (b"\xef\xbb\xbf" + data) if bom else data


def check(conn, data):
    return import_raw_materials_csv(conn, data, mode="check")


def run(conn, data, confirm=False):
    return import_raw_materials_csv(conn, data, mode="run", confirm_overwrite=confirm)


def names(conn, archived=True):
    return {r["name"]: r for r in list_raw_materials(conn, include_archived=archived)}


def make(conn, name, **kw):
    data = {"name": name, "tolerance": 20}
    data.update(kw)
    return create_raw_material(conn, data)


def import_log(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT source, action, entity_id FROM change_log WHERE source = 'import' ORDER BY id")]


# -- Neue Rohstoffe -----------------------------------------------------------------

def test_new_raw_materials_both_spellings_and_bom(conn):
    data = csv_bytes(
        ";Weizenmehl 550;;Mehl;2,5;%;25000;Sack;eigen;nein;",
        ";Roggenmehl 1150;;flour;2.5;percent;;;own;0;",
        "50;Zucker;;Standard;10;g;;;;;",
        bom=True)
    report = run(conn, data)
    assert report["imported"] and report["counts"]["new"] == 3
    rows = names(conn)
    assert rows["Weizenmehl 550"]["type"] == "flour"
    assert rows["Weizenmehl 550"]["tolerance"] == 2.5
    assert rows["Weizenmehl 550"]["unit_size_g"] == 25000
    assert rows["Roggenmehl 1150"]["tolerance_unit"] == "percent"
    assert rows["Zucker"]["number"] == 50
    assert all(r["source"] == "own" for r in rows.values())
    assert [a for _, a, _ in import_log(conn)] == ["create"] * 3


def test_new_with_empty_tolerance_gets_zero_percent_and_is_listed(conn):
    report = run(conn, csv_bytes(";Vanillezucker;;;;g;;;;;", ";Salz;;;0;%;;;;;"))
    item = names(conn)["Vanillezucker"]
    assert (item["tolerance"], item["tolerance_unit"]) == (0, "percent")    # nicht 0 g (Handzugabe)
    reasons = {z["name"]: z["reason"] for z in report["zero_percent"]}
    assert reasons == {"Vanillezucker": "Toleranz leer → 0 %", "Salz": "Toleranz 0 %"}


def test_excel_number_formats(conn):
    run(conn, csv_bytes("12,0;Mehlsack;;Mehl;1;g;25.000;Sack;;;"))
    item = names(conn)["Mehlsack"]
    assert (item["number"], item["unit_size_g"]) == (12, 25000)


def test_windows_encoding_from_excel(conn):
    report = run(conn, csv_bytes(";Weizenmehl Typ 550 (Mühle);;Mehl;2;g;;;;;", encoding="cp1252"))
    assert "Weizenmehl Typ 550 (Mühle)" in names(conn)
    assert report["encoding"] == "cp1252"
    assert any("UTF-8" in h["message"] for h in report["hints"])


def test_comma_delimiter_and_missing_columns(conn):
    run(conn, csv_bytes("Hefe,5", header="Name,Toleranz"))
    item = names(conn)["Hefe"]
    assert (item["tolerance"], item["tolerance_unit"], item["type"]) == (5, "g", "standard")


def test_similar_name_hint(conn):
    make(conn, "Margarine")
    report = check(conn, csv_bytes(";Marrgarine;;;5;g;;;;;"))
    assert report["ok"]
    assert any("Margarine" in h["message"] for h in report["hints"])


def test_new_archived_row(conn):
    run(conn, csv_bytes(";Altes Mehl;;Mehl;1;g;;;;ja;"))
    assert names(conn)["Altes Mehl"]["archived"] is True


# -- Überschreiben (K05-2) -----------------------------------------------------------

def test_overwrite_by_number(conn):
    item = make(conn, "Zucker", display_name="Zucker")
    data = csv_bytes(f"{item['number']};Zucker fein;;Standard;3,0;%;;;;;")
    report = check(conn, data)
    assert report["counts"]["overwritten"] == 1 and report["needs_confirmation"]
    fields = {f["field"]: (f["old"], f["new"]) for f in report["changes"][0]["fields"]}
    assert fields == {"Name": ("Zucker", "Zucker fein"), "Kurzname": ("Zucker", "(leer)"),
                      "Toleranz": ("20 g", "3,0 %")}
    run(conn, data, confirm=True)
    after = get_raw_material(conn, item["id"])
    assert (after["name"], after["display_name"], after["tolerance"], after["tolerance_unit"]) == \
        ("Zucker fein", None, 3.0, "percent")
    assert after["number"] == item["number"] and after["source"] == "own"
    assert import_log(conn) == [("import", "update", item["id"])]


def test_overwrite_by_name_without_number(conn):
    item = make(conn, "Butter")
    run(conn, csv_bytes(";butter;;;8;g;250;Stück;;;"), confirm=True)
    after = get_raw_material(conn, item["id"])
    assert (after["name"], after["tolerance"], after["unit_size_g"]) == ("butter", 8, 250)
    assert len(list_raw_materials(conn)) == 1


def test_empty_tolerance_keeps_value_and_empty_package_clears(conn):
    item = make(conn, "Ei", tolerance="2,5", tolerance_unit="percent", unit_size_g=55, unit_label="Ei")
    run(conn, csv_bytes(f"{item['number']};Ei;;Standard;;;;;;;"), confirm=True)
    after = get_raw_material(conn, item["id"])
    assert (after["tolerance"], after["tolerance_unit"]) == (2.5, "percent")
    assert after["unit_size_g"] is None and after["unit_label"] is None


def test_missing_column_keeps_field(conn):
    item = make(conn, "Ei", display_name="Eier", unit_size_g=55, unit_label="Ei")
    run(conn, csv_bytes(f"{item['number']};Ei;7", header="Nummer;Name;Toleranz"), confirm=True)
    after = get_raw_material(conn, item["id"])
    assert (after["display_name"], after["unit_size_g"], after["tolerance"]) == ("Eier", 55, 7)


def test_empty_type_keeps_type(conn):
    item = make(conn, "Roggenmehl", type="flour")
    report = check(conn, csv_bytes(f"{item['number']};Roggenmehl;;;20;g;;;;;"))
    assert report["counts"]["unchanged"] == 1


def test_unit_change_without_value_is_error(conn):
    item = make(conn, "Hefe")
    report = check(conn, csv_bytes(f"{item['number']};Hefe;;;;%;;;;;"))
    assert not report["ok"]
    assert report["errors"][0]["column"] == "Toleranz"


def test_run_without_confirmation_saves_nothing(conn):
    item = make(conn, "Salz")
    data = csv_bytes(f"{item['number']};Salz;;;5;g;;;;;", ";Neu;;;1;g;;;;;")
    with pytest.raises(ConflictError) as exc:
        run(conn, data)
    assert exc.value.code == "overwrite_confirmation_required"
    assert exc.value.extra["report"]["counts"]["overwritten"] == 1
    assert exc.value.message == "1 Rohstoff wird überschrieben. Bitte bestätigen."   # B2 (0.5.11)
    assert get_raw_material(conn, item["id"])["tolerance"] == 20
    assert "Neu" not in names(conn)
    assert import_log(conn) == []


def test_only_new_rows_need_no_confirmation(conn):
    assert run(conn, csv_bytes(";Neu;;;1;g;;;;;"))["imported"]


def test_archive_and_restore_via_column(conn):
    a = make(conn, "A")
    b = make(conn, "B")
    archive_raw_material(conn, b["id"])
    c = make(conn, "C")
    report = run(conn, csv_bytes(f"{a['number']};A;;;20;g;;;;ja;", f"{b['number']};B;;;20;g;;;;nein;"),
                 confirm=True)
    assert report["counts"]["overwritten"] == 2
    assert get_raw_material(conn, a["id"])["archived"] is True
    assert get_raw_material(conn, b["id"])["archived"] is False
    assert get_raw_material(conn, c["id"])["archived"] is False       # nicht in der Datei: unverändert
    actions = [a for _, a, _ in import_log(conn)]
    assert sorted(actions) == ["archive", "restore"]


def test_restore_with_name_conflict_is_error(conn):
    old = make(conn, "Hefe")
    archive_raw_material(conn, old["id"])
    make(conn, "Hefe")
    report = check(conn, csv_bytes(f"{old['number']};Hefe;;;20;g;;;;nein;"))
    assert not report["ok"]
    assert "Wiederherstellen nicht möglich" in report["errors"][0]["message"]


def test_name_match_finds_single_archived(conn):
    old = make(conn, "Mohn")
    archive_raw_material(conn, old["id"])
    run(conn, csv_bytes(";Mohn;;;20;g;;;;nein;"), confirm=True)
    assert get_raw_material(conn, old["id"])["archived"] is False
    assert len(list_raw_materials(conn, include_archived=True)) == 1


def test_rename_and_archive_in_one_row_skips_name_check(conn):
    a = make(conn, "A")
    make(conn, "B")
    report = run(conn, csv_bytes(f"{a['number']};B;;;20;g;;;;ja;"), confirm=True)
    assert report["imported"]
    assert get_raw_material(conn, a["id"])["name"] == "B"


def test_type_change_of_used_raw_material_highlighted(conn):
    item = make(conn, "Spezialmehl")
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, item["id"])
    data = csv_bytes(f"{item['number']};Spezialmehl;;Mehl;20;g;;;;;")
    report = check(conn, data)
    assert report["changes"][0]["type_change_recipes"] == 1
    assert any("Typwechsel" in h["message"] for h in report["hints"])
    run(conn, data, confirm=True)
    assert get_raw_material(conn, item["id"])["type"] == "flour"


def test_number_of_used_raw_material_never_changes(conn):
    item = make(conn, "Hefe")
    run(conn, csv_bytes(f"{item['number']};Hefe neu;;;20;g;;;BÄKO;;2020-01-01"), confirm=True)
    after = get_raw_material(conn, item["id"])
    assert (after["number"], after["source"], after["name"]) == (item["number"], "own", "Hefe neu")


# -- Export → Re-Import ------------------------------------------------------------

def test_export_reimport_is_unchanged(conn):
    make(conn, "Weizenmehl 550", type="flour", tolerance="2,5", tolerance_unit="percent")
    make(conn, "Ei", display_name="Eier", unit_size_g=55, unit_label="Ei", tolerance=0)
    gone = make(conn, "Alt")
    archive_raw_material(conn, gone["id"])
    exported = build_csv(list_raw_materials(conn, include_archived=True))
    report = check(conn, exported)
    assert report["ok"]
    assert report["counts"] == {"rows": 3, "new": 0, "overwritten": 0, "unchanged": 3, "errors": 0}
    assert not report["needs_confirmation"]


def test_export_edit_reimport(conn):
    item = make(conn, "Zucker")
    exported = build_csv(list_raw_materials(conn)).decode("utf-8-sig")
    edited = exported.replace(";Zucker;;Standard;20;g;", ";Zucker;;Standard;15;g;").encode("utf-8-sig")
    run(conn, edited, confirm=True)
    assert get_raw_material(conn, item["id"])["tolerance"] == 15


# -- Fehler, alles oder nichts ----------------------------------------------------------

def test_check_changes_nothing(conn):
    item = make(conn, "Salz")
    check(conn, csv_bytes(f"{item['number']};Salz neu;;;1;g;;;;;", ";Neu;;;1;g;;;;;"))
    assert [r["name"] for r in list_raw_materials(conn)] == ["Salz"]
    assert import_log(conn) == []


def test_all_or_nothing_with_all_errors_listed(conn):
    data = csv_bytes(";Gut;;;1;g;;;;;", ";=Formel;;;1;g;;;;;", ";Schlecht;;Brot;1;g;;;;;",
                     ";Ei;;;1;g;55;;;;")
    report = check(conn, data)
    lines = {(e["line"], e["column"]) for e in report["errors"]}
    assert lines == {(3, "Name"), (4, "Typ"), (5, "Gebindebezeichnung")}
    with pytest.raises(ValidationError) as exc:
        run(conn, data, confirm=True)
    assert exc.value.code == "import_failed"
    assert list_raw_materials(conn) == []


def test_duplicates_within_file(conn):
    report = check(conn, csv_bytes("5;Hefe;;;1;g;;;;;", "5;Salz;;;1;g;;;;;", ";hefe;;;1;g;;;;;"))
    messages = [e["message"] for e in report["errors"]]
    assert any("Nummer 5 steht mehrfach" in m for m in messages)
    assert any("mehrfach in der Datei" in m and "hefe" in m for m in messages)


def test_new_number_with_existing_name_is_error(conn):
    make(conn, "Hefe")
    report = check(conn, csv_bytes("99;Hefe;;;1;g;;;;;"))
    assert report["errors"][0]["column"] == "Name"


def test_b2_in_import_display_name(conn):
    report = check(conn, csv_bytes(";Hefe;@Hefe;;1;g;;;;;"))
    assert report["errors"][0]["column"] == "Kurzname"


@pytest.mark.parametrize("value", ["vielleicht", "x"])
def test_invalid_archived_value(conn, value):
    report = check(conn, csv_bytes(f";Hefe;;;1;g;;;;{value};"))
    assert report["errors"][0]["column"] == "archiviert"


def test_invalid_number(conn):
    report = check(conn, csv_bytes("abc;Hefe;;;1;g;;;;;"))
    assert report["errors"][0]["column"] == "Nummer"


# -- Datei --------------------------------------------------------------------------

def test_empty_rows_skipped_and_unknown_column_hint(conn):
    report = check(conn, csv_bytes(";Hefe;;;1;g;;;;;;x", ";;;;;;;;;;;", header=HEADER + ";Bemerkung"))
    assert report["counts"]["rows"] == 1
    assert any("Bemerkung" in h["message"] for h in report["hints"])


def test_header_without_name_refused(conn):
    with pytest.raises(ValidationError, match="Name"):
        check(conn, b"Nummer;Toleranz\r\n1;5\r\n")


def test_duplicate_header_refused():
    with pytest.raises(ValidationError, match="doppelt"):
        parse_csv(b"Name;Name\r\nA;B\r\n")


def test_empty_file_refused(conn):
    with pytest.raises(ValidationError):
        check(conn, b"   ")


def test_binary_file_refused(conn):
    with pytest.raises(ValidationError):
        check(conn, b"PK\x03\x04\x00\x00binary")


def test_file_too_large(conn):
    with pytest.raises(PayloadTooLargeError):
        check(conn, b"Name\r\n" + b"x" * (5 * 1024 * 1024 + 1))


def test_too_many_rows(conn):
    data = ("Name;Toleranz\r\n" + "".join(f"R{i};1\r\n" for i in range(5001))).encode()
    with pytest.raises(ValidationError, match="5000"):
        check(conn, data)


def test_invalid_mode(conn):
    with pytest.raises(ValidationError):
        import_raw_materials_csv(conn, csv_bytes(";Hefe;;;1;g;;;;;"), mode="go")
