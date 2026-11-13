"""Tests: Trigger für Versionen, Chargen und Protokolle (Modul 02, docs/datenmodell.md Abschnitt 5)."""

import pytest

from app.db import check_integrity
from conftest import add_item, add_order, add_raw_material, add_recipe, add_version, raises_db_error


@pytest.fixture
def started(conn):
    """Rezept mit einer Zeile, Auftrag gestartet (Version fixiert), eine laufende Charge mit einer Zutat."""
    egg = add_raw_material(conn, 1, name="Vollei", tolerance_value=30, unit_size_g=55, unit_label="Ei")
    recipe, version = add_recipe(conn, 10)
    add_item(conn, version, 1, egg, amount_g=580)
    order = add_order(conn, recipe, version_id=version, status="in_progress", dough_count=2)
    batch = conn.execute(
        "INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status, owner_station_id) "
        "VALUES ('T-1', ?, 1, ?, 'running', 1)", (order, version)).lastrowid
    item = conn.execute(
        "INSERT INTO batch_item (batch_id, position, item_type, raw_material_id, raw_material_number, "
        "raw_material_name, target_g, tolerance_g, unit_size_g, unit_label, units_target, rest_target_g) "
        "VALUES (?, 1, 'raw_material', ?, 1, 'Vollei', 580, 30, 55, 'Ei', 10, 30)", (batch, egg)).lastrowid
    return dict(egg=egg, recipe=recipe, version=version, order=order, batch=batch, item=item)


# --- Versionen (K4, K6) -----------------------------------------------------

def test_starting_order_freezes_version(conn):
    recipe, version = add_recipe(conn, 10)
    order = add_order(conn, recipe)
    assert conn.execute("SELECT frozen_at FROM recipe_version WHERE id = ?", (version,)).fetchone()[0] is None
    conn.execute("UPDATE production_order SET recipe_version_id = ?, status = 'in_progress' WHERE id = ?",
                 (version, order))
    assert conn.execute("SELECT frozen_at FROM recipe_version WHERE id = ?", (version,)).fetchone()[0] is not None


def test_unfrozen_version_can_be_overwritten(conn):
    rm = add_raw_material(conn, 1)
    _, version = add_recipe(conn, 10)
    item = add_item(conn, version, 1, rm, amount_g=1000)
    conn.execute("UPDATE recipe_item SET amount_g = 1100 WHERE id = ?", (item,))
    conn.execute("UPDATE recipe_version SET name = 'Weizenbrot hell' WHERE id = ?", (version,))


def test_frozen_version_is_read_only(conn, started):
    v, egg = started["version"], started["egg"]
    with raises_db_error("neue Version"):
        conn.execute("UPDATE recipe_version SET name = 'geändert' WHERE id = ?", (v,))
    with raises_db_error("neue Version"):
        conn.execute("UPDATE recipe_item SET amount_g = 600 WHERE recipe_version_id = ?", (v,))
    with raises_db_error("neue Version"):
        add_item(conn, v, 2, egg)
    with raises_db_error("neue Version"):
        conn.execute("DELETE FROM recipe_item WHERE recipe_version_id = ?", (v,))
    with raises_db_error("neue Version"):
        conn.execute("INSERT INTO recipe_version_step (recipe_version_id, step_no, name) VALUES (?, 1, 'x')", (v,))
    with raises_db_error("nicht gelöscht"):
        conn.execute("DELETE FROM recipe_version WHERE id = ?", (v,))


def test_new_version_after_production(conn, started):
    """Nach der Produktion entsteht beim Speichern eine neue Version (K4)."""
    egg, recipe = started["egg"], started["recipe"]
    v2 = add_version(conn, recipe, 2)
    add_item(conn, v2, 1, egg, amount_g=600)
    conn.execute("UPDATE recipe SET current_version_id = ? WHERE id = ?", (v2, recipe))
    old = conn.execute("SELECT amount_g FROM recipe_item WHERE recipe_version_id = ?",
                       (started["version"],)).fetchone()[0]
    assert old == 580  # alter Stand bleibt für die Charge erhalten


def test_order_version_fixed_once(conn, started):
    v2 = add_version(conn, started["recipe"], 2)
    with raises_db_error("bereits fixiert"):
        conn.execute("UPDATE production_order SET recipe_version_id = ? WHERE id = ?", (v2, started["order"]))


def test_order_version_must_match_recipe(conn):
    recipe_a, _ = add_recipe(conn, 10)
    _, version_b = add_recipe(conn, 20)
    with raises_db_error("gehört nicht"):
        add_order(conn, recipe_a, version_id=version_b, status="in_progress")
    order = add_order(conn, recipe_a)
    with raises_db_error("gehört nicht"):
        conn.execute("UPDATE production_order SET recipe_version_id = ? WHERE id = ?", (version_b, order))


def test_batch_uses_order_version(conn, started):
    """Alle Teige eines Auftrags nutzen dieselbe Version (K6)."""
    v2 = add_version(conn, started["recipe"], 2)
    with raises_db_error("Version des Auftrags"):
        conn.execute("INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status) "
                     "VALUES ('T-2', ?, 2, ?, 'running')", (started["order"], v2))
    conn.execute("INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status) "
                 "VALUES ('T-2', ?, 2, ?, 'running')", (started["order"], started["version"]))


