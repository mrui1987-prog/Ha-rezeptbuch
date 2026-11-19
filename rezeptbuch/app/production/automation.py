"""Hintergrund des Wiegeablaufs (Modul 09 Teil C2, docs/ablauf.md Abschnitte 6.2a bis 6.6).

``tick`` läuft im Runner alle ``TICK_S`` Sekunden je Station:

* Behälter-Schritte weiterführen (K09-13 „Behälter wiegen“, K09-14 „Behälter wechseln“),
* Pause nach Waagenausfall (``offline_pause_seconds``, M09-8),
* automatische Quittung (M09-4),
* Abschluss durch Abnehmen des Behälters mit ``zero`` (K09-10),
* Live-Nachricht ``weigh`` (Ist, Soll, Toleranz, Bereich, Fortschritt, Tara läuft, Höchstlast, Hinweis).
"""

from __future__ import annotations

import logging
import sqlite3

from ..errors import ServiceError
from . import batches
from .runner import ProductionRunner
from .weigh import EMPTY_LIMIT_G, capacity_warning, zone

log = logging.getLogger("rezeptbuch.production")

PLACE_DELAY_S = 2.0     # nach Tara + Null (1 s Abstand in Add-on 2) erst dann auf den Behälter achten


def _active_batch(conn: sqlite3.Connection, station: int):
    return conn.execute(
        "SELECT * FROM batch WHERE owner_station_id = ? AND (status = 'running' "
        "OR (status = 'done' AND finish_ack_at IS NULL)) ORDER BY id LIMIT 1", (station,)).fetchone()


def _event(runner: ProductionRunner, data: dict, event: str) -> None:
    runner.broadcast({"type": "batch", "batch_id": data["id"], "status": data["status"],
                      "owner_station": data["owner_station"], "current_position": data["current_position"],
                      "event": event})
    if event in ("finished_dough", "finished", "paused"):
        runner.broadcast({"type": "orders"})


def tick(conn: sqlite3.Connection, runner: ProductionRunner) -> None:
    runner.refresh_settings(conn)
    for station in runner.stations():
        try:
            _station_tick(conn, runner, station)
        except ServiceError as exc:
            # z. B. Zeile inzwischen von Hand quittiert: nächster Durchlauf sieht den neuen Stand
            log.info("Waage %d: %s", station, exc.message)


def _station_tick(conn: sqlite3.Connection, runner: ProductionRunner, station: int) -> None:
    s = runner.settings
    sw, sample, _events = runner.observe(station)
    row = _active_batch(conn, station)
    flow = runner.flow(station)
    message = {"type": "weigh", "station": station, "batch_id": None, "position": None, "status": sample.status}

    if flow is not None and (row is None or row["id"] != flow.batch_id or row["status"] != "running"):
        runner.end_flow(station)                 # Teig inzwischen pausiert oder beendet
        flow = None

    if flow is not None:
        _advance_flow(conn, runner, station, flow, sw, sample)
    elif row is not None and row["status"] == "running":
        if runner.offline_for(station, sample) >= s["offline_pause_seconds"]:
            data = batches.pause(conn, row["id"], {"station": station}, runner, reason="scale_offline")
            log.warning("Waage %d seit %d s getrennt – Teig %s pausiert", station, s["offline_pause_seconds"],
                        row["batch_no"])
            _event(runner, data, "paused")
            row = None
        else:
            item = _current_item(conn, row)
            if item is not None and batches.item_kind(item) == "weigh":
                part = sw.actual(sample)
                actual = None if part is None else item["partial_g"] + part
                if sw.auto_ack(runner.clock(), actual, item["rest_target_g"], item["tolerance_g"],
                               s["auto_ack_seconds"], s["auto_ack_span_g"]):
                    data = batches.ack_auto(conn, row["id"], station, runner)
                    _event(runner, data, "finished_dough" if data["status"] == "done" else "acked")
                    row = _active_batch(conn, station)
            else:
                sw.reset_ack()
    elif row is not None and row["status"] == "done":
        gross = sw.gross(sample)
        if sample.status == "invalid" or (sample.ok and gross is not None and gross < EMPTY_LIMIT_G):
            runner.zero(station)
            data = batches.finish_auto(conn, row["id"], station, runner)
            log.info("Waage %d: Behälter abgenommen – Teig %s abgeschlossen", station, row["batch_no"])
            _event(runner, data, "finished")
            row = None
    else:
        sw.reset_ack()

    message.update(_weigh_message(conn, runner, station, row))
    runner.emit_weigh(station, message)


