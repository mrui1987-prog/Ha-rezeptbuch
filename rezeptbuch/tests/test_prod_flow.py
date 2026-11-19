"""Tests Modul 09 Teil C1: Aufträge, Teig starten, Zutatenarten, Pause/Weiter, Abbruch, Abschluss.

docs/ablauf.md Abschnitte 3 bis 9. Die Waage steht für den Mittelsmann (FakeHub); geprüft wird
mit der echten Datenbank (Migration 0007).
"""

import pytest

from app.errors import ConflictError, NotFoundError, ValidationError
from app.production import batches, orders
from app.production.batches import next_batch_no

from prod_helpers import clock, hub, recipes, rm, runner, unlock  # noqa: F401  (Fixtures)

TODAY = "2026-11-20"


def total(recipe_id, grams, **kw):
    data = {"recipe_id": recipe_id, "basis_type": "total", "value": grams, "planned_date": TODAY}
    data.update(kw)
    return data


def st(station=1, **kw):
    return {"station": station, **kw}


def start(conn, runner, order_id, station=1, **kw):
    return batches.start_dough(conn, order_id, st(station, **kw), runner, today=TODAY)


# -- Aufträge -----------------------------------------------------------------------------

def test_create_order_and_list(conn, recipes):
    order = orders.create_order(conn, total(recipes["brot"], 3240, fixed_station=1))
    assert order["status"] == "open" and order["dough_count"] == 1 and order["target_g"] == 3240
    assert order["recipe"]["name"] == "Weißbrot" and order["recipe"]["version_no"] is None
    assert order["fixed_station"] == 1 and order["doughs"][0]["batch"] is None
    second = orders.create_order(conn, total(recipes["brot"], 1620))
    listing = orders.list_orders(conn, TODAY)
    assert [o["id"] for o in listing["orders"]] == [order["id"], second["id"]]
    assert [o["list_position"] for o in listing["orders"]] == [1, 2]
    assert orders.list_orders(conn, "2026-11-21")["orders"] == []


def test_create_order_with_pieces_factor_and_split(conn, recipes):
    misch = recipes["misch"]
    factor = orders.create_order(conn, {"recipe_id": misch, "basis_type": "factor", "factor": "1,5",
                                        "planned_date": TODAY})
    assert factor["basis_value"] == 3750 and factor["target_g"] == 3750
    # Obergrenze 2 500 g: Rückfrage „teilen?“ bei Mehl gesamt, mit Ja zwei Teige
    with pytest.raises(ConflictError) as exc:
        orders.create_order(conn, {"recipe_id": misch, "basis_type": "flour_total", "value": 3000,
                                   "order_limit": 2500, "planned_date": TODAY})
    assert exc.value.code == "split_question"
    split = orders.create_order(conn, {"recipe_id": misch, "basis_type": "flour_total", "value": 3000,
                                       "order_limit": 2500, "split": True, "split_mode": "even",
                                       "sub_modes": [{"position": 1, "mode": "all"}], "planned_date": TODAY})
    assert split["dough_count"] == 2 and [d["target_g"] for d in split["doughs"]] == [2500, 2500]


def test_create_order_refusals(conn, recipes):
    with pytest.raises(ValidationError) as exc:
        orders.create_order(conn, total(recipes["brot"], 1000, version_no=1))
    assert exc.value.code == "version_not_allowed"
    conn.execute("UPDATE recipe SET locked = 1 WHERE id = ?", (recipes["brot"],))
    with pytest.raises(ConflictError) as exc:
        orders.create_order(conn, total(recipes["brot"], 1000))
    assert exc.value.code == "recipe_locked"
    unlock(conn, recipes["brot"])
    with pytest.raises(ConflictError) as exc:
        orders.create_order(conn, total(recipes["brot"], 1000, fixed_station=2))     # Waage 2 nicht eingerichtet
    assert exc.value.code == "not_configured"
    with pytest.raises(ValidationError):
        orders.create_order(conn, total(recipes["brot"], 1000, planned_date="20.11.2026"))


