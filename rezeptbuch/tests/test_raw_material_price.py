"""Tests: Preis je kg am Rohstoff (Modul 03 Ergänzung VC03-a, docs/rohstoffe.md Abschnitt 15).

Regeln R03-13 bis R03-17, Konzeptfragen K03-5 bis K03-8; Export (15.5) und CSV-Import (15.6).
"""

import json
import time

import pytest

from app.errors import ValidationError
from app.imports import import_raw_materials_csv
from app.raw_materials import (
    archive_raw_material,
    build_csv,
    create_raw_material,
    get_raw_material,
    list_raw_materials,
    restore_raw_material,
    update_raw_material,
)
from app.raw_materials.models import euro_text, parse_price

HEADER = ("Nummer;Name;Kurzname;Typ;Toleranz;Toleranzeinheit;Gebindegröße g;Gebindebezeichnung;"
          "Herkunft;archiviert;geändert am")


def make(conn, name="Weizenmehl 550", **kw):
    return create_raw_material(conn, {"name": name, "tolerance": 20, **kw})


def price_log(conn, rm_id):
    rows = conn.execute("SELECT old_values, new_values FROM change_log WHERE entity = 'raw_material' "
                        "AND entity_id = ? AND action = 'update' ORDER BY id", (rm_id,)).fetchall()
    return [(json.loads(r[0]), json.loads(r[1])) for r in rows]


# -- R03-13: Eingabe ------------------------------------------------------------------------------

@pytest.mark.parametrize("text, cents", [
    ("2,35", 235), ("2.35", 235), ("1.234,50", 123450), ("2,35 €", 235), ("2,35€", 235), (" 2,35 ", 235),
    ("0", 0), ("0,00", 0), ("9 999,99", 999999), ("9999,99", 999999), ("12", 1200), ("12,5", 1250),
    (2.35, 235), (3, 300),
])
def test_valid_prices(text, cents):
    assert parse_price(text) == (cents, None)


@pytest.mark.parametrize("text", [None, "", "  ", "€"])
def test_empty_price_means_none(text):
    assert parse_price(text) == (None, None)


@pytest.mark.parametrize("text", ["-1", "-2,35", "10000", "10.000,00", "abc", "²", "2,3,5", "1,234.50", True, "1e5"])
def test_invalid_prices(text):
    with pytest.raises(ValidationError) as err:
        parse_price(text)
    assert err.value.field == "price_per_kg"
    assert err.value.code == "invalid_price"


def test_negative_message():
    with pytest.raises(ValidationError, match="nicht negativ"):
        parse_price("-1")
    with pytest.raises(ValidationError, match="9 999,99"):
        parse_price("10000")


# -- K03-8: Runden mit Hinweis ----------------------------------------------------------------------

@pytest.mark.parametrize("text, cents, hint", [
    ("2,355", 236, "2,355 → 2,36 €"),
    ("2,354", 235, "2,354 → 2,35 €"),
    ("2.345", 235, "2,345 → 2,35 €"),        # Punkt ohne Komma = Dezimalpunkt; kaufmännisch gerundet
    ("1.234", 123, "1,234 → 1,23 €"),
    ("9 999,994", 999999, "9999,994 → 9999,99 €"),
])
def test_rounding_with_hint(text, cents, hint):
    value, message = parse_price(text)
    assert value == cents
    assert message.startswith("Preis auf 2 Nachkommastellen gerundet")
    assert hint in message


def test_limit_checked_after_rounding():
    with pytest.raises(ValidationError, match="9 999,99"):
        parse_price("9999,995")


def test_trailing_zeros_are_not_rounding():
    assert parse_price("2,3500") == (235, None)


def test_euro_text():
    assert euro_text(0) == "0,00"
    assert euro_text(5) == "0,05"
    assert euro_text(123450) == "1234,50"


# -- Service: Anlegen, Ändern, Datum (R03-14) --------------------------------------------------------

def test_create_without_price(conn):
    rm = make(conn)
    assert rm["price_cents_per_kg"] is None and rm["price_changed_at"] is None
    assert "warnings" not in rm


def test_create_with_price_sets_date(conn):
    rm = make(conn, price_per_kg="2,35")
    assert rm["price_cents_per_kg"] == 235
    assert rm["price_changed_at"]


def test_create_with_rounded_price_has_warning(conn):
    rm = make(conn, price_per_kg="2,355")
    assert rm["price_cents_per_kg"] == 236
    assert rm["warnings"] == [{"field": "price_per_kg", "code": "price_rounded",
                               "detail": "Preis auf 2 Nachkommastellen gerundet: 2,355 → 2,36 €"}]


def test_invalid_price_on_create_saves_nothing(conn):
    with pytest.raises(ValidationError):
        make(conn, price_per_kg="-1")
    assert list_raw_materials(conn) == []


