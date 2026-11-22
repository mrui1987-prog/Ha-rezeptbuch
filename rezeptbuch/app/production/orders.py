"""Aufträge (Modul 09, docs/ablauf.md Abschnitte 3, 4 und 11; M09-9, M09-10, K09-6).

Ein Auftrag wird mit derselben Eingabe angelegt wie die Berechnung (``POST /api/v1/calculation``,
Modul 06) plus ``fixed_station`` („Fest an Waage“) und ``planned_date``. Gespeichert werden die
Spalten von ``production_order`` und die Nebentabellen; vor dem Speichern prüft ``validate_basis``
(Befund B4) alles noch einmal. Die Rezeptversion wird erst beim Start des ersten Teigs fixiert (R2).
"""

from __future__ import annotations

import json
import sqlite3

from ..calculation.models import validate_request
from ..calculation.service import calculate, sub_order_targets, validate_basis
from ..db import transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from .common import check_date, local_today, require_confirm, station_row

ORDER_ONLY = ("fixed_station", "planned_date")
EXTRA_COLUMNS = ("surcharge_tenths", "surcharge_g", "carryover_of_order_id")


def _recipe_row(conn: sqlite3.Connection, recipe_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT r.id, r.number, r.locked, r.archived, r.current_version_id, v.name "
        "FROM recipe r LEFT JOIN recipe_version v ON v.id = r.current_version_id WHERE r.id = ?",
        (recipe_id,)).fetchone()
    if row is None:
        raise NotFoundError("Rezept nicht gefunden.", field="recipe_id", code="not_found")
    return row


def create_order(conn: sqlite3.Connection, payload) -> dict:
    """Legt einen Auftrag an (Vorwahl). Antwort wie ``get_order``."""
    prepared = prepare_order(conn, payload)
    with transaction(conn):
        order_id = insert_order_in_tx(conn, prepared)
    return get_order(conn, order_id)


def prepare_order(conn: sqlite3.Connection, payload) -> dict:
    """Prüft und berechnet einen Auftrag, ohne zu schreiben (auch für den Planer, docs/planer.md 9).

    Ergebnis für ``insert_order_in_tx``. ``payload`` wie ``POST /orders``; der Planer gibt zusätzlich
    ``surcharge_tenths``/``surcharge_g``/``carryover_of_order_id`` (nur Anzeige) über ``insert_order_in_tx`` mit.
    """
    if not isinstance(payload, dict):
        raise ValidationError("Ungültige Anfrage.", code="invalid_request")
    if payload.get("version_no") not in (None, ""):
        raise ValidationError("Ein Auftrag nutzt immer die aktuelle Rezeptversion.", field="version_no",
                              code="version_not_allowed")
    calc_payload = {k: v for k, v in payload.items() if k not in ORDER_ONLY}
    req = validate_request(calc_payload)
    recipe = _recipe_row(conn, req.recipe_id)
    if recipe["archived"]:
        raise ConflictError("Das Rezept ist archiviert.", field="recipe_id", code="recipe_archived")
    if recipe["locked"]:
        raise ConflictError("Das Rezept ist gesperrt und nicht für die Produktion freigegeben.",
                            field="recipe_id", code="recipe_locked")
    fixed = None
    if payload.get("fixed_station") not in (None, ""):
        fixed = station_row(conn, payload["fixed_station"])["id"]
    planned_date = check_date(payload.get("planned_date")) or local_today()

    result = calculate(conn, req)
    split = result["split"]
    if split["needs_question"] and req.split is None:
        raise ConflictError(
            f"Der Teig liegt über der Obergrenze von {split['limit_g']} g. Nach Obergrenze teilen?",
            field="split", code="split_question", min_count=split["min_count"])
    doughs = [d["target_g"] for d in result["doughs"]]
    count = len(doughs)
    basis = result["basis"]
    bt = req.basis_type

    if bt in ("total", "flour_total", "raw_material"):
        value = req.value_g
    elif bt == "pieces":
        value = sum(p["weight_g"] * p["count"] for p in basis["pieces"])
    elif bt == "batch_size":
        value = basis["batch_size"]["weight_g"]
    else:
        value = result["demand"]["target_g"]
    unit = req.input_unit or "g"
    if bt == "batch_size" and not req.input_unit:
        unit = "pcs" if basis["batch_size"]["kind"] == "pieces" else "g"
    if bt in ("combined", "factor"):
        unit = "g"

    order = {
        "basis_type": bt, "basis_value": value, "basis_input_unit": unit,
        "basis_raw_material_id": req.raw_material_id if bt == "raw_material" else None,
        "basis_item_position": req.item_position if bt == "raw_material" else None,
        "batch_size_id": req.batch_size_id if bt == "batch_size" else None,
        "total_part_g": value if bt == "total" else (req.total_part_g if bt == "combined" else None),
        "factor_hundredths": req.factor_hundredths if bt in ("factor", "combined") else None,
        "limit_g": split["limit_g"], "limit_source": split["limit_source"],
        "split_mode": split["mode"] if count > 1 else None,
        "dough_count": count,
        "pieces": [{"piece_weight_id": pid, "count": c} for pid, c in req.pieces],
        "batch_sizes": [{"batch_size_id": sid, "count": c} for sid, c in req.batch_sizes],
        "doughs": doughs,
        "overrides": dict(req.overrides),
    }
    validate_basis(conn, req.recipe_id, order)          # zweite Sicherung (Befund B4)
    return {"req": req, "order": order, "basis": basis, "doughs": doughs, "count": count, "value": value,
            "unit": unit, "fixed": fixed, "planned_date": planned_date}


