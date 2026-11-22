"""Rohstoffbestand und Meldewert (Modul 03, Ergänzung VC03-b, docs/bestand.md).

Bestand und Meldewert stehen in ``raw_material.stock_g`` / ``stock_alert_g`` (Gramm). Bestand leer =
keine Bestandsführung (B2), negativ erlaubt (B3). Jede Buchung landet in ``stock_movement``.
Funktionen mit ``_in_tx`` erwarten eine offene Transaktion (Abzug beim Quittieren in Modul 09).
"""

from __future__ import annotations

import re
import sqlite3
from decimal import Decimal, InvalidOperation

from ..db import transaction
from ..errors import ConflictError, NotFoundError, ValidationError

MAX_KG = Decimal("1000000")          # Plausibilitätsgrenze je Eingabe (1 000 t)
KIND_TEXT = {"receipt": "Zugang", "inventory": "Bestand gesetzt", "consumption": "Verwiegung",
             "reversal": "Rückbuchung", "planner": "Planer", "planner_return": "Planer zurück",
             "loss": "Abgang", "return": "Rückgabe", "correction": "Korrektur", "undo": "Rückgängig"}
# Abgangsgründe (K03-54, docs/strichcode.md 7)
# M03-27 (22.11.2026): „Bruch“ und „Verderb“ zusammengefasst; alte Buchungen mit „spoilage“ zeigen denselben Text
REASONS = {"breakage": "Bruch/Verderb", "own_use": "Eigenverbrauch", "merchandise": "Handelsware",
           "other": "Sonstiges"}
SCAN = "scan"                    # Quelle der Scan-Buchungen (docs/strichcode.md 8)
UNDO_MINUTES = 10                # Rückgängig nur eigene Scans der letzten 10 Minuten (docs/strichcode.md 3)
MAX_PACKS = 999

_NUMBER = re.compile(r"^[+-]?\d+([.,]\d+)?$")


# -- Eingabe und Anzeige -------------------------------------------------------------

