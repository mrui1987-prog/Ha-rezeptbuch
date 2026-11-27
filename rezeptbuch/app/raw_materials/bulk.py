"""Sammelaktionen der Rohstoffliste (Modul 03, Rohstoffverwaltung M03-21, docs/rohstoffverwaltung.md 5).

Ablauf wie bei den Rezepten (C3-E1): ``preview`` rechnet alles in einer Transaktion und rollt zurück,
danach Ausführen mit ``confirm``. Jeder Rohstoff läuft in einem eigenen Sicherungspunkt; was nicht
erlaubt ist, wird übersprungen und mit Grund genannt, die übrigen werden ausgeführt (nicht „alles oder
nichts“). Es gelten dieselben Regeln wie beim einzelnen Rohstoff, weil die vorhandenen ``*_in_tx``-
Funktionen benutzt werden (Änderungsprotokoll und Bestandsbuchungen inklusive).

Aktionen: ``archive``, ``restore``, ``tolerance``, ``type``, ``alert``, ``stock`` (``end``/``zero``),
``active_source`` (M04-6). Der Export der Auswahl läuft über ``GET …/export.csv?ids=…``.
"""

from __future__ import annotations

import sqlite3

from ..db import transaction
from ..errors import ConflictError, ServiceError, ValidationError
from . import service, sources, stock
from .models import tolerance_display

MAX_BULK = 1000
ACTIONS = ("archive", "restore", "tolerance", "type", "alert", "stock", "active_source")
TYPE_TEXT = {"standard": "Standard", "flour": "Mehl", "aid": "Hilfs- und Betriebsstoff", "goods": "Handelsware"}
NOTE = "Sammelaktion"


def _tol_text(unit: str, value: int) -> str:
    shown = tolerance_display(unit, value)
    if unit == "percent":
        return f"{shown:.1f}".replace(".", ",") + " %"
    return "0 g (Handzugabe)" if shown == 0 else f"{shown} g"


def _kg(grams) -> str:
    return "–" if grams is None else stock.kg_text(grams) + " kg"


def _row(conn, rm_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT id, number, name, archived, type, tolerance_unit, tolerance_value, stock_g, "
                       "stock_alert_g FROM raw_material WHERE id = ?", (rm_id,)).fetchone()
    if row is None:
        raise ValidationError("Rohstoff nicht gefunden.", code="not_found")
    return row


def _one(conn, action: str, rm_id: int, data: dict, stock_zero_ids: set[int]) -> tuple[str, str]:
    """Führt die Aktion für einen Rohstoff aus (offene Transaktion). → (Status, Text)."""
    row = _row(conn, rm_id)
    if action == "archive":
        if row["archived"]:
            return "unchanged", "schon archiviert"
        zero = rm_id in stock_zero_ids and row["stock_g"] not in (None, 0)
        service.archive_in_tx(conn, rm_id, stock_zero=zero)
        return "changed", "wird archiviert" + (f", Bestand {_kg(row['stock_g'])} → 0" if zero else "")
    if action == "restore":
        if not row["archived"]:
            return "unchanged", "ist aktiv"
        service.restore_in_tx(conn, rm_id)
        return "changed", "wird wiederhergestellt"
    if action == "tolerance":
        changes = service.update_in_tx(conn, rm_id, {"tolerance": data.get("tolerance"),
                                                     "tolerance_unit": data.get("tolerance_unit")})
        new = _row(conn, rm_id)
        if not changes:
            return "unchanged", _tol_text(row["tolerance_unit"], row["tolerance_value"])
        return "changed", (_tol_text(row["tolerance_unit"], row["tolerance_value"]) + " → "
                           + _tol_text(new["tolerance_unit"], new["tolerance_value"]))
    if action == "type":
        changes = service.update_in_tx(conn, rm_id, {"type": data.get("type")}, confirm_type_change=True)
        if not changes:
            return "unchanged", TYPE_TEXT.get(row["type"], row["type"])
        use = service.usage(conn, rm_id)["recipes"]
        text = TYPE_TEXT[row["type"]] + " → " + TYPE_TEXT[data["type"]]
        if use:
            text += f" – betrifft {use} Rezept{'e' if use != 1 else ''} („Mehl gesamt“ ändert sich)"
        return "changed", text
    if action == "alert":
        changes = service.update_in_tx(conn, rm_id, {"stock_alert_kg": data.get("value")})
        new = _row(conn, rm_id)
        if not changes:
            return "unchanged", "Meldewert " + _kg(row["stock_alert_g"])
        return "changed", "Meldewert " + _kg(row["stock_alert_g"]) + " → " + _kg(new["stock_alert_g"])
    if action == "stock":
        if row["stock_g"] is None:
            return "unchanged", "keine Bestandsführung"
        if data.get("mode") == "end":
            stock.inventory_in_tx(conn, rm_id, None, note=NOTE)
            return "changed", f"Bestand {_kg(row['stock_g'])} → Führung beendet"
        if row["stock_g"] == 0:
            return "unchanged", "Bestand 0 kg"
        stock.inventory_in_tx(conn, rm_id, 0, note=NOTE)
        return "changed", f"Bestand {_kg(row['stock_g'])} → 0 kg"
    # active_source
    res = sources.bulk_active_source_in_tx(conn, [rm_id], data.get("dealer_id"))[0]
    if res["action"] == "unchanged":
        return "unchanged", f"„{res['new_dealer']}“ ist schon aktiv"
    text = ("Bezugsquelle neu, aktiv" if res["action"] == "created" else "wird aktiv") + f": „{res['new_dealer']}“"
    if res["price_changes"]:
        text += (" – Preis " + sources.price_text(res["old_price_cents_per_kg"]) + " → "
                 + sources.price_text(res["new_price_cents_per_kg"]) + " je kg")
    return "changed", text