def insert_order_in_tx(conn: sqlite3.Connection, prepared: dict, *, extra: dict | None = None) -> int:
    """Schreibt einen mit ``prepare_order`` geprüften Auftrag (innerhalb einer Transaktion); gibt die ID zurück.

    ``extra``: zusätzliche Spalten von ``production_order`` (Planer: Zuschlag, Übertrag – nur Anzeige).
    """
    req, order, basis, doughs = prepared["req"], prepared["order"], prepared["basis"], prepared["doughs"]
    count, value, unit, fixed = prepared["count"], prepared["value"], prepared["unit"], prepared["fixed"]
    planned_date, bt = prepared["planned_date"], req.basis_type
    extra = {k: v for k, v in (extra or {}).items() if k in EXTRA_COLUMNS}
    columns = ("recipe_id", "basis_type", "basis_value", "basis_input_unit", "basis_raw_material_id",
               "basis_item_position", "batch_size_id", "total_part_g", "factor_hundredths", "limit_g",
               "limit_source", "split_mode", "dough_count", "fixed_station_id", "planned_date",
               "list_position", "sub_modes")
    position = conn.execute(
        "SELECT COALESCE(MAX(list_position), 0) + 1 FROM production_order WHERE planned_date = ?",
        (planned_date,)).fetchone()[0]
    values = (req.recipe_id, bt, value, unit, order["basis_raw_material_id"], order["basis_item_position"],
              order["batch_size_id"], order["total_part_g"], order["factor_hundredths"], order["limit_g"],
              order["limit_source"], order["split_mode"], count, fixed, planned_date, position,
              json.dumps({str(k): v for k, v in req.sub_modes.items()}) if req.sub_modes else None)
    columns = columns + tuple(extra)
    values = values + tuple(extra.values())
    order_id = conn.execute(
        f"INSERT INTO production_order ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
        values).lastrowid
    for p in basis.get("pieces") or []:
        conn.execute("INSERT INTO order_piece (order_id, piece_weight_id, label, weight_g, piece_count) "
                     "VALUES (?, ?, ?, ?, ?)", (order_id, p["piece_weight_id"], p["label"], p["weight_g"],
                                                p["count"]))
    for size in basis.get("batch_sizes") or []:
        conn.execute(
            "INSERT INTO order_batch_size (order_id, batch_size_id, label, kind, value, piece_weight_g, "
            "batch_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (order_id, size["id"], size["label"], size["kind"], size["value"],
             size["piece_weight_g"] if size["kind"] == "pieces" else None, size["count"]))
    for index, target in enumerate(doughs, start=1):
        conn.execute("INSERT INTO order_dough (order_id, dough_index, target_g) VALUES (?, ?, ?)",
                     (order_id, index, target))
    for pos, amount in req.overrides.items():
        conn.execute("INSERT INTO order_item_override (order_id, item_position, amount_g) VALUES (?, ?, ?)",
                     (order_id, pos, amount))
    return order_id


