"""Chargen: Teig starten, Zutaten quittieren, Pause/Weiter, Abbruch, Abschluss (Modul 09).

docs/ablauf.md Abschnitte 3 bis 8 (M09-6, M09-9 bis M09-12, K09-1, K09-2, K09-4, K09-5, K09-9 bis K09-11).
Die Wahrheit liegt in der Datenbank; jede ändernde Funktion nennt die Station und prüft Besitzer und
Status. Den Messwert liefert der ``runner`` (Waage über den Mittelsmann, Tara-Bezug der Software).

Stand Teil C1 (0.9.0): Quittieren beim Wiegen von Hand mit dem Waagenwert („manuell stabil/nicht
stabil“). Auto-Quittung, Tara an der Waage, Lastprüfung beim „Weiter“ (K09-12) und Abschluss durch
Abnehmen des Behälters folgen in Teil C2.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from ..calculation.service import build_batch_items
from ..db import transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from . import orders as orders_mod
from .common import require_confirm, station_busy, station_row, utc_now, whole
from .runner import ProductionRunner

ITEM_COLUMNS = ("position", "recipe_item_id", "item_type", "raw_material_id", "raw_material_number",
                "raw_material_name", "sub_order_id", "target_g", "tolerance_g", "unit_size_g", "unit_label",
                "units_target", "rest_target_g")

ACK_TEXT = {
    "auto_stable": "automatisch (stabil)",
    "manual_stable": "manuell (stabil)",
    "manual_unstable": "manuell (nicht stabil)",
    "hand": "Handzugabe",
    "sub_checked": "abgehakt",
    "sub_done": "Unterrezept gewogen",
    "skipped": "übergangen",
}


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------

def _batch_row(conn: sqlite3.Connection, batch_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT b.*, o.fixed_station_id, o.dough_count FROM batch b JOIN production_order o ON o.id = b.order_id "
        "WHERE b.id = ?", (batch_id,)).fetchone()
    if row is None:
        raise NotFoundError("Charge nicht gefunden.", code="not_found")
    return row


def _item_rows(conn: sqlite3.Connection, batch_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT bi.*, rm.display_name, so.status AS sub_status, so.parent_dough_index AS sub_dough_index, "
        "       sv.name AS sub_name, "
        "       EXISTS (SELECT 1 FROM weighing_event e WHERE e.batch_item_id = bi.id "
        "               AND e.event_type = 'units_ack') AS units_acked "
        "FROM batch_item bi "
        "LEFT JOIN raw_material rm ON rm.id = bi.raw_material_id "
        "LEFT JOIN production_order so ON so.id = bi.sub_order_id "
        "LEFT JOIN recipe sr ON sr.id = so.recipe_id "
        "LEFT JOIN recipe_version sv ON sv.id = COALESCE(so.recipe_version_id, sr.current_version_id) "
        "WHERE bi.batch_id = ? ORDER BY bi.position", (batch_id,)).fetchall()


def item_kind(item) -> str:
    """Art der Zutat (Abschnitt 5): sub_recipe, hand_need (Soll 0 g), units (erst ganze Einheiten),
    hand_target (Toleranz 0 g: nur quittieren, Ist = Soll) oder weigh."""
    if item["item_type"] == "sub_recipe":
        return "sub_recipe"
    if item["target_g"] == 0:
        return "hand_need"
    if item["units_target"] > 0 and not item["units_acked"]:
        return "units"
    if item["tolerance_g"] == 0:
        return "hand_target"
    return "weigh"


def _blocked(item) -> bool:
    """Unterrezept-Zeile wartet, bis der Unterrezept-Teig fertig ist (M09-10)."""
    return item["item_type"] == "sub_recipe" and item["sub_status"] != "done"


def _item_dict(item) -> dict:
    open_ = item["ack_type"] is None
    name = item["sub_name"] if item["item_type"] == "sub_recipe" else (item["display_name"] or item["raw_material_name"])
    return {
        "position": item["position"],
        "item_type": item["item_type"],
        "kind": item_kind(item) if open_ else None,
        "name": name,
        "raw_material_number": item["raw_material_number"],
        "raw_material_name": item["raw_material_name"],
        "target_g": item["target_g"],
        "tolerance_g": item["tolerance_g"],
        "unit_size_g": item["unit_size_g"],
        "unit_label": item["unit_label"],
        "units_target": item["units_target"],
        "units_acked": bool(item["units_acked"]),
        "rest_target_g": item["rest_target_g"],
        "actual_g": item["actual_g"],
        "ack_type": item["ack_type"],
        "ack_text": ACK_TEXT.get(item["ack_type"]),
        "acknowledged_at": item["acknowledged_at"],
        "station_id": item["station_id"],
        "sub_order": None if item["sub_order_id"] is None else {
            "id": item["sub_order_id"], "status": item["sub_status"], "dough_index": item["sub_dough_index"]},
        "blocked": open_ and _blocked(item),
        "done": not open_,
    }


def get_batch(conn: sqlite3.Connection, batch_id: int, runner: ProductionRunner | None = None) -> dict:
    row = _batch_row(conn, batch_id)
    version = conn.execute(
        "SELECT v.name, v.version_no, v.note, v.note_display, v.knead_slow_min, v.knead_fast_min, r.number "
        "FROM recipe_version v JOIN recipe r ON r.id = v.recipe_id WHERE v.id = ?",
        (row["recipe_version_id"],)).fetchone()
    items = [_item_dict(i) for i in _item_rows(conn, batch_id)]
    knead = None
    if version and (version["knead_slow_min"] is not None or version["knead_fast_min"] is not None):
        knead = f"{version['knead_slow_min'] or 0}+{version['knead_fast_min'] or 0}"
    data = {
        "id": row["id"], "batch_no": row["batch_no"], "status": row["status"],
        "order_id": row["order_id"], "dough_index": row["dough_index"], "dough_count": row["dough_count"],
        "recipe": None if version is None else {"number": version["number"], "name": version["name"],
                                                "version_no": version["version_no"]},
        "note": None if version is None or not version["note"] else {"text": version["note"],
                                                                       "display": version["note_display"]},
        "knead": knead,
        "owner_station": row["owner_station_id"], "fixed_station": row["fixed_station_id"],
        "pause_reason": row["pause_reason"], "paused_at": row["paused_at"],
        "started_at": row["started_at"], "finished_at": row["finished_at"], "finish_ack_at": row["finish_ack_at"],
        "container_g": row["container_g"],
        "current_position": row["current_position"],
        "items": items,
        "progress": {"done": sum(1 for i in items if i["done"]), "total": len(items)},
    }
    if runner is not None and row["owner_station_id"] is not None and row["status"] == "running":
        data["scale"] = runner.reading(row["owner_station_id"]).to_dict()
    return data


def list_batches(conn: sqlite3.Connection, station: int | None = None) -> list[dict]:
    """Nicht abgeschlossene Chargen (laufend, pausiert, fertig mit Behälter auf der Waage) – für Prüfseite und
    Tablet (welche Charge läuft an welcher Waage, welche warten auf „Weiter“)."""
    rows = conn.execute(
        "SELECT b.id, b.batch_no, b.status, b.owner_station_id, b.pause_reason, b.order_id, b.dough_index, "
        "       b.current_position, o.fixed_station_id, v.name AS recipe_name "
        "FROM batch b JOIN production_order o ON o.id = b.order_id "
        "LEFT JOIN recipe_version v ON v.id = b.recipe_version_id "
        "WHERE b.status IN ('running', 'paused') OR (b.status = 'done' AND b.finish_ack_at IS NULL) "
        "ORDER BY b.id").fetchall()
    result = []
    for r in rows:
        if station is not None and r["owner_station_id"] not in (None, station):
            continue
        result.append({"id": r["id"], "batch_no": r["batch_no"], "status": r["status"],
                       "owner_station": r["owner_station_id"], "fixed_station": r["fixed_station_id"],
                       "pause_reason": r["pause_reason"], "order_id": r["order_id"], "dough_index": r["dough_index"],
                       "recipe_name": r["recipe_name"], "current_position": r["current_position"]})
    return result


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def _station_of(payload) -> int:
    if not isinstance(payload, dict):
        raise ValidationError("Ungültige Anfrage.", code="invalid_request")
    return whole(payload.get("station"), "station", "die Station")


def _require_running_at(row, station: int) -> None:
    if row["status"] == "paused":
        raise ConflictError("Der Teig ist pausiert – bitte erst „Weiter“.", code="batch_paused")
    if row["status"] != "running":
        raise ConflictError("Der Teig läuft nicht mehr.", code="batch_closed")
    if row["owner_station_id"] != station:
        raise ConflictError(f"Der Teig ist in Arbeit an Waage {row['owner_station_id']}.", code="other_station")


def _open_item(conn: sqlite3.Connection, batch_id: int, payload, current) -> sqlite3.Row:
    position = whole(payload.get("position"), "position", "die Zeile", required=False)
    if position is None:
        position = current
    if position is None:
        raise ValidationError("Bitte eine Zutat wählen.", field="position", code="position_missing")
    items = {i["position"]: i for i in _item_rows(conn, batch_id)}
    item = items.get(position)
    if item is None:
        raise NotFoundError(f"Zeile {position} gibt es in diesem Teig nicht.", field="position", code="not_found")
    if item["ack_type"] is not None:
        raise ConflictError(f"Zeile {position} ist bereits erledigt.", field="position", code="item_done")
    return item


def _next_position(conn: sqlite3.Connection, batch_id: int) -> int | None:
    """Nächste offene Zutat: zuerst die nicht wartenden, sonst eine wartende Unterrezept-Zeile."""
    open_items = [i for i in _item_rows(conn, batch_id) if i["ack_type"] is None]
    for item in open_items:
        if not _blocked(item):
            return item["position"]
    return open_items[0]["position"] if open_items else None


def _event(conn, item_id: int, event_type: str, station: int, now: str, *, weight_g=None, units=None,
           tare_g=None, stable=None, note=None) -> None:
    conn.execute(
        "INSERT INTO weighing_event (batch_item_id, event_type, units, weight_g, tare_g, stable, station_id, "
        "created_at, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (item_id, event_type, units, weight_g, tare_g, None if stable is None else int(bool(stable)), station,
         now, note))


def _complete(conn: sqlite3.Connection, row, item, ack_type: str, actual_g, station: int, now: str) -> bool:
    """Zeile erledigt; danach nächste offene Zutat oder Teig fertig. Gibt zurück, ob der Teig fertig ist."""
    changed = conn.execute(
        "UPDATE batch_item SET ack_type = ?, actual_g = ?, station_id = ?, acknowledged_at = ? "
        "WHERE id = ? AND ack_type IS NULL", (ack_type, actual_g, station, now, item["id"])).rowcount
    if changed != 1:
        raise ConflictError(f"Zeile {item['position']} ist bereits erledigt.", code="item_done")
    nxt = _next_position(conn, row["id"])
    if nxt is None:
        conn.execute("UPDATE batch SET status = 'done', finished_at = ?, current_position = NULL WHERE id = ?",
                     (now, row["id"]))
        orders_mod.update_order_status(conn, row["order_id"], now)
        return True
    conn.execute("UPDATE batch SET current_position = ? WHERE id = ?", (nxt, row["id"]))
    return False


def next_batch_no(conn: sqlite3.Connection, day: str | None = None) -> str:
    """Vorläufige Chargennummer JJJJMMTT-NNN mit Tageszähler (K09-5, in Modul 11 ersetzbar)."""
    prefix = (day or date.today().isoformat()).replace("-", "")
    last = conn.execute("SELECT MAX(CAST(substr(batch_no, 10) AS INTEGER)) FROM batch WHERE batch_no LIKE ?",
                        (prefix + "-%",)).fetchone()[0]
    return f"{prefix}-{(last or 0) + 1:03d}"


# ---------------------------------------------------------------------------
# Teig starten (Abschnitt 4)
# ---------------------------------------------------------------------------

def start_dough(conn: sqlite3.Connection, order_id: int, payload, runner: ProductionRunner | None = None,
                *, now: str | None = None, today: str | None = None) -> dict:
    now = now or utc_now()
    station = station_row(conn, _station_of(payload))["id"]
    dough_index = whole(payload.get("dough_index"), "dough_index", "den Teig", required=False)
    with transaction(conn):
        order = conn.execute("SELECT * FROM production_order WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            raise NotFoundError("Auftrag nicht gefunden.", code="not_found")
        if order["status"] not in ("open", "in_progress"):
            raise ConflictError("Der Auftrag ist abgeschlossen.", code="order_closed")
        if order["dough_count"] > 1 and dough_index is None:
            raise ValidationError("Der Auftrag hat mehrere Teige – bitte den Teig angeben.", field="dough_index",
                                  code="dough_index_missing")
        dough_index = dough_index or 1
        if not 1 <= dough_index <= order["dough_count"]:
            raise ValidationError(f"Teig {dough_index} gibt es im Auftrag nicht.", field="dough_index",
                                  code="dough_index_invalid")
        if order["fixed_station_id"] is not None and order["fixed_station_id"] != station:
            raise ConflictError(f"Der Auftrag ist fest an Waage {order['fixed_station_id']}.", code="fixed_station")
        busy = station_busy(conn, station)
        if busy is not None:
            raise ConflictError(f"An Waage {station} ist noch Teig {busy['batch_no']} offen.", code="station_busy")
        if conn.execute("SELECT 1 FROM batch WHERE order_id = ? AND dough_index = ?",
                        (order_id, dough_index)).fetchone():
            raise ConflictError(f"Teig {dough_index} ist bereits gestartet.", code="dough_started")

        version_id = order["recipe_version_id"]
        if version_id is None:
            # Erster Teig: aktuelle Version für den ganzen Auftrag fixieren (R2, K6), Unterrezept-Aufträge anlegen
            recipe = conn.execute("SELECT current_version_id, archived FROM recipe WHERE id = ?",
                                  (order["recipe_id"],)).fetchone()
            if recipe["archived"]:
                raise ConflictError("Das Rezept ist archiviert.", code="recipe_archived")
            version_id = recipe["current_version_id"]
            conn.execute("UPDATE production_order SET recipe_version_id = ?, status = 'in_progress' WHERE id = ?",
                         (version_id, order_id))
            order = conn.execute("SELECT * FROM production_order WHERE id = ?", (order_id,)).fetchone()
            orders_mod.create_sub_orders(conn, order)

        rows = build_batch_items(conn, order_id, version_id, dough_index if order["dough_count"] > 1 else None)
        subs = {(r["parent_item_position"], r["parent_dough_index"]): r["id"] for r in conn.execute(
            "SELECT id, parent_item_position, parent_dough_index FROM production_order WHERE parent_order_id = ?",
            (order_id,))}
        batch_id = conn.execute(
            "INSERT INTO batch (batch_no, order_id, dough_index, recipe_version_id, status, owner_station_id, "
            "started_at) VALUES (?, ?, ?, ?, 'running', ?, ?)",
            (next_batch_no(conn, today), order_id, dough_index, version_id, station, now)).lastrowid
        for item in rows:
            if item["item_type"] == "sub_recipe":
                item = dict(item, sub_order_id=subs.get((item["position"], dough_index)) or subs.get(
                    (item["position"], None)))
            conn.execute(
                f"INSERT INTO batch_item (batch_id, {', '.join(ITEM_COLUMNS)}) "
                f"VALUES (?, {', '.join('?' * len(ITEM_COLUMNS))})", [batch_id] + [item[c] for c in ITEM_COLUMNS])
        first = _next_position(conn, batch_id)
        conn.execute("UPDATE batch SET current_position = ? WHERE id = ?", (first, batch_id))
    if runner is not None:
        runner.set_reference(station)            # Tara-Aufnahme (6.2; Waage tarieren ab C2)
    return get_batch(conn, batch_id, runner)


# ---------------------------------------------------------------------------
# Zutat wählen und quittieren (Abschnitt 5)
# ---------------------------------------------------------------------------

def select_item(conn, batch_id: int, payload, runner=None) -> dict:
    station = _station_of(payload)
    row = _batch_row(conn, batch_id)
    _require_running_at(row, station)
    item = _open_item(conn, batch_id, payload, None)
    with transaction(conn):
        conn.execute("UPDATE batch SET current_position = ? WHERE id = ? AND status = 'running'",
                     (item["position"], batch_id))
    return get_batch(conn, batch_id, runner)


def ack_weighed(conn, batch_id: int, payload, runner: ProductionRunner, *, now: str | None = None) -> dict:
    """Wiegen von Hand quittieren (Taste): nur in der Toleranz und bei gültigem Waagenwert (R4, K09-2)."""
    now = now or utc_now()
    station = _station_of(payload)
    row = _batch_row(conn, batch_id)
    _require_running_at(row, station)
    item = _open_item(conn, batch_id, payload, row["current_position"])
    kind = item_kind(item)
    if kind != "weigh":
        raise ConflictError("Diese Zutat wird nicht gewogen.", code="not_weighable", kind=kind)
    reading = runner.reading(station)
    if not reading.usable:
        raise ConflictError("Die Waage liefert keinen gültigen Wert.", code="scale_not_ok", scale=reading.to_dict())
    if reading.reference_g is None:
        raise ConflictError("Tara fehlt – bitte Tara drücken.", code="tare_missing")
    rest = reading.actual_g
    if abs(rest - item["rest_target_g"]) > item["tolerance_g"]:
        raise ConflictError(
            f"Außerhalb der Toleranz: {rest} g statt {item['rest_target_g']} g ± {item['tolerance_g']} g.",
            code="out_of_tolerance", actual_g=rest)
    ack_type = "manual_stable" if reading.stable else "manual_unstable"
    actual = rest + (item["units_target"] * item["unit_size_g"] if item["unit_size_g"] else 0)
    with transaction(conn):
        _event(conn, item["id"], "weighed", station, now, weight_g=rest, tare_g=reading.reference_g,
               stable=reading.stable)
        _complete(conn, _batch_row(conn, batch_id), item, ack_type, actual, station, now)
    runner.set_reference(station)               # nächster Nullpunkt (6.2)
    return get_batch(conn, batch_id, runner)


def ack_units(conn, batch_id: int, payload, runner=None, *, now: str | None = None) -> dict:
    """Ganze Einheiten von Hand quittieren (M09-6); Rest 0 g → Zutat fertig."""
    now = now or utc_now()
    station = _station_of(payload)
    row = _batch_row(conn, batch_id)
    _require_running_at(row, station)
    item = _open_item(conn, batch_id, payload, row["current_position"])
    if item_kind(item) != "units":
        raise ConflictError("Für diese Zutat gibt es keine ganzen Einheiten zu quittieren.", code="no_units")
    with transaction(conn):
        _event(conn, item["id"], "units_ack", station, now, units=item["units_target"])
        if item["rest_target_g"] == 0:
            _complete(conn, row, item, "hand", item["target_g"], station, now)
    if runner is not None:
        runner.set_reference(station)
    return get_batch(conn, batch_id, runner)


def ack_hand(conn, batch_id: int, payload, runner=None, *, now: str | None = None) -> dict:
    """Handzugabe quittieren: nach Bedarf (Soll 0 g, Ist leer) oder Sollhandzugabe (Ist = Soll)."""
    now = now or utc_now()
    station = _station_of(payload)
    row = _batch_row(conn, batch_id)
    _require_running_at(row, station)
    item = _open_item(conn, batch_id, payload, row["current_position"])
    kind = item_kind(item)
    if kind not in ("hand_need", "hand_target"):
        raise ConflictError("Diese Zutat ist keine Handzugabe.", code="not_hand", kind=kind)
    actual = None if kind == "hand_need" else item["target_g"]
    with transaction(conn):
        _event(conn, item["id"], "hand", station, now, weight_g=actual)
        _complete(conn, row, item, "hand", actual, station, now)
    if runner is not None:
        runner.set_reference(station)
    return get_batch(conn, batch_id, runner)


def skip_item(conn, batch_id: int, payload, runner=None, *, now: str | None = None) -> dict:
    """Zutat übergehen, nur mit Bestätigung (M09-12)."""
    now = now or utc_now()
    station = _station_of(payload)
    row = _batch_row(conn, batch_id)
    _require_running_at(row, station)
    item = _open_item(conn, batch_id, payload, row["current_position"])
    require_confirm(payload, f"Zeile {item['position']} wirklich übergehen?")
    with transaction(conn):
        _event(conn, item["id"], "skipped", station, now)
        _complete(conn, row, item, "skipped", None, station, now)
    if runner is not None:
        runner.set_reference(station)
    return get_batch(conn, batch_id, runner)


def check_sub(conn, batch_id: int, payload, runner=None, *, now: str | None = None) -> dict:
    """Unterrezept-Zeile erledigen (M09-10, K09-1): Unterrezept-Teig fertig → „Unterrezept gewogen“ mit der
    Ist-Summe; sonst abhaken mit Bestätigung, Ist = Soll."""
    now = now or utc_now()
    station = _station_of(payload)
    row = _batch_row(conn, batch_id)
    _require_running_at(row, station)
    item = _open_item(conn, batch_id, payload, row["current_position"])
    if item["item_type"] != "sub_recipe":
        raise ConflictError("Diese Zeile ist kein Unterrezept.", code="not_sub_recipe")
    sub = None if item["sub_order_id"] is None else conn.execute(
        "SELECT id, status, parent_dough_index FROM production_order WHERE id = ?", (item["sub_order_id"],)).fetchone()
    if sub is not None and sub["status"] == "done":
        ack_type, event = "sub_done", "sub_checked"
        if sub["parent_dough_index"] is None and row["dough_count"] > 1:
            actual = item["target_g"]                # „für alle“: Anteil dieses Teigs
        else:
            actual = conn.execute(
                "SELECT COALESCE(SUM(bi.actual_g), 0) FROM batch_item bi JOIN batch b ON b.id = bi.batch_id "
                "WHERE b.order_id = ? AND b.status = 'done'", (sub["id"],)).fetchone()[0]
    else:
        require_confirm(payload, "Unterrezept ist noch nicht fertig gewogen. Trotzdem abhaken (Ist = Soll)?")
        ack_type, event, actual = "sub_checked", "sub_checked", item["target_g"]
    with transaction(conn):
        _event(conn, item["id"], event, station, now, weight_g=actual,
               note="gewogen" if ack_type == "sub_done" else "abgehakt")
        _complete(conn, row, item, ack_type, actual, station, now)
    if runner is not None:
        runner.set_reference(station)
    return get_batch(conn, batch_id, runner)


def tare(conn, batch_id: int, payload, runner: ProductionRunner, *, now: str | None = None) -> dict:
    """Tara von Hand: neuer Bezug der Software (Tara an der Waage ab Teil C2)."""
    now = now or utc_now()
    station = _station_of(payload)
    row = _batch_row(conn, batch_id)
    _require_running_at(row, station)
    reference = runner.set_reference(station)
    if reference is None:
        raise ConflictError("Die Waage liefert keinen gültigen Wert.", code="scale_not_ok")
    if row["current_position"] is not None:
        item = conn.execute("SELECT id FROM batch_item WHERE batch_id = ? AND position = ?",
                            (batch_id, row["current_position"])).fetchone()
        with transaction(conn):
            _event(conn, item["id"], "tare_set", station, now, tare_g=reference, note="von Hand")
    return get_batch(conn, batch_id, runner)


# ---------------------------------------------------------------------------
# Pause, Handwaage, Weiter (Abschnitte 7 und 9)
# ---------------------------------------------------------------------------

def pause(conn, batch_id: int, payload, runner=None, *, reason: str = "manual", now: str | None = None) -> dict:
    """Pause (frei für jede Station, außer „Fest an Waage“) oder Handwaage (an der Station reserviert, K09-11)."""
    now = now or utc_now()
    station = _station_of(payload)
    row = _batch_row(conn, batch_id)
    _require_running_at(row, station)
    owner = station if reason == "hand_scale" else row["fixed_station_id"]
    with transaction(conn):
        changed = conn.execute(
            "UPDATE batch SET status = 'paused', pause_reason = ?, paused_at = ?, owner_station_id = ? "
            "WHERE id = ? AND status = 'running' AND owner_station_id = ?",
            (reason, now, owner, batch_id, station)).rowcount
        if changed != 1:
            raise ConflictError("Der Teig wurde inzwischen geändert.", code="batch_changed")
    if runner is not None:
        runner.clear(station)
    return get_batch(conn, batch_id, runner)


def resume(conn, batch_id: int, payload, runner: ProductionRunner | None = None) -> dict:
    """Weiter an dieser Station – atomar: die zweite Station bekommt „bereits übernommen“ (M09-11).
    Danach neue Tara an dieser Station (K09-4)."""
    station = station_row(conn, _station_of(payload))["id"]
    row = _batch_row(conn, batch_id)
    if row["status"] == "running":
        raise ConflictError(f"Der Teig wurde bereits an Waage {row['owner_station_id']} übernommen.",
                            code="already_resumed", owner_station=row["owner_station_id"])
    if row["status"] != "paused":
        raise ConflictError("Der Teig läuft nicht mehr.", code="batch_closed")
    if row["fixed_station_id"] is not None and row["fixed_station_id"] != station:
        raise ConflictError(f"Der Teig ist fest an Waage {row['fixed_station_id']}.", code="fixed_station")
    if row["pause_reason"] == "hand_scale" and row["owner_station_id"] != station:
        raise ConflictError(f"Pausiert – Handwaage an Waage {row['owner_station_id']}.", code="reserved")
    busy = station_busy(conn, station)
    if busy is not None and busy["id"] != batch_id:
        raise ConflictError(f"An Waage {station} ist noch Teig {busy['batch_no']} offen.", code="station_busy")
    try:
        with transaction(conn):
            changed = conn.execute(
                "UPDATE batch SET status = 'running', owner_station_id = ?, pause_reason = NULL, paused_at = NULL, "
                "pause_load_g = NULL WHERE id = ? AND status = 'paused' "
                "AND (owner_station_id IS NULL OR owner_station_id = ?)", (station, batch_id, station)).rowcount
            if changed != 1:
                raise ConflictError("Der Teig wurde bereits an einer anderen Waage übernommen.",
                                    code="already_resumed")
    except sqlite3.IntegrityError as exc:
        raise ConflictError(f"An Waage {station} läuft bereits ein Teig.", code="station_busy") from exc
    if runner is not None:
        runner.set_reference(station)
    return get_batch(conn, batch_id, runner)


def pause_running(conn: sqlite3.Connection, *, reason: str = "restart", now: str | None = None) -> int:
    """Beim Start des Add-ons: laufende Chargen → pausiert (M09-11); Besitzer frei außer „Fest an Waage“."""
    now = now or utc_now()
    with transaction(conn):
        return conn.execute(
            "UPDATE batch SET status = 'paused', pause_reason = ?, paused_at = ?, "
            "owner_station_id = (SELECT fixed_station_id FROM production_order o WHERE o.id = batch.order_id) "
            "WHERE status = 'running'", (reason, now)).rowcount


# ---------------------------------------------------------------------------
# Abbruch und Abschluss (Abschnitte 6.6 und 8)
# ---------------------------------------------------------------------------

def cancel(conn, batch_id: int, payload, runner=None, *, now: str | None = None) -> dict:
    """Abbruch mit Bestätigung; Gewogenes bleibt im Protokoll. Laufend nur an der eigenen Station."""
    now = now or utc_now()
    station = _station_of(payload)
    row = _batch_row(conn, batch_id)
    if row["status"] not in ("running", "paused"):
        raise ConflictError("Der Teig läuft nicht mehr.", code="batch_closed")
    if row["status"] == "running" and row["owner_station_id"] != station:
        raise ConflictError(f"Der Teig ist in Arbeit an Waage {row['owner_station_id']}.", code="other_station")
    require_confirm(payload, "Teig wirklich abbrechen? Bereits Gewogenes bleibt im Protokoll.")
    with transaction(conn):
        conn.execute("UPDATE batch SET status = 'cancelled', finished_at = ?, current_position = NULL "
                     "WHERE id = ?", (now, batch_id))
        orders_mod.update_order_status(conn, row["order_id"], now)
    if runner is not None and row["owner_station_id"] is not None:
        runner.clear(row["owner_station_id"])
    return get_batch(conn, batch_id, runner)


def finish(conn, batch_id: int, payload, runner=None, *, now: str | None = None) -> dict:
    """Abschließen von Hand: Station frei (K09-10). In Teil C2 schließt zusätzlich das Abnehmen ab."""
    now = now or utc_now()
    station = _station_of(payload)
    row = _batch_row(conn, batch_id)
    if row["status"] != "done":
        raise ConflictError("Der Teig ist noch nicht fertig.", code="batch_not_done")
    if row["finish_ack_at"] is not None:
        raise ConflictError("Der Teig ist bereits abgeschlossen.", code="already_finished")
    if row["owner_station_id"] != station:
        raise ConflictError(f"Der Teig steht an Waage {row['owner_station_id']}.", code="other_station")
    with transaction(conn):
        conn.execute("UPDATE batch SET finish_ack_at = ? WHERE id = ?", (now, batch_id))
    if runner is not None:
        runner.clear(station)
    return get_batch(conn, batch_id, runner)