def test_zero_differs_from_empty(conn):
    rm = make(conn, "Wasser", price_per_kg="0")
    assert rm["price_cents_per_kg"] == 0 and rm["price_changed_at"]


def _age_price_date(conn, rm_id):
    conn.execute("UPDATE raw_material SET price_changed_at = '2026-01-01T00:00:00Z' WHERE id = ?", (rm_id,))


def test_date_on_first_price_change_and_clear(conn):
    rm = make(conn)
    first = update_raw_material(conn, rm["id"], {"price_per_kg": "2,35"})
    assert first["price_cents_per_kg"] == 235 and first["price_changed_at"]
    _age_price_date(conn, rm["id"])
    changed = update_raw_material(conn, rm["id"], {"price_per_kg": "2,40"})
    assert changed["price_cents_per_kg"] == 240 and changed["price_changed_at"] != "2026-01-01T00:00:00Z"
    _age_price_date(conn, rm["id"])
    cleared = update_raw_material(conn, rm["id"], {"price_per_kg": None})
    assert cleared["price_cents_per_kg"] is None and cleared["price_changed_at"] != "2026-01-01T00:00:00Z"
    _age_price_date(conn, rm["id"])
    cleared_text = update_raw_material(conn, rm["id"], {"price_per_kg": "2,00"})
    _age_price_date(conn, rm["id"])
    cleared_text = update_raw_material(conn, rm["id"], {"price_per_kg": ""})
    assert cleared_text["price_cents_per_kg"] is None
    assert cleared_text["price_changed_at"] != "2026-01-01T00:00:00Z"


def test_date_stays_when_price_unchanged(conn):
    rm = make(conn, price_per_kg="2,35")
    _age_price_date(conn, rm["id"])
    same = update_raw_material(conn, rm["id"], {"price_per_kg": "2,35"})
    assert same["price_changed_at"] == "2026-01-01T00:00:00Z"
    rounded_same = update_raw_material(conn, rm["id"], {"price_per_kg": "2,349"})   # → 2,35
    assert rounded_same["price_cents_per_kg"] == 235
    assert rounded_same["price_changed_at"] == "2026-01-01T00:00:00Z"
    assert rounded_same["warnings"][0]["code"] == "price_rounded"
    other = update_raw_material(conn, rm["id"], {"display_name": "Mehl"})
    assert other["price_changed_at"] == "2026-01-01T00:00:00Z"
    missing = update_raw_material(conn, rm["id"], {"tolerance": 30})               # Feld fehlt = unverändert
    assert missing["price_cents_per_kg"] == 235


def test_price_date_cannot_be_set_by_hand(conn):
    rm = make(conn, price_per_kg="2,35")
    _age_price_date(conn, rm["id"])
    item = update_raw_material(conn, rm["id"], {"price_changed_at": "2030-01-01T00:00:00Z"})
    assert item["price_changed_at"] == "2026-01-01T00:00:00Z"


def test_change_log_has_old_and_new_price(conn):
    rm = make(conn, price_per_kg="2,35")
    update_raw_material(conn, rm["id"], {"price_per_kg": "2,40"})
    old, new = price_log(conn, rm["id"])[-1]
    assert old == {"price_cents_per_kg": 235} and new == {"price_cents_per_kg": 240}
    created = conn.execute("SELECT new_values FROM change_log WHERE action = 'create'").fetchone()[0]
    assert json.loads(created)["price_cents_per_kg"] == 235


def test_archive_and_restore_keep_price(conn):
    rm = make(conn, price_per_kg="2,35")
    assert archive_raw_material(conn, rm["id"])["price_cents_per_kg"] == 235
    assert restore_raw_material(conn, rm["id"])["price_cents_per_kg"] == 235


def test_list_and_get_include_price(conn):
    rm = make(conn, price_per_kg="1,10")
    assert list_raw_materials(conn)[0]["price_cents_per_kg"] == 110
    assert get_raw_material(conn, rm["id"])["price_cents_per_kg"] == 110


# -- Export (15.5) -------------------------------------------------------------------------------------

def test_export_has_price_columns_at_end(conn):
    make(conn, "Mehl", number=1, price_per_kg="2,35")
    make(conn, "Salz", number=2)
    make(conn, "Wasser", number=3, price_per_kg="0")
    lines = build_csv(list_raw_materials(conn)).decode("utf-8-sig").split("\r\n")
    header = lines[0].split(";")
    assert header[-2:] == ["Preis je kg €", "Preis geändert am"]
    assert header[:11] == HEADER.split(";")
    mehl, salz, wasser = (line.split(";") for line in lines[1:4])
    assert mehl[11] == "2,35" and mehl[12]
    assert salz[11:] == ["", ""]
    assert wasser[11] == "0,00"