def create_sub_orders(conn: sqlite3.Connection, order: sqlite3.Row) -> list[int]:
    """Unterrezept-Aufträge beim Start des ersten Teigs (M09-10, R06-44 bis R06-49).

    Läuft innerhalb der Start-Transaktion, nachdem die Version fixiert ist. Menge = Gesamtteig
    des Unterrezepts (gerundete Zeilenmenge, R06-5).
    """
    modes = {int(k): v for k, v in json.loads(order["sub_modes"]).items()} if order["sub_modes"] else {}
    created = []
    for target in sub_order_targets(conn, order["id"], modes):
        sub_id = conn.execute(
            "INSERT INTO production_order (recipe_id, parent_order_id, parent_item_position, parent_dough_index, "
            "basis_type, basis_value, basis_input_unit, total_part_g, dough_count, planned_date, list_position) "
            "VALUES (?, ?, ?, ?, 'total', ?, 'g', ?, 1, ?, ?)",
            (target["sub_recipe_id"], order["id"], target["position"], target["dough_index"], target["target_g"],
             target["target_g"], order["planned_date"], order["list_position"])).lastrowid
        conn.execute("INSERT INTO order_dough (order_id, dough_index, target_g) VALUES (?, 1, ?)",
                     (sub_id, target["target_g"]))
        created.append(sub_id)
    return created


def _batches_by_order(conn: sqlite3.Connection, order_ids: list[int]) -> dict[int, dict[int, dict]]:
    if not order_ids:
        return {}
    rows = conn.execute(
        f"SELECT id, order_id, dough_index, batch_no, status, owner_station_id, pause_reason, finish_ack_at "
        f"FROM batch WHERE order_id IN ({', '.join('?' * len(order_ids))})", order_ids)
    result: dict[int, dict[int, dict]] = {}
    for r in rows:
        result.setdefault(r["order_id"], {})[r["dough_index"]] = {
            "id": r["id"], "batch_no": r["batch_no"], "status": r["status"],
            "owner_station": r["owner_station_id"], "pause_reason": r["pause_reason"],
            "finish_ack_at": r["finish_ack_at"]}
    return result


_ORDER_SELECT = (
    "SELECT o.*, r.number AS recipe_number, COALESCE(fv.name, cv.name) AS recipe_name, fv.version_no AS version_no "
    "FROM production_order o JOIN recipe r ON r.id = o.recipe_id "
    "LEFT JOIN recipe_version cv ON cv.id = r.current_version_id "
    "LEFT JOIN recipe_version fv ON fv.id = o.recipe_version_id ")