def parse_kg(value, field: str, *, allow_empty: bool, allow_negative: bool = True) -> int | None:
    """kg-Text (Komma oder Punkt, höchstens 3 Nachkommastellen, B1) → ganze Gramm; leer → None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_empty:
            return None
        raise ValidationError("Bitte eine Menge in kg eingeben.", field=field)
    if isinstance(value, bool):
        raise ValidationError("Ungültige Menge.", field=field)
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if "," in text and "." in text:            # 1.234,5 → 1234,5
        text = text.replace(".", "")
    if not _NUMBER.match(text):
        raise ValidationError("Menge in kg als Zahl eingeben, z. B. 12,5.", field=field)
    text = text.replace(",", ".")
    if "." in text and len(text.split(".")[1]) > 3:
        raise ValidationError("Höchstens 3 Nachkommastellen (ganze Gramm).", field=field)
    try:
        kg = Decimal(text)
    except InvalidOperation:
        raise ValidationError("Ungültige Menge.", field=field) from None
    if abs(kg) > MAX_KG:
        raise ValidationError("Die Menge ist zu groß.", field=field)
    if kg < 0 and not allow_negative:
        raise ValidationError("Die Menge darf nicht negativ sein.", field=field)
    return int(kg * 1000)


def kg_text(grams: int | None) -> str:
    """Gramm → „12,5“ (kg, bis 3 Nachkommastellen, Komma); leer → ''."""
    if grams is None:
        return ""
    text = f"{Decimal(grams) / 1000:.3f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def status(stock_g: int | None, alert_g: int | None, need_g: int = 0) -> str | None:
    """``short`` (Bestand < Bedarf), ``alert`` (nach Abzug ≤ Meldewert, B6) oder None (keine Führung/ok)."""
    if stock_g is None:
        return None
    if need_g > 0 and stock_g < need_g:
        return "short"
    if alert_g is not None and stock_g - need_g <= alert_g:
        return "alert"
    return None


# -- Buchungen -----------------------------------------------------------------------

def _row(conn: sqlite3.Connection, raw_material_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT id, name, type, stock_g, stock_alert_g, archived, unit_size_g, unit_label, "
                       "delivery_pack_g, delivery_pack_label FROM raw_material WHERE id = ?",
                       (raw_material_id,)).fetchone()
    if row is None:
        raise NotFoundError("Rohstoff nicht gefunden.", code="not_found")
    return row


def _book(conn, raw_material_id: int, kind: str, before: int | None, after: int | None, *, source: str,
          note: str | None = None, batch_id=None, batch_item_id=None, station=None, reason=None,
          purchase_id=None, device_id=None, undo_of_id=None) -> int:
    delta = None if before is None or after is None else after - before
    if kind in ("receipt", "consumption", "reversal", "correction") and before is None and after is not None:
        delta = after                               # erste Buchung schaltet die Führung ein
    conn.execute("UPDATE raw_material SET stock_g = ? WHERE id = ?", (after, raw_material_id))
    cur = conn.execute(
        "INSERT INTO stock_movement (raw_material_id, kind, delta_g, stock_after_g, batch_id, batch_item_id, "
        "station_id, source, note, reason, purchase_id, device_id, undo_of_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (raw_material_id, kind, delta, after, batch_id, batch_item_id, station, source, note, reason,
         purchase_id, device_id, undo_of_id))
    return cur.lastrowid


def _note(note) -> str | None:
    if note is None:
        return None
    text = str(note).strip()
    if len(text) > 200:
        raise ValidationError("Notiz höchstens 200 Zeichen.", field="note")
    return text or None


def receipt_in_tx(conn, raw_material_id: int, grams: int, *, note=None, station=None, source="admin") -> None:
    row = _row(conn, raw_material_id)
    before = row["stock_g"]
    _book(conn, raw_material_id, "receipt", before, (before or 0) + grams, source=source, note=_note(note),
          station=station)


def inventory_in_tx(conn, raw_material_id: int, grams: int | None, *, note=None, source="admin") -> bool:
    """Bestand setzen (Inventur); ``None`` beendet die Bestandsführung (B2). Gibt zurück, ob gebucht wurde."""
    row = _row(conn, raw_material_id)
    if row["stock_g"] is None and grams is None:
        return False
    _book(conn, raw_material_id, "inventory", row["stock_g"], grams, source=source, note=_note(note))
    return True


def consume_in_tx(conn, raw_material_id: int | None, grams: int | None, *, batch_id: int, batch_item_id: int,
                  station: int | None) -> None:
    """Abzug beim Quittieren (B4); ohne Bestandsführung oder ohne Menge nichts."""
    if raw_material_id is None or not grams:
        return
    row = _row(conn, raw_material_id)
    if row["stock_g"] is None:
        return
    _book(conn, raw_material_id, "consumption", row["stock_g"], row["stock_g"] - grams, source="production",
          batch_id=batch_id, batch_item_id=batch_item_id, station=station)


def consumed(conn, batch_id: int) -> list[dict]:
    """Noch nicht zurückgebuchte Abzüge einer Charge je Zutat."""
    rows = conn.execute(
        "SELECT m.batch_item_id, m.raw_material_id, rm.name, SUM(-m.delta_g) AS grams FROM stock_movement m "
        "JOIN raw_material rm ON rm.id = m.raw_material_id WHERE m.batch_id = ? "
        "AND m.kind IN ('consumption', 'reversal') GROUP BY m.batch_item_id, m.raw_material_id "
        "HAVING SUM(-m.delta_g) <> 0 ORDER BY m.batch_item_id", (batch_id,)).fetchall()
    return [dict(r) for r in rows]


def reverse_batch_in_tx(conn, batch_id: int, *, station: int | None) -> int:
    """Rückbuchung aller Abzüge einer Charge (B5). Rohstoffe ohne Führung bleiben ohne. Gibt die Anzahl zurück."""
    done = 0
    for item in consumed(conn, batch_id):
        row = _row(conn, item["raw_material_id"])
        if row["stock_g"] is None:
            continue
        _book(conn, item["raw_material_id"], "reversal", row["stock_g"], row["stock_g"] + item["grams"],
              source="production", batch_id=batch_id, batch_item_id=item["batch_item_id"], station=station,
              note="Teig abgebrochen")
        done += 1
    return done


def zero_in_tx(conn, raw_material_id: int, *, note: str, source: str = "admin") -> bool:
    """„Bestand auf Null setzen?“ beim Archivieren und Austauschen (B9): Inventur auf 0, nur bei Führung."""
    row = _row(conn, raw_material_id)
    if row["stock_g"] is None or row["stock_g"] == 0:
        return False
    return inventory_in_tx(conn, raw_material_id, 0, note=note, source=source)


# -- Öffentliche Funktionen mit eigener Transaktion ---------------------------------

QUICK_ENTRY = "quick_entry"      # Quelle der Schnellerfassung (VC03-d, docs/rohstoffverwaltung.md 6.1)


def _quick(payload: dict) -> bool:
    return payload.get("source") == QUICK_ENTRY


def receipt(conn, raw_material_id: int, payload: dict) -> None:
    grams = parse_kg(payload.get("amount_kg"), "amount_kg", allow_empty=False, allow_negative=False)
    if grams == 0:
        raise ValidationError("Bitte eine Menge größer 0 eingeben.", field="amount_kg")
    station = payload.get("station")
    if station is not None and (isinstance(station, bool) or not isinstance(station, int)):
        raise ValidationError("Ungültige Station.", field="station")
    source = "station" if station is not None else (QUICK_ENTRY if _quick(payload) else "admin")
    with transaction(conn):
        if station is not None and not conn.execute("SELECT 1 FROM station WHERE id = ?", (station,)).fetchone():
            raise ValidationError("Station unbekannt.", field="station")
        receipt_in_tx(conn, raw_material_id, grams, note=payload.get("note"), station=station, source=source)


def inventory(conn, raw_material_id: int, payload: dict) -> int | None:
    """Bestand setzen; mit ``packs`` (+ ``rest_kg``) als „3 Sack + 12,5 kg“ (O-5). Gibt die Buchungs-ID zurück."""
    source = SCAN if payload.get("source") == SCAN else (QUICK_ENTRY if _quick(payload) else "admin")
    device = _device(payload.get("device_id"), required=False)
    with transaction(conn):
        if "packs" in payload:
            row = _row(conn, raw_material_id)
            pack_g, _ = pack_of(row)
            packs = _packs(payload.get("packs"), allow_zero=True)
            if packs and pack_g is None:
                raise ConflictError("Für diesen Rohstoff ist kein Gebinde hinterlegt.", code="pack_missing")
            rest = parse_kg(payload.get("rest_kg"), "rest_kg", allow_empty=True, allow_negative=False) or 0
            grams = packs * (pack_g or 0) + rest
        else:
            if "stock_kg" not in payload:
                raise ValidationError("Bitte den Bestand angeben (leer = Bestandsführung beenden).",
                                      field="stock_kg")
            grams = parse_kg(payload.get("stock_kg"), "stock_kg", allow_empty=True)
        row = _row(conn, raw_material_id)
        if row["stock_g"] is None and grams is None:
            return None
        return _book(conn, raw_material_id, "inventory", row["stock_g"], grams, source=source,
                     note=_note(payload.get("note")), device_id=device)


# -- Scanner (docs/strichcode.md, Teil S1) ---------------------------------------------

def pack_of(row) -> tuple[int | None, str | None]:
    """Gebinde für Scan-Buchungen: Liefergebinde (F-1), sonst Gebinde am Rohstoff (K03-51)."""
    if row["delivery_pack_g"] is not None:
        return row["delivery_pack_g"], row["delivery_pack_label"]
    return row["unit_size_g"], row["unit_label"]


def _packs(value, *, allow_zero: bool = False) -> int:
    if value is None or value == "":
        value = 1 if not allow_zero else 0
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        else:
            raise ValidationError("Anzahl Gebinde als ganze Zahl.", field="packs")
    if value < (0 if allow_zero else 1) or value > MAX_PACKS:
        raise ValidationError(f"Anzahl Gebinde zwischen {0 if allow_zero else 1} und {MAX_PACKS}.", field="packs")
    return value


def _device(value, *, required: bool = True) -> str | None:
    if value is None or value == "":
        if required:
            raise ValidationError("Gerät fehlt.", field="device_id")
        return None
    if not isinstance(value, str) or len(value) > 64 or not value.strip():
        raise ValidationError("Ungültiges Gerät.", field="device_id")
    return value.strip()


def _reason(payload: dict) -> str:
    reason = payload.get("reason")
    if reason == "spoilage":                      # alter Wert (0.10.21) → zusammengefasst (M03-27)
        reason = "breakage"
    if reason not in REASONS:
        raise ValidationError("Bitte einen Grund wählen (Bruch/Verderb, Eigenverbrauch, Handelsware, Sonstiges).",
                              field="reason")
    return reason


def _bookable(row) -> None:
    if row["archived"]:
        raise ConflictError(f"„{row['name']}“ ist archiviert – keine Buchung.", code="archived")


def scan_book(conn, raw_material_id: int, payload: dict, *, mode: str) -> dict:
    """Scan-Buchung je Gebinde: ``receipt`` (+1 Einkauf, Beleg Pflicht, O-1), ``correction`` (+1 Korrektur, PIN
    im Router), ``loss`` (−1 Abgang mit Grund). Regeln S2, S5, S6."""
    packs = _packs(payload.get("packs"))
    device = _device(payload.get("device_id"))
    note = _note(payload.get("note"))
    with transaction(conn):
        row = _row(conn, raw_material_id)
        _bookable(row)
        pack_g, pack_label = pack_of(row)
        if pack_g is None:
            raise ConflictError("Für diesen Rohstoff ist kein Gebinde hinterlegt.", code="pack_missing")
        grams = packs * pack_g
        before = row["stock_g"]
        purchase_id = reason = None
        if mode == "loss":
            reason = _reason(payload)
            if before is None:
                raise ConflictError(f"„{row['name']}“ wird ohne Bestand geführt – Abgang nicht möglich.",
                                    code="not_tracked")
            after = before - grams
        else:
            if before is None and payload.get("start_tracking") is not True:
                raise ConflictError(f"„{row['name']}“ hat keine Bestandsführung. Ab jetzt führen (ab 0)?",
                                    code="not_tracked")
            if mode == "receipt":
                purchase_id = payload.get("purchase_id")
                if isinstance(purchase_id, bool) or not isinstance(purchase_id, int) or not conn.execute(
                        "SELECT 1 FROM purchase WHERE id = ?", (purchase_id,)).fetchone():
                    raise ValidationError("Zugang nur mit Beleg: bitte einen Einkauf wählen.", field="purchase_id",
                                          code="purchase_required")
            after = (before or 0) + grams
        movement_id = _book(conn, raw_material_id, mode, before, after, source=SCAN, note=note, reason=reason,
                            purchase_id=purchase_id, device_id=device)
    return {"movement_id": movement_id, "raw_material_id": raw_material_id, "name": row["name"],
            "packs": packs, "pack_g": pack_g, "pack_label": pack_label, "delta_g": after - (before or 0),
            "stock_g": after}


def loss(conn, raw_material_id: int, payload: dict) -> int:
    """Abgang von Hand (Schnellerfassung, docs/strichcode.md 7): Menge in kg mit Grund."""
    grams = parse_kg(payload.get("amount_kg"), "amount_kg", allow_empty=False, allow_negative=False)
    if grams == 0:
        raise ValidationError("Bitte eine Menge größer 0 eingeben.", field="amount_kg")
    reason = _reason(payload)
    with transaction(conn):
        row = _row(conn, raw_material_id)
        _bookable(row)
        if row["stock_g"] is None:
            raise ConflictError(f"„{row['name']}“ wird ohne Bestand geführt – Abgang nicht möglich.",
                                code="not_tracked")
        return _book(conn, raw_material_id, "loss", row["stock_g"], row["stock_g"] - grams,
                     source=QUICK_ENTRY if _quick(payload) else "admin", note=_note(payload.get("note")),
                     reason=reason)


def undo(conn, movement_id: int, payload: dict) -> dict:
    """Rückgängig (docs/strichcode.md 3): Gegenbuchung, nur eigene Scans dieses Geräts der letzten 10 Minuten."""
    device = _device(payload.get("device_id"))
    with transaction(conn):
        m = conn.execute(
            "SELECT m.*, (m.created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)) AS fresh, "
            "EXISTS (SELECT 1 FROM stock_movement u WHERE u.undo_of_id = m.id) AS undone "
            "FROM stock_movement m WHERE m.id = ?", (f"-{UNDO_MINUTES} minutes", movement_id)).fetchone()
        if m is None:
            raise NotFoundError("Buchung nicht gefunden.", code="not_found")
        if m["source"] != SCAN or m["device_id"] != device or m["kind"] == "undo":
            raise ConflictError("Rückgängig geht nur für eigene Scans dieses Geräts.", code="undo_not_allowed")
        if m["undone"]:
            raise ConflictError("Diese Buchung ist schon zurückgenommen.", code="undo_done")
        if not m["fresh"]:
            raise ConflictError(f"Rückgängig geht nur in den ersten {UNDO_MINUTES} Minuten.", code="undo_expired")
        row = _row(conn, m["raw_material_id"])
        if row["stock_g"] is None or m["delta_g"] is None:
            raise ConflictError("Der Bestand wird nicht mehr geführt – nichts zurückzunehmen.", code="not_tracked")
        after = row["stock_g"] - m["delta_g"]
        new_id = _book(conn, m["raw_material_id"], "undo", row["stock_g"], after, source=SCAN,
                       note=f"Rückgängig: {KIND_TEXT[m['kind']]}", device_id=device, undo_of_id=movement_id)
    return {"movement_id": new_id, "raw_material_id": m["raw_material_id"], "name": row["name"],
            "stock_g": after}


def movements(conn, raw_material_id: int, limit: int = 50) -> list[dict]:
    _row(conn, raw_material_id)
    rows = conn.execute(
        "SELECT m.id, m.kind, m.delta_g, m.stock_after_g, m.batch_id, b.batch_no, m.station_id, m.source, "
        "m.note, m.created_at, m.reason, m.purchase_id, p.label AS purchase_label, m.undo_of_id "
        "FROM stock_movement m LEFT JOIN batch b ON b.id = m.batch_id "
        "LEFT JOIN purchase p ON p.id = m.purchase_id "
        "WHERE m.raw_material_id = ? ORDER BY m.id DESC LIMIT ?", (raw_material_id, limit)).fetchall()
    return [_movement(r) for r in rows]


def _movement(r) -> dict:
    return dict(r, kind_text=KIND_TEXT[r["kind"]],
                reason_text=REASONS.get("breakage" if r["reason"] == "spoilage" else r["reason"]))


def movements_all(conn, *, date_from: str | None = None, date_to: str | None = None,
                  raw_material_id: int | None = None, kind: str | None = None, limit: int = 500) -> list[dict]:
    """Verlauf aller Rohstoffe (Unterreiter „Bestand“, docs/rohstoffverwaltung.md 6.3), neueste zuerst.

    ``date_from``/``date_to``: Tage im Format JJJJ-MM-TT (UTC wie gespeichert), beide einschließlich.
    """
    where, params = [], []
    for value, field, op in ((date_from, "from", ">="), (date_to, "to", "<")):
        if value is None or value == "":
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(value)):
            raise ValidationError("Datum im Format JJJJ-MM-TT.", field=field)
        where.append(f"m.created_at {op} " + ("?" if op == ">=" else "strftime('%Y-%m-%dT%H:%M:%SZ', date(?, '+1 day'))"))
        params.append(value)
    if raw_material_id is not None:
        where.append("m.raw_material_id = ?")
        params.append(raw_material_id)
    if kind is not None and kind != "":
        if kind not in KIND_TEXT:
            raise ValidationError("Unbekannte Buchungsart.", field="kind")
        where.append("m.kind = ?")
        params.append(kind)
    limit = max(1, min(int(limit), 2000))
    sql = ("SELECT m.id, m.raw_material_id, rm.number, rm.name, m.kind, m.delta_g, m.stock_after_g, m.batch_id, "
           "b.batch_no, m.station_id, m.source, m.note, m.created_at, m.reason, m.purchase_id, "
           "p.label AS purchase_label, m.undo_of_id FROM stock_movement m "
           "JOIN raw_material rm ON rm.id = m.raw_material_id LEFT JOIN batch b ON b.id = m.batch_id "
           "LEFT JOIN purchase p ON p.id = m.purchase_id"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY m.id DESC LIMIT ?")
    rows = conn.execute(sql, (*params, limit)).fetchall()
    return [_movement(r) for r in rows]


def need_status(conn, needs: dict[int, int]) -> list[dict]:
    """Bedarf je Rohstoff → Bestand, Meldewert, Status (B6), sortiert nach Rohstoff-ID."""
    out = []
    for rm_id, need in sorted(needs.items()):
        row = conn.execute("SELECT id, number, name, display_name, stock_g, stock_alert_g FROM raw_material "
                           "WHERE id = ?", (rm_id,)).fetchone()
        if row is None:
            continue
        out.append({"raw_material_id": rm_id, "number": row["number"], "name": row["name"],
                    "station_name": row["display_name"] or row["name"], "need_g": need,
                    "stock_g": row["stock_g"], "stock_alert_g": row["stock_alert_g"],
                    "stock_status": status(row["stock_g"], row["stock_alert_g"], need)})
    return out
