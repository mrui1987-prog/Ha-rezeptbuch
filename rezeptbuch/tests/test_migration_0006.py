"""Tests: Migration 0006 (Kombinieren, Faktor, Obergrenze, Teige; Preis je kg).

Modul 06 Teil C3, docs/berechnung.md Abschnitt 17.9 (K06-11); Modul 03 VC03-a, docs/rohstoffe.md 15.2.
"""

import shutil
import sqlite3

import pytest

from app.db import MIGRATIONS_DIR, init_database
from app.db.migrate import discover

from conftest import add_item, add_order, add_raw_material, add_recipe


def columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _batch_size(conn, recipe, label="Großer Teig", value=20000, is_limit=0):
    return conn.execute(
        "INSERT INTO recipe_batch_size (recipe_id, label, kind, value, is_limit) VALUES (?, ?, 'weight', ?, ?)",
        (recipe, label, value, is_limit)).lastrowid


# --- Rohstoff: Preis ---------------------------------------------------------

def test_price_columns_empty_by_default_and_checked(conn):
    rm = add_raw_material(conn, 1)
    row = conn.execute("SELECT price_cents_per_kg, price_changed_at FROM raw_material WHERE id = ?",
                       (rm,)).fetchone()
    assert tuple(row) == (None, None)
    conn.execute("UPDATE raw_material SET price_cents_per_kg = 0 WHERE id = ?", (rm,))
    conn.execute("UPDATE raw_material SET price_cents_per_kg = 999999 WHERE id = ?", (rm,))
    for bad in (-1, 1_000_000):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("UPDATE raw_material SET price_cents_per_kg = ? WHERE id = ?", (bad, rm))


# --- Chargengröße als Obergrenze ---------------------------------------------

def test_at_most_one_limit_per_recipe(conn):
    recipe, _ = add_recipe(conn, 10)
    other, _ = add_recipe(conn, 11, name="Roggenbrot")
    first = _batch_size(conn, recipe, "Groß", is_limit=1)
    _batch_size(conn, recipe, "Klein", 10000)
    _batch_size(conn, other, "Groß", is_limit=1)          # anderes Rezept: erlaubt
    assert conn.execute("SELECT is_limit FROM recipe_batch_size WHERE label = 'Klein'").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _batch_size(conn, recipe, "Mittel", 15000, is_limit=1)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        _batch_size(conn, recipe, "Falsch", 15000, is_limit=2)
    # Haken umsetzen: erst den alten entfernen, dann den neuen setzen
    conn.execute("UPDATE recipe_batch_size SET is_limit = 0 WHERE id = ?", (first,))
    conn.execute("UPDATE recipe_batch_size SET is_limit = 1 WHERE label = 'Klein'")


# --- Auftrag ------------------------------------------------------------------

@pytest.mark.parametrize("basis_type", ["total", "pieces", "batch_size", "flour_total", "combined"])
def test_order_basis_types_including_combined(conn, basis_type):
    recipe, _ = add_recipe(conn, 10)
    add_order(conn, recipe, basis_type=basis_type)


def test_factor_needs_hundredths_in_range(conn):
    recipe, _ = add_recipe(conn, 10)
    add_order(conn, recipe, basis_type="factor", basis_value=15000, factor_hundredths=150)
    add_order(conn, recipe, basis_type="combined", basis_value=15000, factor_hundredths=1, total_part_g=5000)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_order(conn, recipe, basis_type="factor", basis_value=15000)
    for bad in (0, 10001):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            add_order(conn, recipe, basis_type="factor", basis_value=15000, factor_hundredths=bad)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_order(conn, recipe, basis_type="total", basis_value=15000, factor_hundredths=150)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_order(conn, recipe, basis_type="pieces", basis_value=15000, total_part_g=5000)


def test_limit_source_and_split_mode(conn):
    recipe, _ = add_recipe(conn, 10)
    add_order(conn, recipe, basis_value=32000, dough_count=2, limit_g=20000, limit_source="recipe",
              split_mode="fill")
    add_order(conn, recipe, basis_value=32000, dough_count=2, limit_g=16000, limit_source="order",
              split_mode="even")
    bad = [
        dict(limit_g=20000),                                     # Herkunft fehlt
        dict(limit_source="recipe"),                             # Grenze fehlt
        dict(split_mode="fill"),                                 # Teilung ohne Grenze
        dict(limit_g=20000, limit_source="station"),
        dict(limit_g=20000, limit_source="order", split_mode="half"),
        dict(limit_g=1_000_001, limit_source="order"),
    ]
    for extra in bad:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            add_order(conn, recipe, basis_value=32000, **extra)


