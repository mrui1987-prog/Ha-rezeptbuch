"""Tests: Migration 0005 (Leitrohstoff je Zeile, Trigger B2) – Modul 06, docs/berechnung.md Abschnitt 3."""

import shutil
import sqlite3

import pytest

from app.db import MIGRATIONS_DIR, init_database
from app.db.migrate import discover

from conftest import add_item, add_order, add_raw_material, add_recipe, add_version


def columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_column_exists_and_is_empty_by_default(conn):
    assert "basis_item_position" in columns(conn, "production_order")
    recipe, _ = add_recipe(conn, 10)
    order = add_order(conn, recipe)
    assert conn.execute("SELECT basis_item_position FROM production_order WHERE id = ?",
                        (order,)).fetchone()[0] is None


def test_item_position_only_with_leading_material(conn):
    water = add_raw_material(conn, 1, name="Wasser")
    recipe, version = add_recipe(conn, 10)
    add_item(conn, version, 1, water, amount_g=500)
    add_order(conn, recipe, basis_type="raw_material", basis_value=300, basis_raw_material_id=water,
              basis_item_position=1)
    with pytest.raises(sqlite3.IntegrityError, match="nur beim Leitrohstoff"):
        add_order(conn, recipe, basis_type="total", basis_value=300, basis_item_position=1)
    order = add_order(conn, recipe, basis_type="total", basis_value=300)
    with pytest.raises(sqlite3.IntegrityError, match="nur beim Leitrohstoff"):
        conn.execute("UPDATE production_order SET basis_item_position = 1 WHERE id = ?", (order,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_order(conn, recipe, basis_type="raw_material", basis_value=300, basis_raw_material_id=water,
                  basis_item_position=0)


def _batch(conn, order, version, no="T-1"):
    return conn.execute(
        "INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status) VALUES (?, ?, 1, ?, 'running')",
        (no, order, version)).lastrowid


def _batch_item(conn, batch, recipe_item, rm, position=1):
    return conn.execute(
        "INSERT INTO batch_item (batch_id, position, recipe_item_id, item_type, raw_material_id, raw_material_number, "
        "raw_material_name, target_g, tolerance_g, units_target, rest_target_g) "
        "VALUES (?, ?, ?, 'raw_material', ?, 1, 'Mehl', 500, 10, 0, 500)",
        (batch, position, recipe_item, rm)).lastrowid


def test_batch_item_must_use_version_of_batch(conn):
    """Befund B2: Chargenzeile mit Rezeptzeile einer anderen Version wird abgelehnt."""
    rm = add_raw_material(conn, 1)
    recipe, v1 = add_recipe(conn, 10)
    item_v1 = add_item(conn, v1, 1, rm, amount_g=500)
    v2 = add_version(conn, recipe, 2)
    item_v2 = add_item(conn, v2, 1, rm, amount_g=600)
    order = add_order(conn, recipe, version_id=v1, status="in_progress")
    batch = _batch(conn, order, v1)

    with pytest.raises(sqlite3.IntegrityError, match="Version der Charge"):
        _batch_item(conn, batch, item_v2, rm)
    item = _batch_item(conn, batch, item_v1, rm)
    with pytest.raises(sqlite3.IntegrityError, match="Version der Charge"):
        conn.execute("UPDATE batch_item SET recipe_item_id = ? WHERE id = ?", (item_v2, item))
    # ohne Bezug auf eine Rezeptzeile (z. B. alte Daten) bleibt es erlaubt
    _batch_item(conn, batch, None, rm, position=2)
    conn.execute("UPDATE batch_item SET actual_g = 498 WHERE id = ?", (item,))


def test_migration_on_database_with_data(tmp_path):
    """Eine Datenbank im Stand 0004 mit Auftrag wird ohne Verlust auf 0005 gebracht (mit Sicherung)."""
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    for m in discover():
        if m.version <= 4:
            shutil.copy(m.path, old_dir / m.path.name)
    db = tmp_path / "rezeptbuch.db"

    old = init_database(db, migrations_dir=old_dir)
    rm = add_raw_material(old, 1, name="Wasser")
    recipe, version = add_recipe(old, 10)
    add_item(old, version, 1, rm, amount_g=500)
    add_order(old, recipe, basis_type="raw_material", basis_value=300, basis_raw_material_id=rm)
    old.close()

    conn = init_database(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(discover())
    row = conn.execute("SELECT basis_type, basis_value, basis_item_position FROM production_order").fetchone()
    assert tuple(row) == ("raw_material", 300, None)
    assert len(list((tmp_path / "backups").glob("pre_migration_0004_*.db"))) == 1
    conn.close()


def test_shipped_file_name():
    assert (MIGRATIONS_DIR / "0005_batch_item_version.sql").exists()