def test_delete_order_only_open_with_confirm(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    with pytest.raises(ConflictError) as exc:
        orders.delete_order(conn, order["id"], {})
    assert exc.value.code == "confirm_required"
    orders.delete_order(conn, order["id"], {"confirm": True})
    with pytest.raises(NotFoundError):
        orders.get_order(conn, order["id"])
    started = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 500)
    start(conn, runner, started["id"])
    with pytest.raises(ConflictError) as exc:
        orders.delete_order(conn, started["id"], {"confirm": True})
    assert exc.value.code == "order_started"


# -- Teig starten ----------------------------------------------------------------------------

def test_start_fixes_version_and_creates_batch(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 800)                    # Behälter steht schon auf der Waage
    batch = start(conn, runner, order["id"])
    assert batch["status"] == "running" and batch["owner_station"] == 1
    assert batch["batch_no"] == "20261120-001"
    assert batch["recipe"] == {"number": batch["recipe"]["number"], "name": "Weißbrot", "version_no": 1}
    assert batch["knead"] == "5+6" and batch["note"] == {"text": "Teig 10 min ruhen lassen", "display": "end"}
    assert [i["target_g"] for i in batch["items"]] == [1000, 600, 20]
    assert batch["current_position"] == 1 and batch["scale"]["actual_g"] == 0
    row = conn.execute("SELECT status, recipe_version_id FROM production_order WHERE id = ?",
                       (order["id"],)).fetchone()
    assert row["status"] == "in_progress" and row["recipe_version_id"] is not None
    frozen = conn.execute("SELECT frozen_at FROM recipe_version WHERE id = ?", (row["recipe_version_id"],)).fetchone()
    assert frozen[0] is not None
    assert next_batch_no(conn, TODAY) == "20261120-002"


def test_start_refusals(conn, recipes, runner, hub):
    hub.put(1, 0)
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    other = orders.create_order(conn, total(recipes["brot"], 1620))
    start(conn, runner, order["id"])
    with pytest.raises(ConflictError) as exc:
        start(conn, runner, order["id"])                       # Station belegt
    assert exc.value.code == "station_busy"
    conn.execute("UPDATE station SET active = 1 WHERE id = 2")
    with pytest.raises(ConflictError) as exc:
        start(conn, runner, order["id"], station=2)
    assert exc.value.code == "dough_started"
    fixed = orders.create_order(conn, total(recipes["brot"], 1620, fixed_station=1))
    with pytest.raises(ConflictError) as exc:
        start(conn, runner, fixed["id"], station=2)
    assert exc.value.code == "fixed_station"
    start(conn, runner, other["id"], station=2)


def test_start_unknown_station_and_dough(conn, recipes, runner):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    with pytest.raises(NotFoundError):
        start(conn, runner, order["id"], station=3)
    with pytest.raises(ValidationError):
        start(conn, runner, order["id"], dough_index=2)


# -- Wiegen und Quittieren ------------------------------------------------------------------------