def test_parent_dough_index_only_for_sub_orders(conn):
    recipe, _ = add_recipe(conn, 10)
    sub, _ = add_recipe(conn, 11, name="Vorteig")
    parent = add_order(conn, recipe)
    add_order(conn, sub, basis_value=3000, parent_order_id=parent, parent_item_position=1, parent_dough_index=2)
    add_order(conn, sub, basis_value=6000, parent_order_id=parent, parent_item_position=1)   # für alle
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_order(conn, sub, basis_value=3000, parent_dough_index=1)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_order(conn, sub, basis_value=3000, parent_order_id=parent, parent_item_position=1, parent_dough_index=0)


def test_old_triggers_still_work_after_rebuild(conn):
    water = add_raw_material(conn, 1, name="Wasser")
    recipe, version = add_recipe(conn, 10)
    other, other_version = add_recipe(conn, 11)
    add_item(conn, version, 1, water, amount_g=500)
    with pytest.raises(sqlite3.IntegrityError, match="nur beim Leitrohstoff"):
        add_order(conn, recipe, basis_type="total", basis_value=300, basis_item_position=1)
    with pytest.raises(sqlite3.IntegrityError, match="nicht zum Rezept"):
        add_order(conn, recipe, version_id=other_version)
    order = add_order(conn, recipe, version_id=version)
    # Fixieren sperrt die Version
    assert conn.execute("SELECT frozen_at FROM recipe_version WHERE id = ?", (version,)).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="bereits fixiert"):
        conn.execute("UPDATE production_order SET recipe_version_id = ? WHERE id = ?", (other_version, order))
    conn.execute("UPDATE production_order SET status = 'done' WHERE id = ?", (order,))
    with pytest.raises(sqlite3.IntegrityError, match="wieder geöffnet"):
        conn.execute("UPDATE production_order SET status = 'open' WHERE id = ?", (order,))
    # Trigger auf anderen Tabellen, die production_order nennen
    with pytest.raises(sqlite3.IntegrityError, match="abgeschlossen"):
        conn.execute("INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status) "
                     "VALUES ('T-1', ?, 1, ?, 'running')", (order, version))
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


# --- Neue Tabellen ------------------------------------------------------------

