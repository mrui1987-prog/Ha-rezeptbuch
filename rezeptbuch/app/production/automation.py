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

FINAL_TARE_REPEATS = 2      # Tara nach dem Behälter höchstens zweimal wiederholen (M09-19)
log = logging.getLogger("rezeptbuch.production")

TARE_PAUSE_S = 0.5      # ½ s nach der Tara das erste zero (Michael 23:02, vorher 2 s)
SETTLE_MIN_S = 0.5      # nach dem ersten zero mindestens so lange warten, damit „stabil“ frisch ist
SETTLE_MAX_S = 3.0      # höchstens so lange auf eine stabile Anzeige warten, dann das zweite zero trotzdem
ZERO_WAIT_S = 2.0       # so lange auf die Bestätigung der Null warten, dann erneut senden
ZERO_REPEATS = 2        # Null nach dem zweiten zero höchstens zweimal wiederholen (Michael 17:14)
ZERO_OK_G = 5           # Null bestätigt: Waage stabil, ohne Tara, Anzeige höchstens ±5 g


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
                batches.record_snapshot(conn, row, station, runner)        # Stand für „Weiter“ (M09-17)
                part = sw.actual(sample)
                actual = None if part is None else item["partial_g"] + part
                if sw.auto_ack(runner.clock(), actual, item["rest_target_g"], item["tolerance_g"],
                               s["auto_ack_seconds"], s["auto_ack_span_g"], s["auto_ack_min_g"]):
                    data = batches.ack_auto(conn, row["id"], station, runner)
                    _event(runner, data, "finished_dough" if data["status"] == "done" else "acked")
                    row = _active_batch(conn, station)
            else:
                sw.reset_ack()
    elif row is not None and row["status"] == "done":
        gross = sw.gross(sample)
        removed = sample.status == "invalid" or (sample.ok and gross is not None and gross < EMPTY_LIMIT_G)
        if runner.ready_for_command(station, "finish", removed):        # M09-21: Null erst bei Ruhe
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
        if runner.ready_for_command(station, "empty", ready):          # M09-21: erst bei ruhiger Anzeige
            runner.send(station, "tare")
            sw.clear()
            flow.step, flow.sent_at = "zeroing", now
            flow.zero_sent, flow.zero_at, flow.zero_failed = 0, None, False
        return
    if flow.step == "zeroing":
        # Michael 23:02: die KERN verwirft tare/zero bei unruhiger Anzeige (piept trotzdem) – deshalb
        # ½ s nach der Tara zero, auf stabile Anzeige warten, zero erneut; danach Bestätigung/Wiederholung
        if flow.zero_sent == 0:
            if runner.ready_for_command(station, "zero1", now - flow.sent_at >= TARE_PAUSE_S):
                runner.zero(station)
                flow.zero_sent, flow.zero_at = 1, now
            return
        if flow.zero_sent == 1:
            if runner.ready_for_command(station, "zero2", now - flow.zero_at >= SETTLE_MIN_S):
                runner.zero(station)
                flow.zero_sent, flow.zero_at = 2, now
            return
        if _zero_confirmed(sample) and now - flow.zero_at >= SETTLE_MIN_S:
            sw.clear()
            flow.step, flow.sent_at = "place", now
            log.info("Waage %d: Null bestätigt nach %d Befehl(en)", station, flow.zero_sent)
            return
        if now - flow.zero_at >= ZERO_WAIT_S:
            if flow.zero_sent < 2 + ZERO_REPEATS:
                if not runner.ready_for_command(station, "zero_repeat"):
                    return
                runner.zero(station)
                flow.zero_sent, flow.zero_at = flow.zero_sent + 1, now
                log.info("Waage %d: Null nicht bestätigt, %d. Wiederholung", station, flow.zero_sent - 2)
            elif not flow.zero_failed:
                flow.zero_failed = True
                log.warning("Waage %d: Null nach %d Versuchen nicht bestätigt – bitte von Hand", station,
                            flow.zero_sent)
        return
    if flow.step == "final_tare":
        # M09-19: nach dem Behälter nur Tara. Bestätigt = Waage zeigt netto ~0; sonst bei ruhiger Anzeige
        # bis zu FINAL_TARE_REPEATS-mal neu senden, danach rechnet die Software selbst weiter (Hinweis bleibt)
        if sw.taring:
            return
        if sample.ok and sample.net is True and abs(sample.weight_g) <= runner.settings["auto_ack_span_g"]:
            runner.end_flow(station)
            return
        if flow.zero_sent >= FINAL_TARE_REPEATS:
            log.warning("Waage %d: Tara nach dem Behälter nicht bestätigt – die Software rechnet weiter", station)
            runner.end_flow(station)
            return
        if runner.ready_for_command(station, "final_tare", now - flow.sent_at >= SETTLE_MIN_S):
            flow.zero_sent += 1
            flow.sent_at = now
            log.info("Waage %d: Tara nicht bestätigt, %d. Wiederholung", station, flow.zero_sent)
            runner.set_reference(station)
        return
    if flow.step == "place":
        placed = sample.ok and sample.stable and sample.net is not True and sample.weight_g > EMPTY_LIMIT_G
        if runner.ready_for_command(station, "place", placed):         # M09-21: Tara erst bei ruhigem Behälter
            sample = runner.sample(station)
            if not (sample.ok and sample.net is not True and sample.weight_g > EMPTY_LIMIT_G):
                return
            weight = sample.weight_g
            row = conn.execute("SELECT container_g FROM batch WHERE id = ?", (flow.batch_id,)).fetchone()
            old = row["container_g"] if row else None
            if flow.kind == "change" and old and abs(weight - old) > runner.settings["resume_check_g"]:
                flow.step, flow.measured_g = "confirm", weight
                return
            batches.save_container(conn, flow.batch_id, station, runner, weight, "gewogen")
            runner.finish_container(station, flow.kind, flow.batch_id)    # Tara, dann Null
            log.info("Waage %d: Behälter %d g", station, weight)


def _settled(sample, waited: float) -> bool:
    """Zweites zero: Anzeige stabil (frühestens nach SETTLE_MIN_S) oder spätestens nach SETTLE_MAX_S."""
    return (sample.ok and sample.stable and waited >= SETTLE_MIN_S) or waited >= SETTLE_MAX_S


def _zero_confirmed(sample) -> bool:
    """Die Waage zeigt nach ``zero`` stabil brutto 0 (keine Tara aktiv)."""
    return bool(sample.ok and sample.stable and sample.net is not True and sample.weight_g is not None
                and abs(sample.weight_g) <= ZERO_OK_G)


def _weigh_message(conn, runner: ProductionRunner, station: int, row) -> dict:
    sw = runner.weigh_state(station)
    sample = sw.last
    flow = runner.flow(station)
    display = sample.weight_g if sample is not None and sample.ok else None
    gross = sw.gross(sample) if sample is not None else None
    data = {"actual_g": sw.actual(sample) if sample is not None else None, "gross_g": gross,
            "taring": sw.taring, "hint": flow.hint if flow else sw.hint,
            "container_step": flow.step if flow else None, "target_g": None, "tolerance_g": None,
            "zone": None, "auto_ack_progress": 0, "capacity_warning": False,
            "notice": runner.notice(station)}
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