def test_weigh_whole_dough_by_hand(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 800)
    batch = start(conn, runner, order["id"])
    bid = batch["id"]
    hub.put(1, 800 + 1010, stable=True)                     # Mehl 1 010 g, Toleranz 20 g
    batch = batches.ack_weighed(conn, bid, st(), runner)
    mehl = batch["items"][0]
    assert (mehl["actual_g"], mehl["ack_type"], mehl["ack_text"]) == (1010, "manual_stable", "manuell (stabil)")
    assert batch["current_position"] == 2 and batch["scale"]["actual_g"] == 0     # neuer Bezug
    hub.put(1, 1810 + 700, stable=False)                    # Wasser außerhalb der Toleranz (600 ± 50)
    with pytest.raises(ConflictError) as exc:
        batches.ack_weighed(conn, bid, st(), runner)
    assert exc.value.code == "out_of_tolerance" and exc.value.extra["actual_g"] == 700
    hub.put(1, 1810 + 620, stable=False)
    batch = batches.ack_weighed(conn, bid, st(), runner)
    assert batch["items"][1]["ack_type"] == "manual_unstable"
    assert batch["scale"]["taring"] is False                # Tara ausgeführt, auch bei unruhiger Waage (B2)
    hub.put(1, 2430 + 21)
    batch = batches.ack_weighed(conn, bid, st(), runner)
    assert batch["status"] == "done" and batch["finish_ack_at"] is None
    assert batch["progress"] == {"done": 3, "total": 3}
    assert orders.get_order(conn, order["id"])["status"] == "done"
    # Protokoll: Gewicht, Tara-Bezug, stabil
    events = conn.execute("SELECT event_type, weight_g, tare_g, stable FROM weighing_event ORDER BY id").fetchall()
    assert [tuple(e) for e in events] == [("weighed", 1010, 800, 1), ("weighed", 620, 1810, 0),
                                          ("weighed", 21, 2430, 1)]
    # Station bleibt belegt, bis der Teig abgeschlossen ist (K09-10)
    other = orders.create_order(conn, total(recipes["brot"], 1620))
    with pytest.raises(ConflictError):
        start(conn, runner, other["id"])
    batch = batches.finish(conn, bid, st(), runner)
    assert batch["finish_ack_at"] is not None
    start(conn, runner, other["id"])
    with pytest.raises(ConflictError):
        batches.finish(conn, bid, st(), runner)


def test_ack_needs_valid_scale_and_tare(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, None, status="invalid")
    batch = start(conn, runner, order["id"])
    hub.put(1, 1000)
    with pytest.raises(ConflictError) as exc:
        batches.ack_weighed(conn, batch["id"], st(), runner)
    assert exc.value.code == "tare_missing"
    batches.tare(conn, batch["id"], st(), runner)
    hub.put(1, None, status="offline")
    with pytest.raises(ConflictError) as exc:
        batches.ack_weighed(conn, batch["id"], st(), runner)
    assert exc.value.code == "scale_not_ok"
    hub.put(1, 2000)
    batches.ack_weighed(conn, batch["id"], st(), runner)
    tare = conn.execute("SELECT tare_g, note FROM weighing_event WHERE event_type = 'tare_set'").fetchone()
    assert tuple(tare) == (1000, "von Hand")


def test_units_hand_and_skip(conn, recipes, runner, hub):
    # Kuchen 1 000 g Mehl, 1 160 g Ei (21 × 55 g + 5 g), Vanille 0 g, Hefe 30 g mit Toleranz 0
    order = orders.create_order(conn, total(recipes["kuchen"], 2190))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    bid = batch["id"]
    ei = batch["items"][1]
    assert (ei["units_target"], ei["rest_target_g"], ei["unit_label"], ei["kind"]) == (21, 5, "Ei", "units")
    assert [i["kind"] for i in batch["items"]] == ["weigh", "units", "hand_need", "hand_target"]
    hub.put(1, 1000)
    batches.ack_weighed(conn, bid, st(), runner)
    with pytest.raises(ConflictError) as exc:
        batches.ack_weighed(conn, bid, st(), runner)            # erst die Einheiten
    assert exc.value.code == "not_weighable"
    batch = batches.ack_units(conn, bid, st(), runner)
    assert batch["items"][1]["kind"] == "weigh" and batch["items"][1]["units_acked"]
    hub.put(1, 1006)                                            # Rest 6 g (5 ± Toleranz)
    batch = batches.ack_weighed(conn, bid, st(), runner)
    assert batch["items"][1]["actual_g"] == 21 * 55 + 6
    with pytest.raises(ConflictError):
        batches.skip_item(conn, bid, st(), runner)              # ohne Bestätigung
    batch = batches.ack_hand(conn, bid, st(), runner)           # Vanille nach Bedarf
    assert batch["items"][2]["actual_g"] is None and batch["items"][2]["ack_type"] == "hand"
    batch = batches.skip_item(conn, bid, st(confirm=True), runner)
    assert batch["items"][3]["ack_type"] == "skipped" and batch["status"] == "done"


