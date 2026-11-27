"""Kassenimport Vectron-Abverkauf (Teil H1, docs/handelsware.md 6, K03-86).

Ablauf wie bei den anderen Importen: ``mode=check`` (Probelauf, Bericht) → ``mode=run`` mit derselben Datei.

* Spalten über die Überschrift: Artikelnummer („Nummer“, „Artikel-Nr.“, „PLU“ …), Anzahl („Anzahl“, „Menge“ …),
  Wert („Wert“, „Umsatz“, „Betrag“ …), Name optional. Gleiche Nummern werden zusammengezählt.
* Zeitraum: aus der Datei (Datumsangaben in den Kopfzeilen) vorgeschlagen, von Hand änderbar. Jeder Zeitraum lässt
  sich nur einmal importieren; überlappende Zeiträume werden abgelehnt (Doppelt-Schutz).
* Je Handelsware mit Kassennummer: Abgang „Verkauf laut Kasse“ in Stück; bei einem Verweis (K03-93) beim Rohstoff
  über das Gewicht je Stück. Sammelartikel 500 „Offene Handelswaren“ und Kassenartikel ohne Zuordnung werden nur
  angezeigt. Pfand-Artikel zählen als „Pfand Kunden“ (K03-87).
"""

from __future__ import annotations

import hashlib
import io
import re
import sqlite3
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ..db import transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from . import stock
from .models import GOODS_UNIT, normalize_text

COLLECTIVE_NO = 500                 # Sammelartikel „Offene Handelswaren“ – nie gebucht, nur angezeigt
SOURCE = "sales_import"
MAX_ROWS = 20000
STATUS_TEXT = {"booked": "gebucht", "collective": "Sammelartikel – nur angezeigt",
               "unassigned": "ohne Zuordnung – nur angezeigt", "no_stock": "Rohstoff ohne Bestandsführung – nicht gebucht"}

_HEAD = {
    "number": ("nummer", "artikelnummer", "artikel-nr", "artikel nr", "art-nr", "artnr", "art nr", "plu", "nr",
               "artikel-nummer", "kassennummer"),
    "name": ("name", "bezeichnung", "artikel", "artikelname", "text", "artikelbezeichnung"),
    "qty": ("anzahl", "menge", "stück", "stk", "verkauft", "anz", "stückzahl"),
    "value": ("wert", "umsatz", "betrag", "summe", "brutto", "umsatz brutto", "gesamt", "wert brutto", "betrag brutto"),
}
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})")


def _key(value) -> str:
    text = normalize_text(str(value)).casefold() if value is not None else ""
    return re.sub(r"[.:€()]", "", text).strip()


def _columns(header) -> dict | None:
    names = [_key(c) for c in header]
    cols: dict = {}
    for field, words in _HEAD.items():
        for i, n in enumerate(names):
            if n in words and i not in cols.values():
                cols[field] = i
                break
    return cols if "number" in cols and "qty" in cols else None


