"""Inventur, Teil I1 (Modul 03, docs/strichcode.md 5, VC03-e).

Ablauf: anlegen (PIN) → zählen (ohne PIN, blind: ohne Buchbestand und ohne Preise) → Vorschau und Abschluss
(PIN) → Export .xlsx. Höchstens eine offene Inventur.

Mengen stehen in derselben Einheit wie ``raw_material.stock_g``: Gramm, bei Hilfs- und Betriebsstoffen
1 Verpackungseinheit = 1000 (Strichcode S1). Preis „je kg“ ist bei Hilfs- und Betriebsstoffen der Preis je
Verpackungseinheit (H-B); Wert = Menge × Preis / 1000 gilt damit für beide Arten.

Zählzeitpunkt (Abschnitt 5.4): Jeder Zähleintrag merkt sich den Buchbestand im Moment der Zählung. Beim
Abschluss gilt: neuer Bestand = gezählt + Bewegungen seit der Zählung. Bezug ist der **letzte** Zähleintrag des
Rohstoffs (Hinweis Claude: Bewegungen lassen sich keinem Lagerort zuordnen; nach dem letzten Eintrag ist der
Rohstoff fertig gezählt).
"""

from __future__ import annotations

import io
import re
import sqlite3
from datetime import date, datetime, timezone

from ..db import transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from ..raw_materials import stock
from ..raw_materials.models import AID_UNIT, normalize_text

SCOPES = {"stocked": "alle bestandsgeführten", "active": "alle aktiven"}
STATUS_TEXT = {"open": "offen", "closed": "abgeschlossen", "cancelled": "verworfen"}
SOURCE = "stocktake"            # Quelle der Inventur-Buchungen in stock_movement
MAX_NAME = 60
NO_LOCATION = "ohne Lagerort"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# -- Hilfen ----------------------------------------------------------------------------

def date_text(iso: str) -> str:
    """JJJJ-MM-TT → TT.MM.JJJJ."""
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def value_cents(qty: int | None, price_cents: int | None) -> int | None:
    """Menge (g bzw. VE × 1000) × Preis je kg bzw. VE, kaufmännisch gerundet; negative Mengen zählen 0."""
    if qty is None or price_cents is None:
        return None
    q, r = divmod(max(qty, 0) * price_cents, 1000)
    return q + (1 if r >= 500 else 0)


