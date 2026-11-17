"""Tests: Migration 0003 (Bearbeitungsstand, Nummernsperre, Index) – Modul 05."""

import shutil
import sqlite3

import pytest

from app.db import MIGRATIONS_DIR, init_database
from app.db.migrate import discover

from conftest import add_item, add_order, add_raw_material, add_recipe


def test_revision_column_defaults_to_zero(conn):
    recipe, _ = add_recipe(conn, 10)
    assert conn.execute("SELECT revision FROM recipe WHERE id = ?", (recipe,)).fetchone()[0] == 0
    conn.execute("UPDATE recipe SET revision = revision + 1 WHERE id = ?", (recipe,))
    assert conn.execute("SELECT revision FROM recipe WHERE id = ?", (recipe,)).fetchone()[0] == 1


def test_revision_must_not_be_negative(conn):
    recipe, _ = add_recipe(conn, 10)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE recipe SET revision = -1 WHERE id = ?", (recipe,))


def test_version_index_exists(conn):
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(recipe_version)")}
    assert "idx_recipe_version_recipe" in indexes


def test_recipe_number_can_change_while_unused(conn):
    recipe, version = add_recipe(conn, 10)
    rm = add_raw_material(conn, 1)
    add_item(conn, version, 1, rm)          # eigene Zeilen sperren die Nummer nicht
    conn.execute("UPDATE recipe SET number = 11 WHERE id = ?", (recipe,))
    assert conn.execute("SELECT number FROM recipe WHERE id = ?", (recipe,)).fetchone()[0] == 11


def test_recipe_number_locked_when_used_in_order(conn):
    recipe, version = add_recipe(conn, 10)
    add_order(conn, recipe, version_id=version)
    with pytest.raises(sqlite3.IntegrityError, match="Rezeptnummer"):
        conn.execute("UPDATE recipe SET number = 11 WHERE id = ?", (recipe,))


def test_recipe_number_locked_when_used_as_sub_recipe(conn):
    sub, _ = add_recipe(conn, 10, name="Vorteig")
    _, main_version = add_recipe(conn, 20, name="Hauptteig")
    add_item(conn, main_version, 1, sub_recipe_id=sub, amount_g=500)
    with pytest.raises(sqlite3.IntegrityError, match="Rezeptnummer"):
        conn.execute("UPDATE recipe SET number = 11 WHERE id = ?", (sub,))
    # andere Felder und dieselbe Nummer bleiben änderbar
    conn.execute("UPDATE recipe SET number = number, locked = 1 WHERE id = ?", (sub,))


def test_migration_on_database_with_recipes(tmp_path):
    """Eine Datenbank im Stand 0002 mit Rezepten wird ohne Verlust auf 0003 gebracht (mit Sicherung)."""
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    for name in ("0001_initial.sql", "0002_raw_material.sql"):
        shutil.copy(MIGRATIONS_DIR / name, old_dir / name)
    db = tmp_path / "rezeptbuch.db"

    old = init_database(db, migrations_dir=old_dir)
    add_recipe(old, 10, name="Weizenbrot")
    old.close()

    conn = init_database(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(discover())
    row = conn.execute("SELECT number, revision FROM recipe").fetchone()
    assert tuple(row) == (10, 0)
    assert len(list((tmp_path / "backups").glob("pre_migration_0002_*.db"))) == 1
    conn.close()