def _order_dict(conn: sqlite3.Connection, row: sqlite3.Row, batches: dict[int, dict]) -> dict:
    targets = {r["dough_index"]: r["target_g"] for r in conn.execute(
        "SELECT dough_index, target_g FROM order_dough WHERE order_id = ?", (row["id"],))}
    doughs = [{"dough_index": i, "target_g": targets.get(i), "batch": batches.get(i)}
              for i in range(1, row["dough_count"] + 1)]
    parent = None
    if row["parent_order_id"] is not None:
        parent = {"order_id": row["parent_order_id"], "position": row["parent_item_position"],
                  "dough_index": row["parent_dough_index"]}
    return {
        "id": row["id"],
        "recipe": {"id": row["recipe_id"], "number": row["recipe_number"], "name": row["recipe_name"],
                   "version_no": row["version_no"]},
        "status": row["status"],
        "planned_date": row["planned_date"],
        "list_position": row["list_position"],
        "basis_type": row["basis_type"],
        "basis_value": row["basis_value"],
        "dough_count": row["dough_count"],
        "target_g": sum(t for t in targets.values()) if targets else None,
        "fixed_station": row["fixed_station_id"],
        "parent": parent,
        "doughs": doughs,
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


def get_order(conn: sqlite3.Connection, order_id: int) -> dict:
    row = conn.execute(_ORDER_SELECT + "WHERE o.id = ?", (order_id,)).fetchone()
    if row is None:
        raise NotFoundError("Auftrag nicht gefunden.", code="not_found")
    batches = _batches_by_order(conn, [order_id])
    data = _order_dict(conn, row, batches.get(order_id, {}))
    children = conn.execute(_ORDER_SELECT + "WHERE o.parent_order_id = ? ORDER BY o.parent_item_position, "
                            "o.parent_dough_index", (order_id,)).fetchall()
    child_batches = _batches_by_order(conn, [c["id"] for c in children])
    data["sub_orders"] = [_order_dict(conn, c, child_batches.get(c["id"], {})) for c in children]
    return data


def list_orders(conn: sqlite3.Connection, planned_date: str | None = None) -> dict:
    """Produktionsliste eines Tages (Vorgabe heute): offen, in Arbeit, fertig, abgebrochen."""
    day = check_date(planned_date, "date") or local_today()
    rows = conn.execute(_ORDER_SELECT + "WHERE o.planned_date = ? "
                        "ORDER BY o.list_position, o.parent_order_id IS NOT NULL, o.id", (day,)).fetchall()
    batches = _batches_by_order(conn, [r["id"] for r in rows])
    return {"date": day, "orders": [_order_dict(conn, r, batches.get(r["id"], {})) for r in rows]}


def delete_order(conn: sqlite3.Connection, order_id: int, payload) -> None:
    """Nur offene Aufträge ohne gestarteten Teig, mit Bestätigung (K09-6)."""
    row = conn.execute("SELECT status FROM production_order WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise NotFoundError("Auftrag nicht gefunden.", code="not_found")
    if row["status"] != "open" or conn.execute("SELECT 1 FROM batch WHERE order_id = ?", (order_id,)).fetchone():
        raise ConflictError("Nur offene Aufträge ohne gestarteten Teig können gelöscht werden.", code="order_started")
    if conn.execute("SELECT 1 FROM production_order WHERE parent_order_id = ?", (order_id,)).fetchone():
        raise ConflictError("Der Auftrag hat Unterrezept-Aufträge.", code="order_has_sub_orders")
    require_confirm(payload, "Auftrag wirklich löschen?")
    with transaction(conn):
        conn.execute("DELETE FROM production_order WHERE id = ?", (order_id,))


def update_order_status(conn: sqlite3.Connection, order_id: int, now: str) -> str:
    """Auftrag fertig, sobald jeder Teig fertig oder abgebrochen ist (Abschnitt 8)."""
    order = conn.execute("SELECT status, dough_count FROM production_order WHERE id = ?", (order_id,)).fetchone()
    if order["status"] in ("done", "cancelled"):
        return order["status"]
    states = [r["status"] for r in conn.execute("SELECT status FROM batch WHERE order_id = ?", (order_id,))]
    if len(states) < order["dough_count"] or any(s not in ("done", "cancelled") for s in states):
        return order["status"]
    status = "done" if "done" in states else "cancelled"
    conn.execute("UPDATE production_order SET status = ?, finished_at = ? WHERE id = ?", (status, now, order_id))
    return status