def _int_id(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError("Ungültige Auswahl.", field=field)
    return value


def _stocktake(conn, stocktake_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM stocktake WHERE id = ?", (stocktake_id,)).fetchone()
    if row is None:
        raise NotFoundError("Inventur nicht gefunden.", code="not_found")
    return row


def _open_row(conn) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM stocktake WHERE status = 'open'").fetchone()


def _require_open(conn) -> sqlite3.Row:
    row = _open_row(conn)
    if row is None:
        raise ConflictError("Es ist keine Inventur offen.", code="no_open_stocktake")
    return row


def _head(row) -> dict:
    return {"id": row["id"], "name": row["name"], "stichtag": row["stichtag"],
            "stichtag_text": date_text(row["stichtag"]), "scope": row["scope"], "scope_text": SCOPES[row["scope"]],
            "status": row["status"], "status_text": STATUS_TEXT[row["status"]], "created_at": row["created_at"],
            "closed_at": row["closed_at"], "total_value_cents": row["total_value_cents"],
            "missing_price_count": row["missing_price_count"], "note": row["note"]}


# -- Anlegen, Liste, Verwerfen ----------------------------------------------------------

def list_stocktakes(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT s.*, (SELECT count(*) FROM stocktake_count c WHERE c.stocktake_id = s.id) AS counts "
                        "FROM stocktake s ORDER BY s.id DESC").fetchall()
    return [dict(_head(r), counts=r["counts"]) for r in rows]


def create(conn: sqlite3.Connection, payload: dict) -> dict:
    """Inventur anlegen (PIN im Router): Stichtag, Bezeichnung, Umfang."""
    name = payload.get("name")
    name = normalize_text(name) if isinstance(name, str) else ""
    if not name or len(name) > MAX_NAME:
        raise ValidationError(f"Bitte eine Bezeichnung angeben (höchstens {MAX_NAME} Zeichen), "
                              "z. B. „Jahresinventur 2026“.", field="name")
    day = payload.get("stichtag") or date.today().isoformat()
    if not isinstance(day, str) or not _DATE.match(day):
        raise ValidationError("Stichtag im Format JJJJ-MM-TT.", field="stichtag")
    try:
        date.fromisoformat(day)
    except ValueError:
        raise ValidationError("Ungültiger Stichtag.", field="stichtag") from None
    scope = payload.get("scope") or "stocked"
    if scope not in SCOPES:
        raise ValidationError("Umfang: alle bestandsgeführten oder alle aktiven Rohstoffe.", field="scope")
    note = stock._note(payload.get("note"))
    with transaction(conn):
        if _open_row(conn) is not None:
            raise ConflictError("Es ist schon eine Inventur offen – erst abschließen oder verwerfen.",
                                code="stocktake_open")
        new_id = conn.execute("INSERT INTO stocktake (name, stichtag, scope, note) VALUES (?, ?, ?, ?)",
                              (name, day, scope, note)).lastrowid
    return _head(_stocktake(conn, new_id))


def cancel(conn: sqlite3.Connection, stocktake_id: int) -> dict:
    """Offene Inventur verwerfen (PIN): bucht nichts, Zähleinträge bleiben zur Ansicht."""
    with transaction(conn):
        row = _stocktake(conn, stocktake_id)
        if row["status"] != "open":
            raise ConflictError("Nur eine offene Inventur kann verworfen werden.", code="not_open")
        conn.execute("UPDATE stocktake SET status = 'cancelled', closed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
                     "WHERE id = ?", (stocktake_id,))
    return _head(_stocktake(conn, stocktake_id))


# -- Rohstoffe im Umfang ------------------------------------------------------------------

_ITEM_SQL = (
    "SELECT r.id, r.number, r.name, r.display_name, r.type, r.archived, r.stock_g, r.unit_size_g, r.unit_label, "
    "r.delivery_pack_g, r.delivery_pack_label, r.price_cents_per_kg, r.location1_id, r.location1_label, "
    "r.location2_id, r.location2_label, l1.name AS location1_name, l1.sort AS location1_sort, "
    "l2.name AS location2_name, l2.sort AS location2_sort "
    "FROM raw_material r LEFT JOIN storage_location l1 ON l1.id = r.location1_id "
    "LEFT JOIN storage_location l2 ON l2.id = r.location2_id ")


def _items(conn, st) -> list[sqlite3.Row]:
    """Rohstoffe im Umfang der Inventur (aktiv; bei ``stocked`` nur mit Bestandsführung) plus alle, die schon
    gezählt wurden (auch wenn sie außerhalb des Umfangs liegen). Hilfs- und Betriebsstoffe einschließlich."""
    rows = conn.execute(
        _ITEM_SQL + "WHERE (r.archived = 0 AND (? = 'active' OR r.stock_g IS NOT NULL)) "
        "OR r.id IN (SELECT raw_material_id FROM stocktake_count WHERE stocktake_id = ?) ORDER BY r.number",
        (st["scope"], st["id"])).fetchall()
    return rows


def _locations_of(r) -> list[dict]:
    out = []
    for n in (1, 2):
        if r[f"location{n}_id"] is not None:
            out.append({"id": r[f"location{n}_id"], "name": r[f"location{n}_name"], "label": r[f"location{n}_label"],
                        "sort": r[f"location{n}_sort"]})
    return out


def _location_text(locs: list[dict]) -> str:
    return ", ".join(loc["name"] + (f" ({loc['label']})" if loc["label"] else "") for loc in locs)


def _counts(conn, stocktake_id: int) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for c in conn.execute("SELECT c.id, c.raw_material_id, c.location_id, l.name AS location_name, c.qty, "
                          "c.book_at_count, c.source, c.device_id, c.created_at FROM stocktake_count c "
                          "LEFT JOIN storage_location l ON l.id = c.location_id WHERE c.stocktake_id = ? "
                          "ORDER BY c.id", (stocktake_id,)):
        out.setdefault(c["raw_material_id"], []).append(dict(c))
    return out


def _done(locs: list[dict], counts: list[dict]) -> bool:
    """Gezählt erst, wenn an allen Lagerorten des Rohstoffs gezählt wurde (Abschnitt 5.3); ohne Lagerort: ein Eintrag."""
    if not counts:
        return False
    if not locs:
        return True
    seen = {c["location_id"] for c in counts}
    return all(loc["id"] in seen for loc in locs)


# -- Zählen (ohne PIN, blind) --------------------------------------------------------------

def open_view(conn: sqlite3.Connection) -> dict:
    """Zählliste der offenen Inventur – ohne Buchbestand und ohne Preise (blind zählen)."""
    st = _open_row(conn)
    if st is None:
        return {"stocktake": None}
    counts = _counts(conn, st["id"])
    items = []
    for r in _items(conn, st):
        locs = _locations_of(r)
        mine = counts.get(r["id"], [])
        pack_g, pack_label = stock.pack_of(r)
        items.append({
            "id": r["id"], "number": r["number"], "name": r["name"], "display_name": r["display_name"],
            "type": r["type"], "archived": bool(r["archived"]), "pack_g": pack_g, "pack_label": pack_label,
            "unit_label": r["unit_label"], "locations": [{k: v for k, v in loc.items() if k != "sort"} for loc in locs],
            "counts": [{k: c[k] for k in ("id", "location_id", "location_name", "qty", "source", "created_at")}
                       for c in mine],
            "counted": sum(c["qty"] for c in mine) if mine else None,
            "counted_locations": sorted({c["location_id"] for c in mine}, key=lambda x: (x is None, x or 0)),
            "done": _done(locs, mine)})
    used = {loc["id"] for it in items for loc in it["locations"]} | \
        {c["location_id"] for it in items for c in it["counts"] if c["location_id"] is not None}
    locations = [dict(loc, open=sum(1 for it in items if any(x["id"] == loc["id"] for x in it["locations"])
                                    and loc["id"] not in it["counted_locations"]))
                 for loc in _all_locations(conn) if loc["id"] in used or not loc["archived"]]
    no_loc_open = sum(1 for it in items if not it["locations"] and not it["counts"])
    return {"stocktake": _head(st), "items": items, "locations": locations,
            "without_location_open": no_loc_open, "total": len(items),
            "open": sum(1 for it in items if not it["done"])}


def _all_locations(conn) -> list[dict]:
    return [dict(r, archived=bool(r["archived"])) for r in
            conn.execute("SELECT id, name, code, sort, archived FROM storage_location ORDER BY sort, name")]


def _location(conn, value) -> int | None:
    if value is None or value == "":
        return None
    loc_id = _int_id(value, "location_id")
    if not conn.execute("SELECT 1 FROM storage_location WHERE id = ?", (loc_id,)).fetchone():
        raise ValidationError("Lagerort unbekannt.", field="location_id")
    return loc_id


def _count_qty(row, payload: dict) -> int:
    """Menge eines Zähleintrags: ``packs`` (+ ``rest_kg``) wie „3 Sack + 12,5 kg“ (O-5) oder ``amount_kg``.
    Bei Hilfs- und Betriebsstoffen zählt ``packs`` in Verpackungseinheiten, ``amount_kg`` ebenso (1 = 1 VE)."""
    aid = row["type"] == "aid"
    if "packs" in payload and payload.get("packs") not in (None, ""):
        packs = stock._packs(payload.get("packs"), allow_zero=True)
        pack_g = AID_UNIT if aid else stock.pack_of(row)[0]
        if packs and pack_g is None:
            raise ConflictError("Für diesen Rohstoff ist kein Gebinde hinterlegt – Menge in kg eingeben.",
                                code="pack_missing")
        rest = 0 if aid else (stock.parse_kg(payload.get("rest_kg"), "rest_kg", allow_empty=True,
                                             allow_negative=False) or 0)
        return packs * (pack_g or 0) + rest
    qty = stock.parse_kg(payload.get("amount_kg"), "amount_kg", allow_empty=False, allow_negative=False)
    return qty


def add_count(conn: sqlite3.Connection, payload: dict) -> dict:
    """Zähleintrag (ohne PIN, K03-59). „0“ ist erlaubt (an diesem Ort liegt nichts)."""
    rm_id = _int_id(payload.get("raw_material_id"), "raw_material_id")
    source = "scan" if payload.get("source") == "scan" else "hand"
    device = stock._device(payload.get("device_id"), required=False)
    with transaction(conn):
        st = _require_open(conn)
        row = conn.execute(_ITEM_SQL + "WHERE r.id = ?", (rm_id,)).fetchone()
        if row is None:
            raise NotFoundError("Rohstoff nicht gefunden.", code="not_found")
        if row["archived"]:
            raise ConflictError(f"„{row['name']}“ ist archiviert – nicht zählen.", code="archived")
        loc_id = _location(conn, payload.get("location_id"))
        qty = _count_qty(row, payload)
        new_id = conn.execute(
            "INSERT INTO stocktake_count (stocktake_id, raw_material_id, location_id, qty, book_at_count, source, "
            "device_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (st["id"], rm_id, loc_id, qty, row["stock_g"], source, device)).lastrowid
    return _count_result(conn, new_id, rm_id)


def _count_result(conn, count_id: int | None, rm_id: int) -> dict:
    view = open_view(conn)
    item = next((it for it in view.get("items", []) if it["id"] == rm_id), None)
    return {"count_id": count_id, "item": item, "open": view.get("open"), "total": view.get("total")}


def delete_count(conn: sqlite3.Connection, count_id: int) -> dict:
    """Zähleintrag löschen, solange die Inventur offen ist (Abschnitt 5.3; auch „Rückgängig“ beim Scannen)."""
    with transaction(conn):
        row = conn.execute("SELECT c.raw_material_id, s.status FROM stocktake_count c JOIN stocktake s "
                           "ON s.id = c.stocktake_id WHERE c.id = ?", (count_id,)).fetchone()
        if row is None:
            raise NotFoundError("Zähleintrag nicht gefunden.", code="not_found")
        if row["status"] != "open":
            raise ConflictError("Die Inventur ist nicht mehr offen.", code="not_open")
        conn.execute("DELETE FROM stocktake_count WHERE id = ?", (count_id,))
    return _count_result(conn, None, row["raw_material_id"])


def location_done(conn: sqlite3.Connection, payload: dict) -> dict:
    """„Ort fertig“ (O-4): für die gewählten, hier noch nicht gezählten Einträge je eine „0“ buchen."""
    ids = payload.get("raw_material_ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise ValidationError("Ungültige Auswahl.", field="raw_material_ids")
    device = stock._device(payload.get("device_id"), required=False)
    with transaction(conn):
        st = _require_open(conn)
        loc_id = _location(conn, payload.get("location_id"))
        done = 0
        for rm_id in dict.fromkeys(ids):
            row = conn.execute("SELECT id, archived, stock_g FROM raw_material WHERE id = ?", (rm_id,)).fetchone()
            if row is None or row["archived"]:
                continue
            if conn.execute("SELECT 1 FROM stocktake_count WHERE stocktake_id = ? AND raw_material_id = ? "
                            "AND location_id IS ?", (st["id"], rm_id, loc_id)).fetchone():
                continue                                  # hier schon gezählt
            conn.execute("INSERT INTO stocktake_count (stocktake_id, raw_material_id, location_id, qty, book_at_count, "
                         "source, device_id) VALUES (?, ?, ?, 0, ?, 'hand', ?)",
                         (st["id"], rm_id, loc_id, row["stock_g"], device))
            done += 1
    view = open_view(conn)
    return {"zeroed": done, "open": view["open"], "total": view["total"]}


# -- Vorschau und Abschluss (PIN) ------------------------------------------------------------

def _since(book_at_count: int | None, book_now: int | None) -> int:
    """Bewegungen seit der Zählung. Führung erst nach der Zählung begonnen: alles zählt; beendet: nichts."""
    if book_now is None:
        return 0
    if book_at_count is None:
        return book_now
    return book_now - book_at_count


def _compute(conn, st, zero_ids: set[int]) -> list[dict]:
    counts = _counts(conn, st["id"])
    lines = []
    for r in _items(conn, st):
        locs = _locations_of(r)
        mine = counts.get(r["id"], [])
        pack_g, pack_label = stock.pack_of(r)
        book_now = r["stock_g"]
        if mine:
            counted = sum(c["qty"] for c in mine)
            since = _since(mine[-1]["book_at_count"], book_now)
            action, after, value_qty = "set", counted + since, counted
        else:
            counted, since = None, 0
            if r["id"] in zero_ids:
                action, after, value_qty = "zero", 0, 0
            else:
                action, after = "unchanged", book_now
                value_qty = None if book_now is None else max(book_now, 0)
        price = r["price_cents_per_kg"]
        value = value_cents(value_qty, price)
        lines.append({
            "raw_material_id": r["id"], "number": r["number"], "name": r["name"], "type": r["type"],
            "pack_g": pack_g, "pack_label": pack_label, "unit_label": r["unit_label"],
            "locations": _location_text(locs), "counted": counted, "done": _done(locs, mine),
            "count_entries": len(mine), "action": action, "book_before": book_now, "since_count": since,
            "stock_after": after,
            "diff": None if after is None or book_now is None else after - book_now,
            "value_qty": value_qty, "price_cents": price, "value_cents": value,
            "missing_price": price is None and bool(value_qty)})
    return lines


def _totals(lines: list[dict]) -> dict:
    out = {"materials_cents": 0, "aids_cents": 0, "missing_price_count": 0, "counted": 0, "uncounted": 0,
           "incomplete": 0}
    for ln in lines:
        key = "aids_cents" if ln["type"] == "aid" else "materials_cents"
        out[key] += ln["value_cents"] or 0
        out["missing_price_count"] += 1 if ln["missing_price"] else 0
        if ln["counted"] is None:
            out["uncounted"] += 1
        else:
            out["counted"] += 1
            out["incomplete"] += 0 if ln["done"] else 1
    out["total_cents"] = out["materials_cents"] + out["aids_cents"]
    return out


def _zero_ids(value) -> set[int]:
    if value is None:
        return set()
    if not isinstance(value, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in value):
        raise ValidationError("Ungültige Auswahl „auf 0“.", field="zero_ids")
    return set(value)


def _stored_lines(conn, stocktake_id: int) -> list[dict]:
    rows = conn.execute("SELECT * FROM stocktake_line WHERE stocktake_id = ? ORDER BY type = 'aid', number",
                        (stocktake_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["diff"] = None if r["stock_after"] is None or r["book_before"] is None else r["stock_after"] - r["book_before"]
        d["missing_price"] = r["price_cents"] is None and bool(r["value_qty"])
        d["done"] = r["counted"] is not None
        out.append(d)
    return out


def detail(conn: sqlite3.Connection, stocktake_id: int, zero_ids=None) -> dict:
    """Vorschau (offen) bzw. festgeschriebenes Ergebnis (abgeschlossen); mit PIN – zeigt Buchbestand und Wert."""
    st = _stocktake(conn, stocktake_id)
    if st["status"] == "closed":
        lines = _stored_lines(conn, stocktake_id)
    elif st["status"] == "open":
        lines = _compute(conn, st, _zero_ids(zero_ids))
        lines.sort(key=lambda ln: (ln["type"] == "aid", ln["number"]))
    else:
        lines = []
    return {"stocktake": _head(st), "lines": lines, "totals": _totals(lines)}


def close(conn: sqlite3.Connection, stocktake_id: int, payload: dict) -> dict:
    """Abschluss (PIN): je Rohstoff eine Inventur-Buchung „Inventur <Stichtag>“ in einer Transaktion;
    ungezählte bleiben unverändert oder gehen einzeln auf 0 (K03-57); Preis und Wert werden gespeichert (K03-58)."""
    if payload.get("confirm") is not True:
        raise ValidationError("Bitte den Abschluss bestätigen.", field="confirm", code="confirm_required")
    zero_ids = _zero_ids(payload.get("zero_ids"))
    with transaction(conn):
        st = _stocktake(conn, stocktake_id)
        if st["status"] != "open":
            raise ConflictError("Die Inventur ist nicht offen.", code="not_open")
        lines = _compute(conn, st, zero_ids)
        note = f"Inventur {date_text(st['stichtag'])}"
        for ln in lines:
            movement_id = None
            book = ln["action"] == "set" or (ln["action"] == "zero" and ln["book_before"] != 0)
            if book:
                movement_id = stock._book(conn, ln["raw_material_id"], "inventory", ln["book_before"],
                                          ln["stock_after"], source=SOURCE, note=note, stocktake_id=stocktake_id)
            conn.execute(
                "INSERT INTO stocktake_line (stocktake_id, raw_material_id, counted, action, book_before, stock_after, "
                "since_count, value_qty, price_cents, value_cents, stock_movement_id, number, name, type, pack_g, "
                "pack_label, locations) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (stocktake_id, ln["raw_material_id"], ln["counted"], ln["action"], ln["book_before"],
                 ln["stock_after"], ln["since_count"], ln["value_qty"], ln["price_cents"], ln["value_cents"],
                 movement_id, ln["number"], ln["name"], ln["type"], ln["pack_g"],
                 ln["unit_label"] if ln["type"] == "aid" else ln["pack_label"], ln["locations"] or None))
        totals = _totals(lines)
        conn.execute("UPDATE stocktake SET status = 'closed', closed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
                     "total_value_cents = ?, missing_price_count = ? WHERE id = ?",
                     (totals["total_cents"], totals["missing_price_count"], stocktake_id))
    return detail(conn, stocktake_id)


# -- Zählliste zum Drucken (blind) ---------------------------------------------------------------

def countlist(conn: sqlite3.Connection, stocktake_id: int) -> dict:
    """Nach Lagerort sortiert: Nr., Name, Gebinde, leere Spalte „gezählt“ – ohne Preise und Buchbestand.
    Ein Rohstoff mit zwei Lagerorten steht an beiden Orten; ohne Lagerort am Ende."""
    st = _stocktake(conn, stocktake_id)
    if st["status"] != "open":
        raise ConflictError("Eine Zählliste gibt es nur für die offene Inventur.", code="not_open")
    groups: dict = {}
    for r in _items(conn, st):
        if r["archived"]:
            continue
        pack_g, pack_label = stock.pack_of(r)
        if r["type"] == "aid":
            pack = r["unit_label"] or "VE"
        elif pack_g:
            pack = f"{pack_label} = {stock.kg_text(pack_g)} kg"
        else:
            pack = "kg"
        entry = {"number": r["number"], "name": r["name"], "pack": pack, "aid": r["type"] == "aid"}
        locs = _locations_of(r)
        if not locs:
            groups.setdefault((1, 0, NO_LOCATION), []).append(dict(entry, label=None))
        for loc in locs:
            groups.setdefault((0, loc["sort"], loc["name"]), []).append(dict(entry, label=loc["label"]))
    out = [{"location": key[2], "items": sorted(items, key=lambda i: i["number"])}
           for key, items in sorted(groups.items())]
    return {"stocktake": _head(st), "groups": out}


# -- Export .xlsx (Abschnitt 5.6) -----------------------------------------------------------------

def _qty_cell(ln) -> tuple[float | None, str]:
    qty = ln["value_qty"] if ln["counted"] is None else ln["counted"]
    if qty is None:
        return None, ""
    if ln["type"] == "aid":
        return qty / AID_UNIT, ln["pack_label"] or "VE"
    return qty / 1000, "kg"


def _pack_cell(ln) -> str:
    """Gezählte Menge in Gebinden: „3 Sack + 12,5 kg“ (O-5); ungezählt: Gebindegröße."""
    if ln["type"] == "aid" or not ln["pack_g"]:
        return ""
    if ln["counted"] is None:
        return f"{ln['pack_label']} = {stock.kg_text(ln['pack_g'])} kg"
    packs, rest = divmod(ln["counted"], ln["pack_g"])
    if not packs:
        return ""
    return f"{packs} {ln['pack_label']}" + (f" + {stock.kg_text(rest)} kg" if rest else "")


def _local(utc_text: str | None) -> str:
    """Zeitstempel (UTC wie gespeichert) → Ortszeit „TT.MM.JJJJ HH:MM“ (Zeitzone vom Add-on, logsetup)."""
    if not utc_text:
        return ""
    when = datetime.strptime(utc_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
    return when.strftime("%d.%m.%Y %H:%M")


def export_xlsx(conn: sqlite3.Connection, stocktake_id: int) -> tuple[bytes, str]:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    st = _stocktake(conn, stocktake_id)
    if st["status"] != "closed":
        raise ConflictError("Export erst nach dem Abschluss (Preis und Wert stehen dann fest).", code="not_closed")
    lines = _stored_lines(conn, stocktake_id)
    totals = _totals(lines)
    euro = '#,##0.00 "€"'
    bold = Font(bold=True)
    grey = PatternFill("solid", fgColor="EEEEEE")
    yellow = PatternFill("solid", fgColor="FFF3CD")
    wb = Workbook()
    ws = wb.active
    ws.title = "Inventur"
    ws.append([st["name"]])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Stichtag", date_text(st["stichtag"]), "", "Abgeschlossen", _local(st["closed_at"])])
    ws.append([])
    head = ["Nr.", "Name", "Menge", "Einheit", "Gebinde", "Preis €", "je", "Wert €", "Hinweis"]
    ws.append(head)
    for c in ws[ws.max_row]:
        c.font = bold
        c.fill = grey

    def section(title: str, rows: list[dict], subtotal: int, label: str) -> None:
        ws.append([title])
        ws.cell(row=ws.max_row, column=1).font = bold
        for ln in rows:
            qty, unit = _qty_cell(ln)
            hint = []
            if ln["counted"] is None:
                hint.append("nicht gezählt – auf 0" if ln["action"] == "zero" else "nicht gezählt – Buchbestand")
            if ln["missing_price"]:
                hint.append("ohne Preis")
            ws.append([ln["number"], ln["name"], qty, unit, _pack_cell(ln),
                       None if ln["price_cents"] is None else ln["price_cents"] / 100,
                       (ln["pack_label"] or "VE") if ln["type"] == "aid" else "kg",
                       None if ln["value_cents"] is None else ln["value_cents"] / 100, ", ".join(hint)])
            r = ws.max_row
            ws.cell(row=r, column=3).number_format = "#,##0.000" if ln["type"] != "aid" else "#,##0.###"
            ws.cell(row=r, column=6).number_format = euro
            ws.cell(row=r, column=8).number_format = euro
            if ln["missing_price"]:
                for col in range(1, len(head) + 1):
                    ws.cell(row=r, column=col).fill = yellow
        ws.append(["", label, None, None, None, None, None, subtotal / 100])
        r = ws.max_row
        ws.cell(row=r, column=2).font = bold
        ws.cell(row=r, column=8).font = bold
        ws.cell(row=r, column=8).number_format = euro
        ws.append([])

    materials = [ln for ln in lines if ln["type"] != "aid"]
    aids = [ln for ln in lines if ln["type"] == "aid"]
    section("Rohstoffe", materials, totals["materials_cents"], "Zwischensumme Rohstoffe")
    section("Hilfs- und Betriebsstoffe", aids, totals["aids_cents"], "Zwischensumme Hilfs- und Betriebsstoffe")
    missing = totals["missing_price_count"]
    ws.append(["", "Gesamtsumme" + (f" (ohne {missing} Position{'en' if missing != 1 else ''} ohne Preis, "
                                    "siehe Blatt „ohne Preis“)" if missing else ""),
               None, None, None, None, None, totals["total_cents"] / 100])
    r = ws.max_row
    for col in (2, 8):
        ws.cell(row=r, column=col).font = Font(bold=True, size=12)
    ws.cell(row=r, column=8).number_format = euro
    for col, width in zip("ABCDEFGHI", (7, 36, 11, 9, 18, 10, 8, 13, 30)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A5"

    ws2 = wb.create_sheet("ohne Preis")
    ws2.append(["Rohstoffe und Hilfs- und Betriebsstoffe ohne Preis – Wert fehlt in der Summe"])
    ws2["A1"].font = bold
    ws2.append(["Nr.", "Name", "Art", "Menge", "Einheit"])
    for c in ws2[2]:
        c.font = bold
        c.fill = grey
    for ln in lines:
        if ln["missing_price"]:
            qty, unit = _qty_cell(ln)
            ws2.append([ln["number"], ln["name"], "Hilfs- und Betriebsstoff" if ln["type"] == "aid" else "Rohstoff",
                        qty, unit])
    if not missing:
        ws2.append(["", "Alle gezählten Positionen haben einen Preis."])
    for col, width in zip("ABCDE", (7, 36, 24, 11, 9)):
        ws2.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", st["name"]).strip("_") or "Inventur"
    return buf.getvalue(), f"Inventur_{st['stichtag']}_{safe}.xlsx"
