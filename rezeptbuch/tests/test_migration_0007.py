"""Tests: Migration 0007 (Wiegeablauf, Modul 09, docs/ablauf.md Abschnitt 12) und Einstellungen (Abschnitt 10)."""

import shutil
import sqlite3

import pytest

from app.db import MIGRATIONS_DIR, init_database
from app.errors import ValidationError
from app.production.settings import load_settings, save_settings

from conftest import add_item, add_order, add_raw_material, add_recipe


def columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


@pytest.fixture
def started(conn):
    rm = add_raw_material(conn, 1)
    recipe, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm, 1000)
    order = add_order(conn, recipe, version_id=version, status="in_progress")
    batch = conn.execute("INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status, "
                         "owner_station_id) VALUES ('T-1', ?, 1, ?, 'running', 1)", (order, version)).lastrowid
    item = conn.execute(
        "INSERT INTO batch_item (batch_id, position, item_type, raw_material_id, raw_material_number, "
        "raw_material_name, target_g, tolerance_g, rest_target_g) VALUES (?, 1, 'raw_material', ?, 1, 'Mehl', "
        "1000, 20, 1000)", (batch, rm)).lastrowid
    return {"order": order, "version": version, "batch": batch, "item": item, "recipe": recipe}


def test_new_columns(conn):
    assert {"pause_reason", "paused_at", "pause_load_g", "finish_ack_at", "container_g",
            "current_position"} <= columns(conn, "batch")
    assert "note" in columns(conn, "weighing_event")
    assert "sub_modes" in columns(conn, "production_order")


def test_new_ack_types(conn, started):
    for ack in ("manual_stable", "sub_done"):
        conn.execute("UPDATE batch_item SET ack_type = ?, acknowledged_at = '2026-11-20T08:00:00Z' WHERE id = ?",
                     (ack, started["item"]))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE batch_item SET ack_type = 'unbekannt' WHERE id = ?", (started["item"],))


def test_new_event_types(conn, started):
    for event in ("resume_deviation", "container", "partial"):
        conn.execute("INSERT INTO weighing_event (batch_item_id, event_type, weight_g, station_id, note) "
                     "VALUES (?, ?, 12, 1, 'x')", (started["item"], event))
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute("INSERT INTO weighing_event (batch_item_id, event_type, station_id) VALUES (?, ?, 1)",
                         (started["item"], event))
    with pytest.raises(sqlite3.DatabaseError, match="Wiegeprotokoll"):
        conn.execute("DELETE FROM weighing_event")


def test_pause_reason_checked(conn, started):
    conn.execute("UPDATE batch SET status = 'paused', pause_reason = 'hand_scale' WHERE id = ?", (started["batch"],))
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("UPDATE batch SET pause_reason = 'kaffee' WHERE id = ?", (started["batch"],))


def test_one_running_batch_per_station(conn, started):
    order2 = add_order(conn, started["recipe"], version_id=started["version"], status="in_progress")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute("INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status, "
                     "owner_station_id) VALUES ('T-2', ?, 1, ?, 'running', 1)", (order2, started["version"]))
    conn.execute("INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status, "
                 "owner_station_id) VALUES ('T-2', ?, 1, ?, 'paused', 1)", (order2, started["version"]))


def test_done_batch_allows_only_finish_ack(conn, started):
    batch = started["batch"]
    conn.execute("UPDATE batch_item SET ack_type = 'manual_stable', acknowledged_at = 'x', actual_g = 1000 "
                 "WHERE id = ?", (started["item"],))
    conn.execute("UPDATE batch SET status = 'done', finished_at = '2026-11-20T08:00:00Z' WHERE id = ?", (batch,))
    with pytest.raises(sqlite3.DatabaseError, match="abgeschlossen"):
        conn.execute("UPDATE batch SET batch_no = 'X' WHERE id = ?", (batch,))
    with pytest.raises(sqlite3.DatabaseError, match="abgeschlossen"):
        conn.execute("UPDATE batch SET finish_ack_at = 'x', container_g = 5 WHERE id = ?", (batch,))
    conn.execute("UPDATE batch SET finish_ack_at = '2026-11-20T08:01:00Z' WHERE id = ?", (batch,))
    with pytest.raises(sqlite3.DatabaseError, match="abgeschlossen"):
        conn.execute("UPDATE batch SET finish_ack_at = '2026-11-20T08:02:00Z' WHERE id = ?", (batch,))
    with pytest.raises(sqlite3.DatabaseError, match="abgeschlossen"):
        conn.execute("UPDATE batch_item SET actual_g = 1 WHERE id = ?", (started["item"],))


