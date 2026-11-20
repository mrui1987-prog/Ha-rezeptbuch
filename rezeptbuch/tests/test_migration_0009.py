"""Tests: Migration 0009 (Händler, Bezugsquellen, Pass-Tabellen; Modul 04, docs/kennzeichnungspass-import.md 3)."""

import shutil
import sqlite3

import pytest

from app.db import MIGRATIONS_DIR, init_database

from conftest import add_item, add_order, add_raw_material, add_recipe


def columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def add_dealer(conn, name="BÄKO"):
    return conn.execute("INSERT INTO dealer (name) VALUES (?)", (name,)).lastrowid


def test_raw_material_columns(conn):
    assert {"datenlink_id", "price_cents_per_kg", "stock_g", "display_name"} <= columns(conn, "raw_material")
    assert {"grams_per_unit", "unit_code", "commodity_group", "is_active"} <= columns(conn, "raw_material_source")


def test_source_values(conn):
    rm = add_raw_material(conn, 1)
    assert conn.execute("SELECT source FROM raw_material WHERE id = ?", (rm,)).fetchone()[0] == "own"
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE raw_material SET source = 'baeko' WHERE id = ?", (rm,))
    # datenlink nur mit ID, ID nur mit datenlink
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE raw_material SET source = 'datenlink' WHERE id = ?", (rm,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE raw_material SET datenlink_id = 'DL-1' WHERE id = ?", (rm,))
    conn.execute("UPDATE raw_material SET source = 'datenlink', datenlink_id = 'DL-1' WHERE id = ?", (rm,))


def test_datenlink_id_unique_among_active(conn):
    a = add_raw_material(conn, 1, "A")
    b = add_raw_material(conn, 2, "B")
    conn.execute("UPDATE raw_material SET source = 'datenlink', datenlink_id = 'DL-X' WHERE id = ?", (a,))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("UPDATE raw_material SET source = 'datenlink', datenlink_id = 'DL-X' WHERE id = ?", (b,))
    conn.execute("UPDATE raw_material SET archived = 1 WHERE id = ?", (a,))
    conn.execute("UPDATE raw_material SET source = 'datenlink', datenlink_id = 'DL-X' WHERE id = ?", (b,))


def test_number_lock_trigger_still_works(conn):
    rm = add_raw_material(conn, 1)
    recipe, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm, 1000)
    with pytest.raises(sqlite3.DatabaseError, match="Rohstoffnummer"):
        conn.execute("UPDATE raw_material SET number = 5 WHERE id = ?", (rm,))


def test_dealer_name_unique_case_insensitive(conn):
    add_dealer(conn, "Bäko")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        add_dealer(conn, " bäko ".upper().replace("Ä", "ä"))


def test_source_rules(conn):
    rm = add_raw_material(conn, 1)
    d1, d2 = add_dealer(conn, "BÄKO"), add_dealer(conn, "Metro")
    conn.execute("INSERT INTO raw_material_source (raw_material_id, dealer_id, is_active) VALUES (?, ?, 1)", (rm, d1))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO raw_material_source (raw_material_id, dealer_id) VALUES (?, ?)", (rm, d1))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO raw_material_source (raw_material_id, dealer_id, is_active) VALUES (?, ?, 1)",
                     (rm, d2))
    conn.execute("INSERT INTO raw_material_source (raw_material_id, dealer_id, grams_per_unit, unit_code) "
                 "VALUES (?, ?, 1030, 'L')", (rm, d2))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE raw_material_source SET grams_per_unit = 0 WHERE dealer_id = ?", (d2,))
    # Händler mit Bezugsquelle nicht löschbar
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("DELETE FROM dealer WHERE id = ?", (d1,))


def test_allergen_list(conn):
    assert conn.execute("SELECT COUNT(*) FROM allergen").fetchone()[0] == 26
    assert conn.execute("SELECT COUNT(*) FROM allergen WHERE parent_code = 'gluten'").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM allergen WHERE parent_code = 'schalenfruechte'").fetchone()[0] == 8


def test_existing_rows_survive_migration(tmp_path):
    """Datenbank auf Stand 0008 mit Rezept, Auftrag, Charge, Preis, Bestand → 0009: alles bleibt."""
    old_dir = tmp_path / "migrations"
    old_dir.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 8:
            shutil.copy(path, old_dir / path.name)
    db = tmp_path / "x.db"
    conn = init_database(db, migrations_dir=old_dir)
    rm = add_raw_material(conn, 7, "Roggenmehl 1150")
    conn.execute("UPDATE raw_material SET display_name = 'Roggen', price_cents_per_kg = 59, "
                 "price_changed_at = '2026-11-18T10:00:00Z', stock_g = 25000, stock_alert_g = 5000 WHERE id = ?",
                 (rm,))
    recipe, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm, 1000)
    order = add_order(conn, recipe, version_id=version, status="in_progress")
    batch = conn.execute("INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status) "
                         "VALUES ('T-1', ?, 1, ?, 'running')", (order, version)).lastrowid
    conn.execute(
        "INSERT INTO batch_item (batch_id, position, item_type, raw_material_id, raw_material_number, "
        "raw_material_name, target_g, tolerance_g, rest_target_g) VALUES (?, 1, 'raw_material', ?, 7, 'R', "
        "1000, 20, 1000)", (batch, rm))
    conn.execute("INSERT INTO stock_movement (raw_material_id, kind, delta_g, stock_after_g) "
                 "VALUES (?, 'receipt', 25000, 25000)", (rm,))
    before = dict(conn.execute("SELECT * FROM raw_material WHERE id = ?", (rm,)).fetchone())
    conn.close()

    conn = init_database(db, backup_dir=tmp_path / "backups")
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 9
    after = dict(conn.execute("SELECT * FROM raw_material WHERE id = ?", (rm,)).fetchone())
    assert after.pop("datenlink_id") is None
    assert after == before
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT COUNT(*) FROM stock_movement").fetchone()[0] == 1
    # Fremdschlüssel zeigen weiter auf die neue Tabelle
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("DELETE FROM raw_material WHERE id = ?", (rm,))
    with pytest.raises(sqlite3.DatabaseError, match="Rohstoffnummer"):
        conn.execute("UPDATE raw_material SET number = 99 WHERE id = ?", (rm,))
    conn.close()
