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
from ..errors import NotFoundError, ValidationError

MAX_KG = Decimal("1000000")          # Plausibilitätsgrenze je Eingabe (1 000 t)
KIND_TEXT = {"receipt": "Zugang", "inventory": "Bestand gesetzt", "consumption": "Verwiegung",
             "reversal": "Rückbuchung"}

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
    row = conn.execute("SELECT id, name, stock_g, stock_alert_g, archived FROM raw_material WHERE id = ?",
                       (raw_material_id,)).fetchone()
    if row is None:
        raise NotFoundError("Rohstoff nicht gefunden.", code="not_found")
    return row


def _book(conn, raw_material_id: int, kind: str, before: int | None, after: int | None, *, source: str,
          note: str | None = None, batch_id=None, batch_item_id=None, station=None) -> None:
    delta = None if before is None or after is None else after - before
    if kind in ("receipt", "consumption", "reversal") and before is None and after is not None:
        delta = after                               # erste Buchung schaltet die Führung ein
    conn.execute("UPDATE raw_material SET stock_g = ? WHERE id = ?", (after, raw_material_id))
    conn.execute(
        "INSERT INTO stock_movement (raw_material_id, kind, delta_g, stock_after_g, batch_id, batch_item_id, "
        "station_id, source, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (raw_material_id, kind, delta, after, batch_id, batch_item_id, station, source, note))


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

def receipt(conn, raw_material_id: int, payload: dict) -> None:
    grams = parse_kg(payload.get("amount_kg"), "amount_kg", allow_empty=False, allow_negative=False)
    if grams == 0:
        raise ValidationError("Bitte eine Menge größer 0 eingeben.", field="amount_kg")
    station = payload.get("station")
    if station is not None and (isinstance(station, bool) or not isinstance(station, int)):
        raise ValidationError("Ungültige Station.", field="station")
    with transaction(conn):
        if station is not None and not conn.execute("SELECT 1 FROM station WHERE id = ?", (station,)).fetchone():
            raise ValidationError("Station unbekannt.", field="station")
        receipt_in_tx(conn, raw_material_id, grams, note=payload.get("note"), station=station,
                      source="station" if station is not None else "admin")


def inventory(conn, raw_material_id: int, payload: dict) -> None:
    if "stock_kg" not in payload:
        raise ValidationError("Bitte den Bestand angeben (leer = Bestandsführung beenden).", field="stock_kg")
    grams = parse_kg(payload.get("stock_kg"), "stock_kg", allow_empty=True)
    with transaction(conn):
        inventory_in_tx(conn, raw_material_id, grams, note=payload.get("note"))


def movements(conn, raw_material_id: int, limit: int = 50) -> list[dict]:
    _row(conn, raw_material_id)
    rows = conn.execute(
        "SELECT m.id, m.kind, m.delta_g, m.stock_after_g, m.batch_id, b.batch_no, m.station_id, m.source, "
        "m.note, m.created_at FROM stock_movement m LEFT JOIN batch b ON b.id = m.batch_id "
        "WHERE m.raw_material_id = ? ORDER BY m.id DESC LIMIT ?", (raw_material_id, limit)).fetchall()
    return [dict(r, kind_text=KIND_TEXT[r["kind"]]) for r in rows]


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