def _number(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace("€", "").replace(" ", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _dates_in(value) -> list[date]:
    if isinstance(value, datetime):
        return [value.date()]
    if isinstance(value, date):
        return [value]
    out = []
    for d, m, y in _DATE.findall(str(value or "")):
        y = int(y) + (2000 if len(y) == 2 else 0)
        try:
            out.append(date(y, int(m), int(d)))
        except ValueError:
            pass
    return out


def read_sales(data: bytes, file_name: str | None = None) -> dict:
    """Liest die Abverkaufszeilen (je Artikelnummer zusammengezählt) und den vorgeschlagenen Zeitraum."""
    from openpyxl import load_workbook

    if not data:
        raise ValidationError("Die Datei ist leer.", code="empty_file")
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ValidationError("Die Datei ist keine lesbare Excel-Datei (.xlsx).", code="not_xlsx") from exc
    try:
        for ws in wb.worksheets:
            found: list[date] = []
            rows = ws.iter_rows(values_only=True)
            cols = None
            for n, header in enumerate(rows):
                cols = _columns(header)
                if cols:
                    break
                if n < 30:
                    for c in header:
                        found.extend(_dates_in(c))
            if cols is None:
                continue
            items: dict[int, dict] = {}
            count = 0
            for values in rows:
                count += 1
                if count > MAX_ROWS:
                    raise ValidationError(f"Die Datei hat mehr als {MAX_ROWS} Zeilen.", code="too_many_rows")
                values = list(values) + [None] * 4

                def get(field):
                    i = cols.get(field)
                    return values[i] if i is not None and i < len(values) else None

                no = _number(get("number"))
                qty = _number(get("qty"))
                if no is None or qty is None or no != no.to_integral_value() or no <= 0:
                    continue
                name = normalize_text(str(get("name"))) if get("name") is not None else ""
                if name.startswith("#"):
                    continue
                value = _number(get("value"))
                it = items.setdefault(int(no), {"register_no": int(no), "name": name[:80], "qty_milli": 0,
                                                "value_cents": 0 if value is not None else None})
                it["qty_milli"] += int((qty * 1000).to_integral_value())
                if value is not None:
                    it["value_cents"] = (it["value_cents"] or 0) + int((value * 100).to_integral_value())
            if file_name:
                found.extend(_dates_in(file_name))
            period = (min(found).isoformat(), max(found).isoformat()) if found else (None, None)
            return {"items": [items[k] for k in sorted(items)], "date_from": period[0], "date_to": period[1]}
    finally:
        wb.close()
    raise ValidationError("In der Datei fehlen die Spalten Artikelnummer und Anzahl (Abverkauf der Vectron).",
                          code="columns_missing")


def _day(value, field: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValidationError("Datum im Format JJJJ-MM-TT.", field=field)
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValidationError("Ungültiges Datum.", field=field) from None
    return value


def _overlap(conn, date_from: str, date_to: str):
    return conn.execute("SELECT id, date_from, date_to, created_at FROM sales_import WHERE date_from <= ? AND date_to >= ? "
                        "ORDER BY date_from LIMIT 1", (date_to, date_from)).fetchone()


def _text(d: str) -> str:
    y, m, dd = d.split("-")
    return f"{dd}.{m}.{y}"


def _classify(conn, it: dict) -> dict:
    out = dict(it, status="unassigned", raw_material_id=None, goods_name=None, target_name=None, booked_qty=None,
               is_deposit=False, unit="Stück")
    if it["register_no"] == COLLECTIVE_NO:
        out["status"] = "collective"
        return out
    g = conn.execute("SELECT g.id, g.name, g.is_deposit, g.stock_ref_id, g.piece_g, g.stock_g, r.name AS ref_name, "
                     "r.stock_g AS ref_stock, r.archived AS ref_archived FROM raw_material g "
                     "LEFT JOIN raw_material r ON r.id = g.stock_ref_id WHERE g.register_no = ? AND g.archived = 0 "
                     "AND g.type = 'goods'", (it["register_no"],)).fetchone()
    if g is None:
        return out
    out.update(goods_name=g["name"], is_deposit=bool(g["is_deposit"]))
    if g["stock_ref_id"] is not None:
        out.update(raw_material_id=g["stock_ref_id"], target_name=g["ref_name"], unit="g",
                   booked_qty=it["qty_milli"] * g["piece_g"] // 1000)
        out["status"] = "no_stock" if g["ref_stock"] is None or g["ref_archived"] else "booked"
    else:
        out.update(raw_material_id=g["id"], target_name=g["name"], booked_qty=it["qty_milli"] * GOODS_UNIT // 1000,
                   status="booked")
    return out


def import_sales(conn: sqlite3.Connection, data: bytes, *, mode: str = "check", date_from: str | None = None,
                 date_to: str | None = None, file_name: str | None = None) -> dict:
    if mode not in ("check", "run"):
        raise ValidationError("mode: check oder run.", field="mode")
    parsed = read_sales(data, file_name)
    date_from = _day(date_from, "date_from") or parsed["date_from"]
    date_to = _day(date_to, "date_to") or parsed["date_to"] or date_from
    if date_from and date_to and date_from > date_to:
        raise ValidationError("„von“ liegt nach „bis“.", field="date_from")
    lines = [_classify(conn, it) for it in parsed["items"]]
    dup = _overlap(conn, date_from, date_to) if date_from and date_to else None
    deposit = sum(l["value_cents"] or 0 for l in lines if l["is_deposit"])
    report = {"mode": mode, "date_from": date_from, "date_to": date_to,
              "detected_from": parsed["date_from"], "detected_to": parsed["date_to"],
              "duplicate": None if dup is None else {"date_from": dup["date_from"], "date_to": dup["date_to"],
                                                     "created_at": dup["created_at"]},
              "counts": {s: sum(1 for l in lines if l["status"] == s) for s in STATUS_TEXT},
              "deposit_cents": deposit, "lines": [dict(l, status_text=STATUS_TEXT[l["status"]]) for l in lines],
              "without_register": _without_register(conn), "imported": False}
    if mode == "check":
        return report
    if not date_from or not date_to:
        raise ValidationError("Bitte den Zeitraum angeben (von/bis).", field="date_from", code="period_missing")
    sha = hashlib.sha256(data).hexdigest()
    with transaction(conn):
        dup = _overlap(conn, date_from, date_to)
        if dup is not None:
            raise ConflictError(f"Der Zeitraum {_text(dup['date_from'])}–{_text(dup['date_to'])} ist schon importiert "
                                f"– jeder Zeitraum nur einmal.", code="period_imported")
        imp_id = conn.execute(
            "INSERT INTO sales_import (date_from, date_to, file_name, file_sha256, deposit_cents, total_cents) "
            "VALUES (?, ?, ?, ?, ?, ?)", (date_from, date_to, (file_name or "")[:200] or None, sha, deposit,
                                          sum(l["value_cents"] or 0 for l in lines))).lastrowid
        booked = 0
        note = f"Kasse {_text(date_from)}–{_text(date_to)}"
        for l in _rebuild(conn, parsed["items"]):
            mid = None
            if l["status"] == "booked" and l["booked_qty"]:
                row = stock._row(conn, l["raw_material_id"])
                before = row["stock_g"]
                mid = stock._book(conn, row["id"], "sale", before, (before or 0) - l["booked_qty"], source=SOURCE,
                                  note=(note + f" · Kasse {l['register_no']} × {l['qty_milli'] / 1000:g}"
                                        + (f" ({l['goods_name']})" if l["goods_name"] != row["name"] else ""))[:500],
                                  sales_import_id=imp_id)
                booked += 1
            conn.execute(
                "INSERT INTO sales_import_line (sales_import_id, register_no, name, qty_milli, value_cents, status, "
                "raw_material_id, booked_qty, is_deposit, stock_movement_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (imp_id, l["register_no"], l["name"] or l["goods_name"], l["qty_milli"], l["value_cents"], l["status"],
                 l["raw_material_id"], l["booked_qty"], 1 if l["is_deposit"] else 0, mid))
        conn.execute("UPDATE sales_import SET booked_count = ? WHERE id = ?", (booked, imp_id))
    report.update(imported=True, id=imp_id, booked=booked)
    return report


def _rebuild(conn, items):
    return [_classify(conn, it) for it in items]


def _without_register(conn) -> list[dict]:
    """Handelsware ohne Kassennummer: „ohne Kassenartikel, nur Inventur“ (K03-86)."""
    return [dict(r) for r in conn.execute(
        "SELECT id, number, name FROM raw_material WHERE type = 'goods' AND archived = 0 AND register_no IS NULL "
        "ORDER BY name")]


def list_imports(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT s.*, (SELECT count(*) FROM sales_import_line l WHERE l.sales_import_id = s.id) AS lines "
                        "FROM sales_import s ORDER BY s.date_from DESC").fetchall()
    return [dict(r) for r in rows]


def get_import(conn: sqlite3.Connection, import_id: int) -> dict:
    row = conn.execute("SELECT * FROM sales_import WHERE id = ?", (import_id,)).fetchone()
    if row is None:
        raise NotFoundError("Kassenimport nicht gefunden.", code="not_found")
    lines = conn.execute("SELECT l.*, r.name AS target_name FROM sales_import_line l LEFT JOIN raw_material r "
                         "ON r.id = l.raw_material_id WHERE l.sales_import_id = ? ORDER BY l.status <> 'booked', "
                         "l.register_no", (import_id,)).fetchall()
    return dict(row, lines=[dict(l, status_text=STATUS_TEXT[l["status"]], is_deposit=bool(l["is_deposit"]))
                            for l in lines])


def delete_import(conn: sqlite3.Connection, import_id: int) -> dict:
    """Kassenimport zurücknehmen: jede Verkaufsbuchung bekommt eine Gegenbuchung („Rückgängig“), der Zeitraum
    ist danach wieder frei."""
    reversed_n = 0
    with transaction(conn):
        row = conn.execute("SELECT * FROM sales_import WHERE id = ?", (import_id,)).fetchone()
        if row is None:
            raise NotFoundError("Kassenimport nicht gefunden.", code="not_found")
        for m in conn.execute("SELECT m.* FROM stock_movement m WHERE m.sales_import_id = ? AND m.kind = 'sale' "
                              "AND NOT EXISTS (SELECT 1 FROM stock_movement u WHERE u.undo_of_id = m.id)",
                              (import_id,)).fetchall():
            rm = stock._row(conn, m["raw_material_id"])
            if rm["stock_g"] is None or m["delta_g"] is None:
                continue
            stock._book(conn, rm["id"], "undo", rm["stock_g"], rm["stock_g"] - m["delta_g"], source=SOURCE,
                        undo_of_id=m["id"], note=f"Kassenimport {_text(row['date_from'])}–{_text(row['date_to'])} "
                                                  "zurückgenommen")
            reversed_n += 1
        conn.execute("UPDATE stock_movement SET sales_import_id = NULL WHERE sales_import_id = ?", (import_id,))
        conn.execute("DELETE FROM sales_import WHERE id = ?", (import_id,))
    return {"reversed": reversed_n}