def test_units_with_zero_rest_finish_item(conn, rm, runner, hub):
    from app.recipes import create_recipe
    eier = create_recipe(conn, {"name": "Eierteig", "items": [{"type": "raw_material", "raw_material_id": rm["ei"],
                                                                "amount_g": 110}]})
    unlock(conn, eier["id"])
    order = orders.create_order(conn, total(eier["id"], 110))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    batch = batches.ack_units(conn, batch["id"], st(), runner)
    assert batch["status"] == "done" and batch["items"][0]["actual_g"] == 110


def test_select_other_item(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    batch = batches.select_item(conn, batch["id"], st(position=3), runner)
    assert batch["current_position"] == 3
    hub.put(1, 20)
    batch = batches.ack_weighed(conn, batch["id"], st(), runner)
    assert batch["current_position"] == 1 and batch["items"][2]["done"]
    with pytest.raises(ConflictError):
        batches.select_item(conn, batch["id"], st(position=3), runner)


# -- Unterrezepte ---------------------------------------------------------------------------------

def test_sub_recipe_orders_and_lines(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["misch"], 2500))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    full = orders.get_order(conn, order["id"])
    assert len(full["sub_orders"]) == 1
    sub = full["sub_orders"][0]
    assert sub["recipe"]["name"] == "Vorteig" and sub["target_g"] == 1000
    assert sub["parent"] == {"order_id": order["id"], "position": 1, "dough_index": None}
    line = batch["items"][0]
    assert line["item_type"] == "sub_recipe" and line["blocked"] and line["sub_order"]["id"] == sub["id"]
    assert batch["current_position"] == 2                      # wartende Unterrezept-Zeile übersprungen
    hub.put(1, 1000)
    batches.ack_weighed(conn, batch["id"], st(), runner)
    hub.put(1, 1500)
    batch = batches.ack_weighed(conn, batch["id"], st(), runner)
    assert batch["current_position"] == 1 and batch["status"] == "running"
    # Unterrezept an Waage 2 wiegen (K09-9), Hauptteig wartet
    conn.execute("UPDATE station SET active = 1 WHERE id = 2")
    hub.put(2, 0)
    sub_batch = start(conn, runner, sub["id"], station=2)
    hub.put(2, 505)
    batches.ack_weighed(conn, sub_batch["id"], st(2), runner)
    hub.put(2, 1000)
    sub_batch = batches.ack_weighed(conn, sub_batch["id"], st(2), runner)
    assert sub_batch["status"] == "done"
    batch = batches.check_sub(conn, batch["id"], st(), runner)
    assert batch["items"][0]["ack_type"] == "sub_done" and batch["items"][0]["actual_g"] == 1000
    assert batch["status"] == "done"


def test_sub_recipe_checked_without_weighing(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["misch"], 2500))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    with pytest.raises(ConflictError) as exc:
        batches.check_sub(conn, batch["id"], st(position=1), runner)
    assert exc.value.code == "confirm_required"
    batch = batches.check_sub(conn, batch["id"], st(position=1, confirm=True), runner)
    assert batch["items"][0]["ack_type"] == "sub_checked" and batch["items"][0]["actual_g"] == 1000


def test_two_doughs_sub_per_dough_and_for_all(conn, recipes, runner, hub):
    per = orders.create_order(conn, {"recipe_id": recipes["misch"], "basis_type": "total", "value": 5000, "order_limit": 2500,
                                     "split_mode": "fill", "planned_date": TODAY})
    assert per["dough_count"] == 2
    hub.put(1, 0)
    with pytest.raises(ValidationError):
        start(conn, runner, per["id"])                          # Teig angeben
    batch = start(conn, runner, per["id"], dough_index=2)
    subs = orders.get_order(conn, per["id"])["sub_orders"]
    assert [(s["parent"]["dough_index"], s["target_g"]) for s in subs] == [(1, 1000), (2, 1000)]
    assert batch["items"][0]["sub_order"]["id"] == subs[1]["id"]
    batches.cancel(conn, batch["id"], st(confirm=True), runner)
    for_all = orders.create_order(conn, {"recipe_id": recipes["misch"], "basis_type": "total", "value": 5000, "order_limit": 2500,
                                         "split_mode": "fill", "sub_modes": [{"position": 1, "mode": "all"}],
                                         "planned_date": TODAY})
    batch = start(conn, runner, for_all["id"], dough_index=1)
    subs = orders.get_order(conn, for_all["id"])["sub_orders"]
    assert [(s["parent"]["dough_index"], s["target_g"]) for s in subs] == [(None, 2000)]
    assert batch["items"][0]["sub_order"]["id"] == subs[0]["id"]