def test_existing_rows_survive_migration(tmp_path):
    """Datenbank auf Stand 0006 mit Charge und Protokoll → 0007: alles bleibt erhalten."""
    old_dir = tmp_path / "migrations"
    old_dir.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 6:
            shutil.copy(path, old_dir / path.name)
    db = tmp_path / "x.db"
    conn = init_database(db, migrations_dir=old_dir)
    rm = add_raw_material(conn, 1)
    recipe, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm, 1000)
    order = add_order(conn, recipe, version_id=version, status="in_progress")
    batch = conn.execute("INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status) "
                         "VALUES ('T-1', ?, 1, ?, 'running')", (order, version)).lastrowid
    item = conn.execute(
        "INSERT INTO batch_item (batch_id, position, item_type, raw_material_id, raw_material_number, "
        "raw_material_name, target_g, tolerance_g, rest_target_g, ack_type, acknowledged_at, actual_g) "
        "VALUES (?, 1, 'raw_material', ?, 1, 'Mehl', 1000, 20, 1000, 'auto_stable', 'x', 1001)",
        (batch, rm)).lastrowid
    conn.execute("INSERT INTO weighing_event (batch_item_id, event_type, weight_g, station_id) "
                 "VALUES (?, 'weighed', 1001, 1)", (item,))
    conn.close()
    conn = init_database(db, backup_dir=tmp_path / "backups")
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 7
    row = conn.execute("SELECT ack_type, actual_g FROM batch_item WHERE id = ?", (item,)).fetchone()
    assert tuple(row) == ("auto_stable", 1001)
    event = conn.execute("SELECT event_type, weight_g, note FROM weighing_event").fetchone()
    assert tuple(event) == ("weighed", 1001, None)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(sqlite3.DatabaseError, match="Wiegeprotokoll"):
        conn.execute("UPDATE weighing_event SET weight_g = 1")
    conn.close()


# -- Einstellungen -----------------------------------------------------------------------

def test_settings_defaults_and_save(conn):
    assert load_settings(conn) == {"auto_ack_seconds": 2, "auto_ack_span_g": 5, "offline_pause_seconds": 45,
                                   "capacity_warn_g": 1000, "tare_confirm_seconds": 3, "resume_check_g": 5}
    saved = save_settings(conn, {"auto_ack_seconds": "3", "resume_check_g": 10})
    assert saved["auto_ack_seconds"] == 3 and saved["resume_check_g"] == 10
    conn.execute("UPDATE setting SET value = 'kaputt' WHERE key = 'auto_ack_seconds'")
    assert load_settings(conn)["auto_ack_seconds"] == 2


@pytest.mark.parametrize("data, field", [
    ({"auto_ack_seconds": 0}, "auto_ack_seconds"),
    ({"auto_ack_span_g": 51}, "auto_ack_span_g"),
    ({"offline_pause_seconds": "4,5"}, "offline_pause_seconds"),
    ({"capacity_warn_g": True}, "capacity_warn_g"),
    ({"unbekannt": 1}, "unbekannt"),
])
def test_settings_refused(conn, data, field):
    with pytest.raises(ValidationError) as exc:
        save_settings(conn, data)
    assert exc.value.field == field
    assert load_settings(conn)["auto_ack_seconds"] == 2
