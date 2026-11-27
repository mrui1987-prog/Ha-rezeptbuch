"""Tests: Migration 0015 (Handelsware und Pfand H1, docs/handelsware.md) – Bestandsdaten bleiben erhalten."""

import shutil
import sqlite3

import pytest

from app.db import MIGRATIONS_DIR, init_database

from conftest import add_raw_material


def test_upgrade_keeps_data(tmp_path):
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 14:
            shutil.copy(path, old_dir / path.name)
    db = tmp_path / "r.db"
    conn = init_database(db, backup_dir=tmp_path / "b", migrations_dir=old_dir)
    rm = add_raw_material(conn, 1, "Weizenmehl", "flour")
    aid = conn.execute("INSERT INTO raw_material (number, name, type, tolerance_value, unit_size_g, unit_label, stock_g, "
                       "location1_id, booking_group_id, substitute_note) VALUES (2, 'Tüten', 'aid', 0, 1000, 'VE', 5000, "
                       "NULL, 9, 'x')").lastrowid
    conn.execute("INSERT INTO stock_movement (raw_material_id, kind, delta_g, stock_after_g, reason, attachment) "
                 "VALUES (?, 'loss', -1000, 4000, 'own_use', 'zugang-1.jpg')", (aid,))
    conn.commit()
    conn.close()
    conn = init_database(db, backup_dir=tmp_path / "b")
    row = conn.execute("SELECT * FROM raw_material WHERE id = ?", (aid,)).fetchone()
    assert row["stock_g"] == 5000 and row["booking_group_id"] == 9 and row["substitute_note"] == "x"
    assert row["is_deposit"] == 0 and row["register_no"] is None
    m = conn.execute("SELECT * FROM stock_movement").fetchone()
    assert m["reason"] == "own_use" and m["attachment"] == "zugang-1.jpg"
    assert conn.execute("SELECT type FROM raw_material WHERE id = ?", (rm,)).fetchone()[0] == "flour"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_goods_checks(conn):
    g = conn.execute("INSERT INTO raw_material (number, name, type, tolerance_value, unit_size_g, unit_label, stock_g) "
                     "VALUES (1, 'Cola', 'goods', 0, 1000, 'Stück', 0)").lastrowid
    m = add_raw_material(conn, 2, "H-Milch")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):       # Pfand nur bei Handelsware
        conn.execute("UPDATE raw_material SET is_deposit = 1 WHERE id = ?", (m,))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):       # Verweis ohne eigenen Bestand
        conn.execute("UPDATE raw_material SET stock_ref_id = ?, piece_g = 1000 WHERE id = ?", (m, g))
    conn.execute("UPDATE raw_material SET stock_g = NULL, stock_ref_id = ?, piece_g = 1000, register_no = 1200 "
                 "WHERE id = ?", (m, g))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO raw_material (number, name, type, tolerance_value, unit_size_g, unit_label, "
                     "register_no) VALUES (3, 'Fanta', 'goods', 0, 1000, 'Stück', 1200)")
    conn.execute("INSERT INTO stock_movement (raw_material_id, kind, delta_g) VALUES (?, 'sale', -1000)", (m,))