# -- CSV-Import (15.6) ---------------------------------------------------------------------------------

def csv_bytes(*lines, header=HEADER):
    return ("\r\n".join([header, *lines]) + "\r\n").encode("utf-8")


PRICE_HEADER = HEADER + ";Preis je kg €;Preis geändert am"


def run(conn, data, confirm=True):
    return import_raw_materials_csv(conn, data, mode="run", confirm_overwrite=confirm)


def test_import_new_with_price(conn):
    report = run(conn, csv_bytes("1;Mehl;;Mehl;20;g;;;eigen;nein;;2,35;", header=PRICE_HEADER))
    assert report["imported"]
    item = list_raw_materials(conn)[0]
    assert item["price_cents_per_kg"] == 235 and item["price_changed_at"]


def test_old_file_without_price_column_keeps_price(conn):
    make(conn, "Mehl", number=1, price_per_kg="2,35")
    run(conn, csv_bytes("1;Mehl;Weizen;Mehl;20;g;;;eigen;nein;"))
    assert list_raw_materials(conn)[0]["price_cents_per_kg"] == 235


def test_empty_cell_deletes_price(conn):
    rm = make(conn, "Mehl", number=1, price_per_kg="2,35")
    report = run(conn, csv_bytes("1;Mehl;;Standard;20;g;;;eigen;nein;;;", header=PRICE_HEADER))
    assert get_raw_material(conn, rm["id"])["price_cents_per_kg"] is None
    assert report["changes"][0]["fields"] == [{"field": "Preis je kg", "old": "2,35 €", "new": "(leer)"}]


@pytest.mark.parametrize("label", ["Preis je kg", "PREIS €/KG", "preis/kg"])
def test_header_variants(conn, label):
    header = HEADER + ";" + label
    run(conn, csv_bytes("1;Mehl;;Standard;20;g;;;eigen;nein;;1,5", header=header))
    assert list_raw_materials(conn)[0]["price_cents_per_kg"] == 150


def test_import_rounds_with_hint_and_line(conn):
    report = run(conn, csv_bytes("1;Mehl;;Standard;20;g;;;eigen;nein;;2,355;", header=PRICE_HEADER))
    assert report["imported"]
    assert list_raw_materials(conn)[0]["price_cents_per_kg"] == 236
    hint = next(h for h in report["hints"] if "gerundet" in h["message"])
    assert hint["line"] == 2 and "2,355 → 2,36" in hint["message"]


@pytest.mark.parametrize("bad", ["-1", "abc", "10000"])
def test_import_invalid_price_is_error_with_column(conn, bad):
    report = import_raw_materials_csv(conn, csv_bytes(f"1;Mehl;;Standard;20;g;;;eigen;nein;;{bad};",
                                                      header=PRICE_HEADER), mode="check")
    assert not report["ok"]
    error = report["errors"][0]
    assert error["line"] == 2 and error["column"] == "Preis je kg €"
    assert list_raw_materials(conn) == []


def test_changed_price_shows_old_new_and_needs_confirmation(conn):
    make(conn, "Mehl", number=1, price_per_kg="2,35")
    data = csv_bytes("1;Mehl;;Standard;20;g;;;eigen;nein;;2,40;", header=PRICE_HEADER)
    report = import_raw_materials_csv(conn, data, mode="check")
    assert report["changes"][0]["fields"] == [{"field": "Preis je kg", "old": "2,35 €", "new": "2,40 €"}]
    with pytest.raises(Exception):
        run(conn, data, confirm=False)
    run(conn, data)
    assert list_raw_materials(conn)[0]["price_cents_per_kg"] == 240


def test_export_reimport_unchanged_keeps_date(conn):
    make(conn, "Mehl", number=1, type="flour", price_per_kg="2,35")
    make(conn, "Salz", number=2)
    conn.execute("UPDATE raw_material SET price_changed_at = '2026-01-01T00:00:00Z' WHERE number = 1")
    data = build_csv(list_raw_materials(conn, include_archived=True))
    report = run(conn, data, confirm=False)
    assert report["imported"] and report["counts"]["unchanged"] == 2 and report["changes"] == []
    assert list_raw_materials(conn)[0]["price_changed_at"] == "2026-01-01T00:00:00Z"
    assert not any("wird nicht ausgewertet" in h["message"] for h in report["hints"])


def test_price_column_not_read_from_template_headers():
    """K03-7: Die Importvorlage .xlsx kennt die Preisspalte nicht (nur CSV)."""
    from app.imports.raw_materials_csv import CSV_HEADERS, HEADERS
    assert "preis je kg €" not in HEADERS
    assert CSV_HEADERS["preis je kg €"] == "price_per_kg"
