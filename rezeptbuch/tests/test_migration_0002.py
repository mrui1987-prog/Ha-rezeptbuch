"""Tests: Migration 0002 (Kurzname, Nummernsperre, Index) – Modul 03."""

import shutil
import sqlite3

import pytest

from app.db import MIGRATIONS_DIR, init_database

from conftest import add_item, add_order, add_raw_material, add_recipe


def columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_display_name_column_and_index_exist(conn):
    assert "display_name" in columns(conn, "raw_material")
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(raw_material)")}
    assert "idx_raw_material_name" in indexes


def test_display_name_may_be_empty_but_not_blank(conn):
    rm = add_raw_material(conn, 1)
    conn.execute("UPDATE raw_material SET display_name = NULL WHERE id = ?", (rm,))
    conn.execute("UPDATE raw_material SET display_name = 'Margarine' WHERE id = ?", (rm,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE raw_material SET display_name = '   ' WHERE id = ?", (rm,))


def test_display_name_is_not_unique(conn):
    for number in (1, 2, 3):
        rm = add_raw_material(conn, number, name=f"Margarine Sorte {number}")
        conn.execute("UPDATE raw_material SET display_name = 'Margarine' WHERE id = ?", (rm,))
    assert conn.execute("SELECT count(*) FROM raw_material WHERE display_name = 'Margarine'").fetchone()[0] == 3


def test_number_can_change_while_unused(conn):
    rm = add_raw_material(conn, 1)
    conn.execute("UPDATE raw_material SET number = 7 WHERE id = ?", (rm,))
    assert conn.execute("SELECT number FROM raw_material WHERE id = ?", (rm,)).fetchone()[0] == 7


def test_number_locked_when_used_in_recipe(conn):
    rm = add_raw_material(conn, 1)
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm)
    with pytest.raises(sqlite3.IntegrityError, match="Rohstoffnummer"):
        conn.execute("UPDATE raw_material SET number = 7 WHERE id = ?", (rm,))


def test_number_locked_when_used_as_basis_of_order(conn):
    rm = add_raw_material(conn, 1)
    recipe, version = add_recipe(conn, 10)
    add_order(conn, recipe, version_id=version, basis_type="raw_material", basis_value=7500,
              basis_raw_material_id=rm)
    with pytest.raises(sqlite3.IntegrityError, match="Rohstoffnummer"):
        conn.execute("UPDATE raw_material SET number = 7 WHERE id = ?", (rm,))


def test_other_fields_can_change_when_used(conn):
    rm = add_raw_material(conn, 1)
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm)
    conn.execute("UPDATE raw_material SET name = 'Neu', display_name = 'N' WHERE id = ?", (rm,))
    conn.execute("UPDATE raw_material SET number = number WHERE id = ?", (rm,))  # gleiche Nummer ist erlaubt


def test_migration_on_database_with_data(tmp_path):
    """Eine Datenbank im Stand 0001 mit Daten wird ohne Verlust auf den neuesten Stand gebracht (mit Sicherung)."""
    only_first = tmp_path / "only_first"
    only_first.mkdir()
    shutil.copy(MIGRATIONS_DIR / "0001_initial.sql", only_first / "0001_initial.sql")
    db = tmp_path / "rezeptbuch.db"

    old = init_database(db, migrations_dir=only_first)
    add_raw_material(old, 1, name="Weizenmehl 550", type_="flour")
    add_raw_material(old, 2, name="Ei", unit_size_g=55, unit_label="Ei")
    old.close()

    conn = init_database(db)
    rows = conn.execute("SELECT number, name, display_name FROM raw_material ORDER BY number").fetchall()
    assert [tuple(r) for r in rows] == [(1, "Weizenmehl 550", None), (2, "Ei", None)]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
    backups = list((tmp_path / "backups").glob("pre_migration_0001_*.db"))
    assert len(backups) == 1
    conn.close()