def test_order_batch_size_copies_and_counts(conn):
    recipe, _ = add_recipe(conn, 10)
    size = _batch_size(conn, recipe)
    order = add_order(conn, recipe, basis_type="combined", basis_value=40000)
    conn.execute("INSERT INTO order_batch_size (order_id, batch_size_id, label, kind, value, batch_count) "
                 "VALUES (?, ?, 'Großer Teig', 'weight', 20000, 2)", (order, size))
    conn.execute("INSERT INTO order_batch_size (order_id, label, kind, value, piece_weight_g, batch_count) "
                 "VALUES (?, 'Blech', 'pieces', 30, 65, 1)", (order,))
    for sql in (
        "INSERT INTO order_batch_size (order_id, label, kind, value, batch_count) VALUES (?, 'x', 'weight', 1, 0)",
        "INSERT INTO order_batch_size (order_id, label, kind, value, batch_count) VALUES (?, 'x', 'pieces', 1, 1)",
        "INSERT INTO order_batch_size (order_id, label, kind, value, piece_weight_g, batch_count) "
        "VALUES (?, 'x', 'weight', 1, 65, 1)",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(sql, (order,))
    # Chargengröße im Rezept gelöscht: Kopie im Auftrag bleibt
    conn.execute("DELETE FROM recipe_batch_size WHERE id = ?", (size,))
    row = conn.execute("SELECT batch_size_id, label, value, batch_count FROM order_batch_size "
                       "WHERE kind = 'weight'").fetchone()
    assert tuple(row) == (None, "Großer Teig", 20000, 2)


def test_order_dough_unique_index_and_target(conn):
    recipe, _ = add_recipe(conn, 10)
    order = add_order(conn, recipe, basis_value=32000, dough_count=2)
    conn.execute("INSERT INTO order_dough (order_id, dough_index, target_g) VALUES (?, 1, 20000)", (order,))
    conn.execute("INSERT INTO order_dough (order_id, dough_index, target_g) VALUES (?, 2, 12000)", (order,))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO order_dough (order_id, dough_index, target_g) VALUES (?, 2, 1)", (order,))
    for index, target in ((0, 1), (3, 0), (3, 1_000_001)):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("INSERT INTO order_dough (order_id, dough_index, target_g) VALUES (?, ?, ?)",
                         (order, index, target))
    # Löschen des Auftrags löscht die Teige mit
    conn.execute("DELETE FROM production_order WHERE id = ?", (order,))
    assert conn.execute("SELECT COUNT(*) FROM order_dough").fetchone()[0] == 0


def test_closed_order_keeps_doughs_and_batch_sizes(conn):
    recipe, version = add_recipe(conn, 10)
    order = add_order(conn, recipe, version_id=version, basis_type="combined", basis_value=20000)
    conn.execute("INSERT INTO order_dough (order_id, dough_index, target_g) VALUES (?, 1, 20000)", (order,))
    conn.execute("INSERT INTO order_batch_size (order_id, label, kind, value, batch_count) "
                 "VALUES (?, 'Groß', 'weight', 20000, 1)", (order,))
    conn.execute("UPDATE production_order SET status = 'done' WHERE id = ?", (order,))
    for sql in (
        "INSERT INTO order_dough (order_id, dough_index, target_g) VALUES (?, 2, 1)",
        "UPDATE order_dough SET target_g = 1 WHERE order_id = ?",
        "DELETE FROM order_dough WHERE order_id = ?",
        "INSERT INTO order_batch_size (order_id, label, kind, value, batch_count) VALUES (?, 'x', 'weight', 1, 1)",
        "UPDATE order_batch_size SET batch_count = 2 WHERE order_id = ?",
        "DELETE FROM order_batch_size WHERE order_id = ?",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="abgeschlossen"):
            conn.execute(sql, (order,))


# --- Migration mit Daten --------------------------------------------------------

def test_migration_on_database_with_data(tmp_path):
    """Eine Datenbank im Stand 0005 mit Aufträgen, Chargen und Stückzahlen kommt ohne Verlust auf 0006."""
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    for m in discover():
        if m.version <= 5:
            shutil.copy(m.path, old_dir / m.path.name)
    db = tmp_path / "rezeptbuch.db"

    old = init_database(db, migrations_dir=old_dir)
    rm = add_raw_material(old, 1, name="Wasser")
    recipe, version = add_recipe(old, 10)
    sub, _ = add_recipe(old, 11, name="Vorteig")
    item = add_item(old, version, 1, rm, amount_g=500)
    old.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g) VALUES (?, 'Brötchen', 65)", (recipe,))
    size = old.execute("INSERT INTO recipe_batch_size (recipe_id, label, kind, value) "
                       "VALUES (?, 'Groß', 'weight', 20000)", (recipe,)).lastrowid
    order = add_order(old, recipe, version_id=version, basis_type="raw_material", basis_value=300,
                      basis_raw_material_id=rm, basis_item_position=1, status="in_progress", dough_count=2)
    add_order(old, sub, basis_value=150, parent_order_id=order, parent_item_position=2)
    add_order(old, recipe, basis_type="batch_size", basis_value=20000, batch_size_id=size)
    old.execute("INSERT INTO order_piece (order_id, label, weight_g, piece_count) VALUES (?, 'Brötchen', 65, 3)",
                (order,))
    old.execute("INSERT INTO order_item_override (order_id, item_position, amount_g) VALUES (?, 1, 400)", (order,))
    batch = old.execute("INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status) "
                        "VALUES ('T-1', ?, 1, ?, 'running')", (order, version)).lastrowid
    old.execute("INSERT INTO batch_item (batch_id, position, recipe_item_id, item_type, raw_material_id, "
                "raw_material_number, raw_material_name, target_g, tolerance_g, units_target, rest_target_g) "
                "VALUES (?, 1, ?, 'raw_material', ?, 1, 'Wasser', 300, 5, 0, 300)", (batch, item, rm))
    before = [tuple(r) for r in old.execute("SELECT * FROM production_order ORDER BY id")]
    old.close()

    conn = init_database(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(discover())
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    after = [tuple(r)[:len(before[0])] for r in conn.execute(
        "SELECT id, recipe_id, recipe_version_id, parent_order_id, parent_item_position, basis_type, basis_value, "
        "basis_raw_material_id, basis_input_unit, batch_size_id, dough_count, fixed_station_id, planned_date, "
        "list_position, status, created_at, finished_at, basis_item_position FROM production_order ORDER BY id")]
    assert after == before
    assert conn.execute("SELECT COUNT(*) FROM order_piece").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM order_item_override").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM batch_item").fetchone()[0] == 1
    assert conn.execute("SELECT is_limit FROM recipe_batch_size").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    # Fremdschlüssel zeigen weiter auf die neue Tabelle
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("INSERT INTO order_piece (order_id, label, weight_g, piece_count) VALUES (999, 'x', 1, 1)")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("DELETE FROM production_order WHERE id = ?", (order,))   # Charge hängt daran
    assert len(list((tmp_path / "backups").glob("pre_migration_0005_*.db"))) == 1
    conn.close()


def test_shipped_file_name_and_marker():
    path = MIGRATIONS_DIR / "0006_order_doughs.sql"
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("-- migration: foreign_keys=off")