def test_one_batch_per_dough(conn, started):
    with raises_db_error("UNIQUE"):
        conn.execute("INSERT INTO batch (batch_no, order_id, dough_index) VALUES ('T-9', ?, 1)", (started["order"],))


# --- Gebinde / Stück (M02-2c, M02-2d) ---------------------------------------

def test_units_and_rest_must_add_up(conn, started):
    with raises_db_error("CHECK"):
        conn.execute("UPDATE batch_item SET rest_target_g = 40 WHERE id = ?", (started["item"],))
    with raises_db_error("CHECK"):
        conn.execute(
            "INSERT INTO batch_item (batch_id, position, item_type, raw_material_id, raw_material_number, "
            "raw_material_name, target_g, tolerance_g, units_target, rest_target_g) "
            "VALUES (?, 2, 'raw_material', ?, 1, 'x', 500, 10, 0, 400)", (started["batch"], started["egg"]))


def test_weighing_events_units_then_rest(conn, started):
    item = started["item"]
    conn.execute("INSERT INTO weighing_event (batch_item_id, event_type, units, station_id) "
                 "VALUES (?, 'units_ack', 10, 1)", (item,))
    conn.execute("INSERT INTO weighing_event (batch_item_id, event_type, weight_g, stable, station_id) "
                 "VALUES (?, 'weighed', 28, 1, 1)", (item,))
    with raises_db_error("CHECK"):
        conn.execute("INSERT INTO weighing_event (batch_item_id, event_type, station_id) "
                     "VALUES (?, 'units_ack', 1)", (item,))


# --- Abgeschlossene Chargen und Protokolle ----------------------------------

def test_ack_needs_time(conn, started):
    with raises_db_error("CHECK"):
        conn.execute("UPDATE batch_item SET ack_type = 'auto_stable' WHERE id = ?", (started["item"],))
    conn.execute("UPDATE batch_item SET ack_type = 'auto_stable', acknowledged_at = '2026-11-13T18:00:00Z', "
                 "actual_g = 578, station_id = 1 WHERE id = ?", (started["item"],))


def test_closed_batch_is_read_only(conn, started):
    batch, item = started["batch"], started["item"]
    conn.execute("UPDATE batch SET status = 'done', finished_at = '2026-11-13T18:05:00Z' WHERE id = ?", (batch,))
    with raises_db_error("abgeschlossen"):
        conn.execute("UPDATE batch SET status = 'running' WHERE id = ?", (batch,))
    with raises_db_error("abgeschlossen"):
        conn.execute("UPDATE batch_item SET actual_g = 1 WHERE id = ?", (item,))
    with raises_db_error("abgeschlossen"):
        conn.execute("INSERT INTO weighing_event (batch_item_id, event_type, weight_g, station_id) "
                     "VALUES (?, 'weighed', 5, 1)", (item,))
    with raises_db_error("abgeschlossen"):
        conn.execute("DELETE FROM batch WHERE id = ?", (batch,))


def test_weighing_events_append_only(conn, started):
    event = conn.execute("INSERT INTO weighing_event (batch_item_id, event_type, weight_g, station_id) "
                         "VALUES (?, 'weighed', 28, 1)", (started["item"],)).lastrowid
    with raises_db_error("Wiegeprotokoll"):
        conn.execute("UPDATE weighing_event SET weight_g = 30 WHERE id = ?", (event,))
    with raises_db_error("Wiegeprotokoll"):
        conn.execute("DELETE FROM weighing_event WHERE id = ?", (event,))


def test_change_log_append_only(conn):
    entry = conn.execute("INSERT INTO change_log (source, entity, entity_id, action) "
                         "VALUES ('admin', 'recipe', 1, 'new_version')").lastrowid
    with raises_db_error("Änderungsprotokoll"):
        conn.execute("UPDATE change_log SET action = 'update' WHERE id = ?", (entry,))
    with raises_db_error("Änderungsprotokoll"):
        conn.execute("DELETE FROM change_log WHERE id = ?", (entry,))


def test_closed_order_overrides_locked(conn, started):
    order = started["order"]
    conn.execute("INSERT INTO order_item_override (order_id, item_position, amount_g) VALUES (?, 1, 600)", (order,))
    conn.execute("UPDATE production_order SET status = 'done' WHERE id = ?", (order,))
    with raises_db_error("abgeschlossen"):
        conn.execute("UPDATE order_item_override SET amount_g = 650 WHERE order_id = ?", (order,))


def test_used_version_and_order_cannot_be_deleted(conn, started):
    with raises_db_error():
        conn.execute("DELETE FROM recipe WHERE id = ?", (started["recipe"],))
    with raises_db_error("FOREIGN KEY"):
        conn.execute("DELETE FROM production_order WHERE id = ?", (started["order"],))


# --- Integritätsprüfung -----------------------------------------------------

def test_integrity_check_ok(conn, started):
    assert check_integrity(conn) == []


def test_integrity_check_finds_broken_reference(conn):
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO recipe_group (id, name) VALUES (1, 'Brot')")
    conn.execute("INSERT INTO recipe (number, group_id, locked) VALUES (5, 77, 0)")
    conn.execute("PRAGMA foreign_keys = ON")
    problems = check_integrity(conn)
    assert len(problems) == 1
    assert "recipe" in problems[0]