def _check(data: dict) -> tuple[str, list[int], dict]:
    action = data.get("action")
    if action not in ACTIONS:
        raise ValidationError("Unbekannte Sammelaktion.", field="action")
    ids = data.get("ids")
    if (not isinstance(ids, list) or not ids
            or any(isinstance(i, bool) or not isinstance(i, int) for i in ids)):
        raise ValidationError("Bitte mindestens einen Rohstoff wählen.", field="ids")
    ids = list(dict.fromkeys(ids))
    if len(ids) > MAX_BULK:
        raise ValidationError(f"Höchstens {MAX_BULK} Rohstoffe auf einmal.", field="ids")
    value = data.get("value") if isinstance(data.get("value"), dict) else {}
    if action == "type" and value.get("type") not in ("standard", "flour"):
        raise ValidationError("Bitte den Typ wählen.", field="type")
    if action == "tolerance" and (value.get("tolerance") in (None, "") or value.get("tolerance_unit") not in ("g", "percent")):
        raise ValidationError("Bitte Toleranz und Einheit angeben.", field="tolerance")
    if action == "stock" and value.get("mode") not in ("end", "zero"):
        raise ValidationError("Bitte wählen: Führung beenden oder auf 0 setzen.", field="mode")
    if action == "active_source" and (isinstance(value.get("dealer_id"), bool) or not isinstance(value.get("dealer_id"), int)):
        raise ValidationError("Bitte einen Händler wählen.", field="dealer_id")
    if action == "alert" and "value" not in value:
        raise ValidationError("Bitte einen Meldewert angeben (leer = löschen).", field="value")
    return action, ids, value


def run(conn: sqlite3.Connection, data: dict) -> dict:
    """Sammelaktion: ``{action, ids, value?, preview?, confirm?, stock_zero_ids?}``."""
    action, ids, value = _check(data)
    preview = data.get("preview") is True
    if not preview and data.get("confirm") is not True:
        raise ConflictError("Bitte die Sammelaktion bestätigen.", code="confirmation_required")
    zero_ids = data.get("stock_zero_ids") if isinstance(data.get("stock_zero_ids"), list) else []
    stock_zero_ids = {i for i in zero_ids if isinstance(i, int) and not isinstance(i, bool)}

    class _Rollback(Exception):
        pass

    items: list[dict] = []
    try:
        with transaction(conn):
            for rm_id in ids:
                before = conn.execute("SELECT number, name, archived, stock_g FROM raw_material WHERE id = ?",
                                      (rm_id,)).fetchone()
                item = {"raw_material_id": rm_id, "number": before["number"] if before else None,
                        "name": before["name"] if before else None,
                        "archived": bool(before["archived"]) if before else None,
                        "stock_g": before["stock_g"] if before else None}
                conn.execute("SAVEPOINT bulk_item")
                try:
                    item["status"], item["detail"] = _one(conn, action, rm_id, value, stock_zero_ids)
                    conn.execute("RELEASE bulk_item")
                except (ServiceError, sqlite3.IntegrityError) as exc:
                    conn.execute("ROLLBACK TO bulk_item")
                    conn.execute("RELEASE bulk_item")
                    item["status"] = "skipped"
                    item["detail"] = exc.message if isinstance(exc, ServiceError) else "nicht möglich (Datenbankregel)"
                items.append(item)
            if preview:
                raise _Rollback
    except _Rollback:
        pass
    counts = {k: sum(1 for i in items if i["status"] == k) for k in ("changed", "unchanged", "skipped")}
    return {"action": action, "preview": preview, "items": items, **counts}