# -- Pause, Übergabe, Handwaage ---------------------------------------------------------------------

def test_pause_and_resume_at_other_station(conn, recipes, runner, hub):
    conn.execute("UPDATE station SET active = 1 WHERE id = 2")
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    bid = batch["id"]
    hub.put(1, 1000)
    batches.ack_weighed(conn, bid, st(), runner)
    with pytest.raises(ConflictError):
        batches.pause(conn, bid, st(2), runner)                 # nicht Besitzer
    batch = batches.pause(conn, bid, st(), runner)
    assert batch["status"] == "paused" and batch["owner_station"] is None and batch["pause_reason"] == "manual"
    with pytest.raises(ConflictError) as exc:
        batches.ack_weighed(conn, bid, st(), runner)
    assert exc.value.code == "batch_paused"
    # Waage 1 ist frei für einen anderen Teig
    other = orders.create_order(conn, total(recipes["brot"], 1620))
    start(conn, runner, other["id"])
    hub.put(2, 3000)                                            # Behälter auf Waage 2
    batch = batches.resume(conn, bid, st(2), runner)
    assert batch["status"] == "running" and batch["owner_station"] == 2 and batch["scale"]["actual_g"] == 0
    with pytest.raises(ConflictError) as exc:
        batches.resume(conn, bid, st(1), runner)
    assert exc.value.code == "already_resumed"
    hub.put(2, 3600)
    batch = batches.ack_weighed(conn, bid, st(2), runner)
    assert batch["items"][1]["station_id"] == 2 and batch["items"][0]["station_id"] == 1


def test_resume_race_second_station_loses(conn, recipes, runner, hub):
    conn.execute("UPDATE station SET active = 1 WHERE id = 2")
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    batches.pause(conn, batch["id"], st(), runner)
    # Zweite Station drückt gleichzeitig: bedingtes UPDATE ändert nichts mehr
    conn.execute("UPDATE batch SET status = 'running', owner_station_id = 1, pause_reason = NULL WHERE id = ?",
                 (batch["id"],))
    with pytest.raises(ConflictError) as exc:
        batches.resume(conn, batch["id"], st(2), runner)
    assert exc.value.code == "already_resumed" and exc.value.extra["owner_station"] == 1


def test_fixed_station_pause_stays_bound(conn, recipes, runner, hub):
    conn.execute("UPDATE station SET active = 1 WHERE id = 2")
    order = orders.create_order(conn, total(recipes["brot"], 1620, fixed_station=1))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    batch = batches.pause(conn, batch["id"], st(), runner)
    assert batch["owner_station"] == 1
    with pytest.raises(ConflictError) as exc:
        batches.resume(conn, batch["id"], st(2), runner)
    assert exc.value.code == "fixed_station"
    other = orders.create_order(conn, total(recipes["brot"], 1620))
    start(conn, runner, other["id"])                            # Pause blockiert die Station nicht


def test_hand_scale_reserves_station(conn, recipes, runner, hub):
    conn.execute("UPDATE station SET active = 1 WHERE id = 2")
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    batch = batches.pause(conn, batch["id"], st(), runner, reason="hand_scale")
    assert batch["pause_reason"] == "hand_scale" and batch["owner_station"] == 1
    with pytest.raises(ConflictError) as exc:
        batches.resume(conn, batch["id"], st(2), runner)
    assert exc.value.code == "reserved"
    other = orders.create_order(conn, total(recipes["brot"], 1620))
    with pytest.raises(ConflictError) as exc:
        start(conn, runner, other["id"])
    assert exc.value.code == "station_busy"
    batch = batches.resume(conn, batch["id"], st(1), runner)
    assert batch["status"] == "running"


