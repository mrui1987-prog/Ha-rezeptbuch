"""Strichcode-Scanner, Teil S1 (Modul 03, docs/strichcode.md): Codes, Lagerorte, Einkäufe.

Code-Normierung (docs/strichcode.md 3, K03-62): EAN-8/-13, UPC-A/-E und GTIN-14 werden mit gültiger
Prüfziffer auf 14 Stellen gebracht; bei GS1-Codes (Code 128 mit (01)) zählt nur die GTIN, Charge und MHD
werden verworfen. Alle anderen Codes (Code 39, Code 128 ohne GS1, QR) bleiben Text.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta

from ..db import transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from .models import AID_UNIT, MAX_GRAMS, MAX_UNIT_LABEL, normalize_text
from . import stock

MAX_CODE = 100
_GS1_PREFIXES = ("]C1", "]e0", "]d2", "]Q3")       # Symbologie-Kennung, die manche Leser voranstellen
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


# -- Normierung ----------------------------------------------------------------------

def gtin_valid(digits: str) -> bool:
    """Prüfziffer nach GS1 (Gewichte 3/1 von rechts)."""
    if not digits.isdigit() or len(digits) not in (8, 12, 13, 14):
        return False
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def upce_to_upca(code: str) -> str | None:
    """UPC-E (8 Stellen mit Nummernsystem und Prüfziffer) → UPC-A (12 Stellen)."""
    if len(code) != 8 or not code.isdigit() or code[0] not in "01":
        return None
    ns, d, check = code[0], code[1:7], code[7]
    last = d[5]
    if last in "012":
        body = d[0:2] + last + "0000" + d[2:5]
    elif last == "3":
        body = d[0:3] + "00000" + d[3:5]
    elif last == "4":
        body = d[0:4] + "00000" + d[4]
    else:
        body = d[0:5] + "0000" + last
    return ns + body + check


def normalize(raw, fmt: str | None = None) -> str:
    """Gelesener Code → gespeicherter Schlüssel (14-stellige GTIN oder Text)."""
    if not isinstance(raw, str):
        raise ValidationError("Code fehlt.", field="code")
    text = raw.strip()
    for prefix in _GS1_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    # GS1 in Klammerschreibweise: (01)04012345678901(10)…(17)…
    m = re.match(r"^\(01\)(\d{14})", text)
    if m and gtin_valid(m.group(1)):
        return m.group(1)
    compact = _CONTROL.sub("", text)
    fmt = (fmt or "").lower()
    if compact.isdigit():
        if fmt in ("upc_e", "upce") and len(compact) == 8:
            upca = upce_to_upca(compact)
            if upca and gtin_valid(upca):
                return upca.zfill(14)
        if len(compact) in (8, 12, 13, 14) and gtin_valid(compact):
            return compact.zfill(14)
    # GS1-128 ohne Klammern: AI 01 + GTIN-14 + weitere Felder (Charge, MHD werden weggelassen)
    if fmt in ("code_128", "code128", "gs1", "") and len(compact) > 16 and compact.startswith("01") \
            and compact[2:16].isdigit() and gtin_valid(compact[2:16]):
        return compact[2:16]
    if not compact:
        raise ValidationError("Code fehlt.", field="code")
    if len(compact) > MAX_CODE:
        raise ValidationError(f"Code höchstens {MAX_CODE} Zeichen.", field="code")
    return compact


def display(code: str) -> str:
    """Anzeige: GTIN-14 mit führender 0 als EAN-13."""
    return code[1:] if len(code) == 14 and code.isdigit() and code[0] == "0" else code


# -- Nachschlagen --------------------------------------------------------------------

def _material(conn, raw_material_id: int) -> dict:
    row = stock._row(conn, raw_material_id)
    pack_g, pack_label = stock.pack_of(row)
    r = conn.execute(
        "SELECT r.number, r.display_name, r.price_cents_per_kg, r.location1_label, r.location2_label, "
        "l1.name AS location1_name, l2.name AS location2_name FROM raw_material r "
        "LEFT JOIN storage_location l1 ON l1.id = r.location1_id "
        "LEFT JOIN storage_location l2 ON l2.id = r.location2_id WHERE r.id = ?", (raw_material_id,)).fetchone()
    locations = [n + (f" ({lab})" if lab else "") for n, lab in
                 ((r["location1_name"], r["location1_label"]), (r["location2_name"], r["location2_label"])) if n]
    return {"id": row["id"], "number": r["number"], "name": row["name"], "display_name": r["display_name"],
            "type": row["type"], "archived": bool(row["archived"]), "stock_g": row["stock_g"],
            "stock_alert_g": row["stock_alert_g"], "stock_status": stock.status(row["stock_g"], row["stock_alert_g"]),
            "unit_size_g": row["unit_size_g"], "unit_label": row["unit_label"],
            "delivery_pack_g": row["delivery_pack_g"], "delivery_pack_label": row["delivery_pack_label"],
            "pack_g": pack_g, "pack_label": pack_label, "price_cents_per_kg": r["price_cents_per_kg"],
            "locations": locations, "is_deposit": bool(row["is_deposit"]),
            "stock_ref_name": row["stock_ref_name"]}


def lookup(conn: sqlite3.Connection, raw: str, fmt: str | None = None) -> dict:
    """``known`` (Rohstoff), ``location`` (Lagerort-Code) oder ``unknown``."""
    code = normalize(raw, fmt)
    hit = conn.execute("SELECT raw_material_id FROM raw_material_barcode WHERE code = ?", (code,)).fetchone()
    if hit:
        material = _material(conn, hit["raw_material_id"])
        material["movements"] = stock.movements(conn, hit["raw_material_id"], limit=5)
        return {"status": "known", "code": code, "code_text": display(code), "raw_material": material}
    loc = conn.execute("SELECT id, name FROM storage_location WHERE code = ?", (code,)).fetchone()
    if loc:
        return {"status": "location", "code": code, "code_text": display(code), "location": dict(loc)}
    return {"status": "unknown", "code": code, "code_text": display(code)}


def candidates(conn: sqlite3.Connection, search: str = "", location_id: int | None = None,
               limit: int = 30) -> list[dict]:
    """Auswahl beim unbekannten Code (O-7): Einträge ohne Code und am gewählten Lagerort zuerst."""
    rows = conn.execute(
        "SELECT r.id, r.number, r.name, r.display_name, r.type, r.unit_size_g, r.unit_label, r.delivery_pack_g, "
        "r.delivery_pack_label, r.location1_id, r.location2_id, "
        "(SELECT count(*) FROM raw_material_barcode c WHERE c.raw_material_id = r.id) AS codes "
        "FROM raw_material r WHERE r.archived = 0 ORDER BY r.number").fetchall()
    needle = normalize_text(search or "").casefold()
    out = []
    for r in rows:
        if needle and needle not in str(r["number"]) and needle not in r["name"].casefold() \
                and not (r["display_name"] and needle in r["display_name"].casefold()):
            continue
        at_location = location_id is not None and location_id in (r["location1_id"], r["location2_id"])
        out.append((0 if at_location else 1, 1 if r["codes"] else 0, r["number"],
                    {"id": r["id"], "number": r["number"], "name": r["name"], "type": r["type"],
                     "has_code": bool(r["codes"]), "unit_size_g": r["unit_size_g"], "unit_label": r["unit_label"],
                     "delivery_pack_g": r["delivery_pack_g"], "delivery_pack_label": r["delivery_pack_label"]}))
    out.sort(key=lambda x: x[:3])
    return [x[3] for x in out[:max(1, min(limit, 200))]]


def list_for(conn: sqlite3.Connection, raw_material_id: int) -> list[dict]:
    stock._row(conn, raw_material_id)
    rows = conn.execute("SELECT id, code, format, created_at FROM raw_material_barcode WHERE raw_material_id = ? "
                        "ORDER BY id", (raw_material_id,)).fetchall()
    return [dict(r, code_text=display(r["code"])) for r in rows]


# -- Zuordnen ------------------------------------------------------------------------

def _int_id(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError("Ungültige Auswahl.", field=field)
    return value


def _format(value) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 30:
        raise ValidationError("Ungültiges Format.", field="format")
    return value


def _pack_input(payload: dict, row) -> dict:
    """Gebinde beim ersten Scan (Michael 23:31, H-F): nur wenn am Rohstoff noch leer."""
    if payload.get("pack_g") in (None, "") and payload.get("pack_label") in (None, ""):
        return {}
    if row["type"] in ("aid", "goods"):
        size = AID_UNIT
    else:
        size = payload.get("pack_g")
        if isinstance(size, str) and size.strip().isdigit():
            size = int(size.strip())
        if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_GRAMS:
            raise ValidationError(f"Gebindegröße in g zwischen 1 und {MAX_GRAMS}.", field="pack_g")
    label = payload.get("pack_label")
    label = normalize_text(label) if isinstance(label, str) else ""
    if not label or len(label) > MAX_UNIT_LABEL:
        raise ValidationError("Bitte die Bezeichnung angeben (z. B. Sack).", field="pack_label")
    if row["unit_size_g"] is not None:
        raise ConflictError("Das Gebinde ist schon hinterlegt; ändern nur auf der Rohstoffseite (PIN).",
                            code="pack_set")
    return {"unit_size_g": size, "unit_label": label}


def _set_pack(conn, raw_material_id: int, pack: dict) -> None:
    if pack:
        conn.execute("UPDATE raw_material SET unit_size_g = ?, unit_label = ?, "
                     "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                     (pack["unit_size_g"], pack["unit_label"], raw_material_id))
        conn.execute("INSERT INTO change_log (source, entity, entity_id, action, old_values, new_values) "
                     "VALUES ('system', 'raw_material', ?, 'update', NULL, ?)",
                     (raw_material_id, f'{{"unit_size_g": {pack["unit_size_g"]}}}'))


def assign(conn: sqlite3.Connection, payload: dict) -> dict:
    """Erstes Zuordnen ohne PIN (S4); ist der Code schon bei einem anderen Rohstoff → 409 (Umhängen mit PIN)."""
    code = normalize(payload.get("code"), payload.get("format"))
    rm_id = _int_id(payload.get("raw_material_id"), "raw_material_id")
    fmt = _format(payload.get("format"))
    with transaction(conn):
        row = stock._row(conn, rm_id)
        if row["archived"]:
            raise ConflictError(f"„{row['name']}“ ist archiviert.", code="archived")
        pack = _pack_input(payload, row)
        if conn.execute("SELECT 1 FROM storage_location WHERE code = ?", (code,)).fetchone():
            raise ConflictError("Dieser Code gehört zu einem Lagerort.", code="code_is_location")
        hit = conn.execute("SELECT b.raw_material_id, r.name FROM raw_material_barcode b JOIN raw_material r "
                           "ON r.id = b.raw_material_id WHERE b.code = ?", (code,)).fetchone()
        if hit and hit["raw_material_id"] != rm_id:
            raise ConflictError(f"Der Code gehört schon zu „{hit['name']}“. Umhängen nur mit PIN.",
                                code="code_taken", raw_material_id=hit["raw_material_id"])
        if not hit:
            conn.execute("INSERT INTO raw_material_barcode (raw_material_id, code, format) VALUES (?, ?, ?)",
                         (rm_id, code, fmt))
        _set_pack(conn, rm_id, pack)
    return lookup(conn, code)


def set_pack(conn: sqlite3.Connection, raw_material_id: int, payload: dict) -> dict:
    """Bekannter Code ohne Gebinde: Gebinde einmal abfragen und speichern (ohne PIN, nur wenn leer)."""
    with transaction(conn):
        row = stock._row(conn, raw_material_id)
        pack = _pack_input(payload, row)
        if not pack:
            raise ValidationError("Bitte Gebindegröße und Bezeichnung angeben.", field="pack_g")
        _set_pack(conn, raw_material_id, pack)
    return _material(conn, raw_material_id)


def reassign(conn: sqlite3.Connection, raw: str, payload: dict) -> dict:
    """Umhängen eines Codes (PIN, S4)."""
    code = normalize(raw, payload.get("format"))
    rm_id = _int_id(payload.get("raw_material_id"), "raw_material_id")
    with transaction(conn):
        row = stock._row(conn, rm_id)
        if row["archived"]:
            raise ConflictError(f"„{row['name']}“ ist archiviert.", code="archived")
        cur = conn.execute("UPDATE raw_material_barcode SET raw_material_id = ?, "
                           "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE code = ?", (rm_id, code))
        if cur.rowcount == 0:
            raise NotFoundError("Code nicht gefunden.", code="not_found")
    return lookup(conn, code)


def delete_code(conn: sqlite3.Connection, barcode_id: int) -> None:
    with transaction(conn):
        if conn.execute("DELETE FROM raw_material_barcode WHERE id = ?", (barcode_id,)).rowcount == 0:
            raise NotFoundError("Code nicht gefunden.", code="not_found")


# -- Lagerorte (M03-25, H-C) -----------------------------------------------------------

def list_locations(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    sql = ("SELECT l.id, l.name, l.code, l.sort, l.archived, (SELECT count(*) FROM raw_material r WHERE r.archived = 0 "
           "AND (r.location1_id = l.id OR r.location2_id = l.id)) AS materials FROM storage_location l"
           + ("" if include_archived else " WHERE l.archived = 0") + " ORDER BY l.sort, l.name")
    return [dict(r, archived=bool(r["archived"]),
                 code_text=display(r["code"]) if r["code"] else None) for r in conn.execute(sql)]


def _location_values(conn, payload: dict, current: dict | None) -> dict:
    out = {}
    if "name" in payload or current is None:
        name = payload.get("name")
        name = normalize_text(name) if isinstance(name, str) else ""
        if not name or len(name) > 40:
            raise ValidationError("Name des Lagerorts (1 bis 40 Zeichen).", field="name")
        out["name"] = name
    if "code" in payload:
        out["code"] = None if payload["code"] in (None, "") else normalize(payload["code"], payload.get("format"))
        if out["code"] and conn.execute("SELECT 1 FROM raw_material_barcode WHERE code = ?",
                                        (out["code"],)).fetchone():
            raise ConflictError("Der Code gehört schon zu einem Rohstoff.", field="code", code="code_taken")
    if "sort" in payload:
        if isinstance(payload["sort"], bool) or not isinstance(payload["sort"], int):
            raise ValidationError("Reihenfolge als ganze Zahl.", field="sort")
        out["sort"] = payload["sort"]
    if "archived" in payload:
        out["archived"] = 1 if payload["archived"] is True else 0
    return out


def create_location(conn: sqlite3.Connection, payload: dict) -> dict:
    with transaction(conn):
        values = _location_values(conn, payload, None)
        try:
            new_id = conn.execute("INSERT INTO storage_location (" + ", ".join(values) + ") VALUES ("
                                  + ", ".join("?" * len(values)) + ")", tuple(values.values())).lastrowid
        except sqlite3.IntegrityError:
            raise ConflictError("Diesen Lagerort oder Code gibt es schon.", field="name", code="location_taken") from None
    return next(loc for loc in list_locations(conn, True) if loc["id"] == new_id)


def update_location(conn: sqlite3.Connection, location_id: int, payload: dict) -> dict:
    with transaction(conn):
        if not conn.execute("SELECT 1 FROM storage_location WHERE id = ?", (location_id,)).fetchone():
            raise NotFoundError("Lagerort nicht gefunden.", code="not_found")
        values = _location_values(conn, payload, {})
        if values:
            try:
                conn.execute("UPDATE storage_location SET " + ", ".join(f"{k} = ?" for k in values)
                             + ", updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                             (*values.values(), location_id))
            except sqlite3.IntegrityError:
                raise ConflictError("Diesen Lagerort oder Code gibt es schon.", field="name",
                                    code="location_taken") from None
    return next(loc for loc in list_locations(conn, True) if loc["id"] == location_id)


# -- Einkäufe (O-1 geändert: kein +1 ohne Beleg) ---------------------------------------

def list_purchases(conn: sqlite3.Connection, days: int = 3) -> list[dict]:
    since = (date.today() - timedelta(days=max(0, min(days, 30)))).isoformat()
    rows = conn.execute(
        "SELECT p.id, p.label, p.purchase_date, p.created_at, count(m.id) AS bookings FROM purchase p "
        "LEFT JOIN stock_movement m ON m.purchase_id = p.id WHERE p.purchase_date >= ? "
        "GROUP BY p.id ORDER BY p.purchase_date DESC, p.id DESC", (since,)).fetchall()
    today = date.today().isoformat()
    return [dict(r, today=r["purchase_date"] == today) for r in rows]


def create_purchase(conn: sqlite3.Connection, payload: dict) -> dict:
    label = payload.get("label")
    label = normalize_text(label) if isinstance(label, str) else ""
    if not label or len(label) > 60:
        raise ValidationError("Bitte angeben, wo eingekauft wurde (z. B. Metro).", field="label")
    device = stock._device(payload.get("device_id"), required=False)
    with transaction(conn):
        new_id = conn.execute("INSERT INTO purchase (label, purchase_date, device_id) VALUES (?, ?, ?)",
                              (label, date.today().isoformat(), device)).lastrowid
    return next(p for p in list_purchases(conn, 0) if p["id"] == new_id)