def _current_item(conn, row):
    if row["current_position"] is None:
        return None
    for item in batches._item_rows(conn, row["id"]):
        if item["position"] == row["current_position"]:
            return item if item["ack_type"] is None else None
    return None


def _advance_flow(conn, runner: ProductionRunner, station: int, flow, sw, sample) -> None:
    """Behälter-Schritte (6.2a, 6.2b)."""
    now = runner.clock()
    if flow.step in ("empty", "remove"):
        gross = sw.gross(sample)
        if flow.step == "remove":
            ready = sample.status == "invalid" or (sample.ok and gross is not None and gross < EMPTY_LIMIT_G)
        else:
            ready = sample.status == "invalid" or (
                sample.ok and sample.stable and abs(sample.weight_g) <= EMPTY_LIMIT_G
                and (gross is None or gross <= EMPTY_LIMIT_G))
        if ready:
            # Tara, 1 s später Null (Add-on 2 hält den Abstand ein, K09-14 Michael 12:22)
            runner.send(station, "tare")
            runner.zero(station)
            sw.clear()
            flow.step, flow.sent_at = "place", now
        return
    if flow.step == "place":
        if flow.sent_at is not None and now - flow.sent_at < PLACE_DELAY_S:
            return
        if sample.ok and sample.stable and sample.net is not True and sample.weight_g > EMPTY_LIMIT_G:
            weight = sample.weight_g
            row = conn.execute("SELECT container_g FROM batch WHERE id = ?", (flow.batch_id,)).fetchone()
            old = row["container_g"] if row else None
            if flow.kind == "change" and old and abs(weight - old) > runner.settings["resume_check_g"]:
                flow.step, flow.measured_g = "confirm", weight
                return
            batches.save_container(conn, flow.batch_id, station, runner, weight, "gewogen")
            runner.set_reference(station)        # Tara mit dem Behälter
            log.info("Waage %d: Behälter %d g", station, weight)


def _weigh_message(conn, runner: ProductionRunner, station: int, row) -> dict:
    sw = runner.weigh_state(station)
    sample = sw.last
    flow = runner.flow(station)
    display = sample.weight_g if sample is not None and sample.ok else None
    gross = sw.gross(sample) if sample is not None else None
    data = {"actual_g": sw.actual(sample) if sample is not None else None, "gross_g": gross,
            "taring": sw.taring, "hint": flow.hint if flow else sw.hint,
            "container_step": flow.step if flow else None, "target_g": None, "tolerance_g": None,
            "zone": None, "auto_ack_progress": 0, "capacity_warning": False}
    remaining = 0
    if row is not None:
        data["batch_id"] = row["id"]
        data["position"] = row["current_position"]
        open_items = [i for i in batches._item_rows(conn, row["id"]) if i["ack_type"] is None]
        current = next((i for i in open_items if i["position"] == row["current_position"]), None)
        if current is not None and batches.item_kind(current) == "weigh" and data["actual_g"] is not None:
            data["actual_g"] += current["partial_g"]
            data["target_g"] = current["rest_target_g"]
            data["tolerance_g"] = current["tolerance_g"]
            data["zone"] = zone(data["actual_g"], current["rest_target_g"], current["tolerance_g"])
            data["auto_ack_progress"] = sw.progress
        for item in open_items:
            if item["item_type"] == "raw_material":
                remaining += item["rest_target_g"] - (item["partial_g"] or 0)
        if current is not None and data["actual_g"] is not None and batches.item_kind(current) == "weigh":
            remaining -= max(data["actual_g"] - current["partial_g"], 0)
    capacity = sample.capacity_g if sample is not None else None
    data["capacity_warning"] = capacity_warning(gross, display, capacity, runner.settings["capacity_warn_g"],
                                                remaining)
    return data