def test_restart_pauses_running(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    conn.execute("UPDATE station SET active = 1 WHERE id = 2")
    fixed = orders.create_order(conn, total(recipes["brot"], 1620, fixed_station=2))
    hub.put(1, 0)
    hub.put(2, 0)
    first = start(conn, runner, order["id"])
    second = start(conn, runner, fixed["id"], station=2)
    assert batches.pause_running(conn) == 2
    a = batches.get_batch(conn, first["id"])
    b = batches.get_batch(conn, second["id"])
    assert (a["status"], a["pause_reason"], a["owner_station"]) == ("paused", "restart", None)
    assert (b["status"], b["owner_station"]) == ("paused", 2)
    assert batches.pause_running(conn) == 0


# -- Abbruch -------------------------------------------------------------------------------------

def test_cancel_keeps_protocol_and_closes_order(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    hub.put(1, 1000)
    batches.ack_weighed(conn, batch["id"], st(), runner)
    with pytest.raises(ConflictError):
        batches.cancel(conn, batch["id"], st(), runner)
    batch = batches.cancel(conn, batch["id"], st(confirm=True), runner)
    assert batch["status"] == "cancelled" and batch["items"][0]["actual_g"] == 1000
    assert orders.get_order(conn, order["id"])["status"] == "cancelled"
    assert conn.execute("SELECT count(*) FROM weighing_event").fetchone()[0] == 1
    other = orders.create_order(conn, total(recipes["brot"], 1620))
    start(conn, runner, other["id"])                            # Station wieder frei


def test_order_done_when_all_doughs_closed(conn, recipes, runner, hub):
    order = orders.create_order(conn, {"recipe_id": recipes["brot"], "basis_type": "total", "value": 3240,
                                       "order_limit": 1620, "split_mode": "fill", "planned_date": TODAY})
    assert order["dough_count"] == 2
    hub.put(1, 0)
    first = start(conn, runner, order["id"], dough_index=1)
    batches.cancel(conn, first["id"], st(confirm=True), runner)
    assert orders.get_order(conn, order["id"])["status"] == "in_progress"
    second = start(conn, runner, order["id"], dough_index=2)
    for weight in (1000, 1600, 1620):
        hub.put(1, weight)
        second = batches.ack_weighed(conn, second["id"], st(), runner)
    assert second["status"] == "done"
    assert orders.get_order(conn, order["id"])["status"] == "done"


def test_list_batches(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    listed = batches.list_batches(conn)
    assert [(b["id"], b["status"], b["owner_station"]) for b in listed] == [(batch["id"], "running", 1)]
    assert batches.list_batches(conn, station=2) == []


def test_skipped_item_comes_back_at_the_end(conn, recipes, runner, hub):
    """Überspringen (Oberfläche: andere Zutat wählen): weiter hinter der quittierten Zutat, die übersprungene
    kommt zum Schluss wieder (Michael 19.11.2026, 21:18)."""
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    targets = {i["position"]: i["rest_target_g"] for i in batch["items"]}
    assert len(targets) >= 3
    batch = batches.select_item(conn, batch["id"], st(position=2), runner)      # 1 überspringen
    load = targets[2]
    hub.put(1, load)
    batch = batches.ack_weighed(conn, batch["id"], st(), runner)
    assert batch["current_position"] == 3                                       # nicht zurück auf 1
    load += targets[3]
    hub.put(1, load)
    batch = batches.ack_weighed(conn, batch["id"], st(), runner)
    assert batch["current_position"] == (4 if 4 in targets else 1)
    assert not batch["items"][0]["done"]


def test_skip_text_is_weglassen(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    batch = start(conn, runner, order["id"])
    with pytest.raises(ConflictError) as err:
        batches.skip_item(conn, batch["id"], st(), runner)
    assert "weglassen" in str(err.value)
    batch = batches.skip_item(conn, batch["id"], st(confirm=True), runner)
    assert batch["items"][0]["ack_type"] == "skipped" and batch["items"][0]["ack_text"] == "weggelassen"
