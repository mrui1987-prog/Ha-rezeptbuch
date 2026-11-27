"""Handelsware und Pfand, Teil H1 (Modul 03, docs/handelsware.md, K03-85 bis K03-93).

* „Verschieben nach …“ / „Kopieren nach …“ zwischen den Arten (K03-89): Rohstoff (Standard/Mehl), Hilfs- und
  Betriebsstoff, Handelsware, Sonstiger Artikel. Verschieben ändert die Art desselben Artikels (Bezugsquelle, Belege,
  Verlauf bleiben dran); Kopieren legt einen neuen Artikel an, der alte bleibt. Ein Rohstoff in Rezepten oder
  Stücklisten lässt sich nur kopieren.
* Rohstoff + Handelsware zugleich (K03-93): nur der Rohstoff führt Bestand; die Handelsware ist ein Verweis mit
  Kassennummer und Gewicht je Stück.
* Pfand-Übersicht in Euro (K03-87): Pfand BÄKO (Lieferungen/Gutschriften), Pfand Kunden (Kassenimport), Differenz.

Mengen: Gramm bei Rohstoffen, Tausendstel bei Hilfs- und Betriebsstoffen (VE) und Handelsware (Stück).
"""

from __future__ import annotations

import sqlite3

from ..booking import service as booking
from ..db import transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from . import service, sources, stock
from .models import GOODS_UNIT, TYPE_TEXT, normalize_text

GRAM_TYPES = ("standard", "flour")
UNIT_TYPES = ("aid", "goods")
TARGETS = ("standard", "flour", "aid", "goods", "other")
TARGET_TEXT = dict(TYPE_TEXT, standard="Rohstoff", flour="Rohstoff (Mehl)", other="Sonstiger Artikel")
SOURCE = "admin"


# -- Hilfen ----------------------------------------------------------------------------

def _target(payload: dict) -> str:
    to = payload.get("to")
    if to not in TARGETS:
        raise ValidationError("Ziel: Rohstoff, Hilfs- und Betriebsstoff, Handelsware oder Sonstiger Artikel.", field="to")
    return to


def _pos_int(value, field: str, label: str, *, required: bool, maximum: int = 1_000_000) -> int | None:
    if isinstance(value, str):
        value = value.strip().replace(".", "")
        value = int(value) if value.isdigit() else (None if value == "" else value)
    if value is None:
        if required:
            raise ValidationError(f"{label} fehlt.", field=field, code=f"{field}_missing")
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise ValidationError(f"{label}: ganze Zahl größer 0.", field=field)
    return value


def _row(conn, rm_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM raw_material WHERE id = ?", (rm_id,)).fetchone()
    if row is None:
        raise NotFoundError("Artikel nicht gefunden.", code="not_found")
    return row


def _locked(conn, rm_id: int) -> bool:
    """In Rezepten, Aufträgen, Chargen oder Stücklisten verwendet → nur kopieren (K03-89)."""
    return service.usage(conn, rm_id)["used"] or service._in_articles(conn, rm_id)


def _scale(value: int | None, num: int, den: int) -> int | None:
    if value is None:
        return None
    q, r = divmod(value * num, den)
    return q + (1 if 2 * r >= den else 0)


def _log(conn, action: str, rm_id: int, old, new) -> None:
    service._log(conn, action, rm_id, old, new, SOURCE)


def _free_name(conn, name: str, type_: str) -> str:
    """Name für die Kopie: gleicher Name, wenn frei (Handelsware zählt getrennt), sonst mit „(Kopie)“."""
    base = normalize_text(name)[:90]
    candidate, n = base, 1
    while service._find_active_with_name(conn, candidate, type_=type_) is not None:
        n += 1
        candidate = f"{base} (Kopie{'' if n == 2 else ' ' + str(n - 1)})"
    return candidate


def _tolerance(payload: dict) -> tuple[str, int]:
    from .models import parse_tolerance
    unit = payload.get("tolerance_unit") or "g"
    if unit not in ("g", "percent"):
        raise ValidationError("Toleranzeinheit g oder %.", field="tolerance_unit")
    return unit, parse_tolerance(payload.get("tolerance", 5), unit)


# -- Verschieben ------------------------------------------------------------------------

def move(conn: sqlite3.Connection, rm_id: int, payload: dict) -> dict:
    """Art desselben Artikels ändern. payload: ``to``; Gramm ↔ Stück/VE mit ``piece_g`` (g je Stück bzw. VE,
    rechnet Bestand, Preis und Bezugsquellen um – ohne Angabe endet die Bestandsführung); VE ↔ Stück mit
    ``factor`` (Stück je VE, Vorgabe 1); zu Rohstoff ``tolerance``; zu Sonstiger Artikel: BÄKO-Artikelnummer nötig."""
    to = _target(payload)
    with transaction(conn):
        row = _row(conn, rm_id)
        if row["archived"]:
            raise ConflictError(f"„{row['name']}“ ist archiviert.", code="archived")
        if to == row["type"]:
            raise ConflictError(f"„{row['name']}“ ist schon {TARGET_TEXT[to]}.", code="same_type")
        if (to in UNIT_TYPES or to == "other") and _locked(conn, rm_id):
            raise ConflictError(f"„{row['name']}“ steckt in Rezepten oder Stücklisten – nur „Kopieren nach …“ "
                                "(K03-89).", code="move_locked")
        if to == "other":
            return _move_to_other(conn, row)
        if row["stock_ref_id"] is not None and to != "goods":
            conn.execute("UPDATE raw_material SET stock_ref_id = NULL, piece_g = NULL WHERE id = ?", (rm_id,))
            row = _row(conn, rm_id)
        old_family = "g" if row["type"] in GRAM_TYPES else "u"
        new_family = "g" if to in GRAM_TYPES else "u"
        num, den, ended = 1, 1, False
        if old_family != new_family:
            piece = _pos_int(payload.get("piece_g"), "piece_g", "Gewicht je Stück/VE in g", required=False)
            if piece is None:
                ended = True
            elif old_family == "g":                   # Gramm → Tausendstel Stück
                num, den = GOODS_UNIT, piece
            else:                                     # Tausendstel Stück → Gramm
                num, den = piece, GOODS_UNIT
        elif old_family == "u":
            factor = _pos_int(payload.get("factor"), "factor", "Stück je VE", required=False, maximum=10000) or 1
            num, den = (factor, 1) if to == "goods" else (1, factor)
        fields = {"type": to}
        if to in UNIT_TYPES:
            fields.update(tolerance_unit="g", tolerance_value=0, unit_size_g=GOODS_UNIT,
                          unit_label="Stück" if to == "goods" else (row["unit_label"] if row["type"] == "aid" else "VE"),
                          delivery_pack_g=None, delivery_pack_label=None)
            if row["type"] == "goods" and to == "aid":
                fields["unit_label"] = "VE"
        else:
            if row["type"] in UNIT_TYPES:
                unit, tol = _tolerance(payload)
                fields.update(tolerance_unit=unit, tolerance_value=tol, unit_size_g=None, unit_label=None)
        if to != "goods":
            fields.update(is_deposit=0, register_no=None, stock_ref_id=None, piece_g=None)
        else:
            if isinstance(payload.get("is_deposit"), bool):
                fields["is_deposit"] = 1 if payload["is_deposit"] else 0
        same = service._find_active_with_name(conn, row["name"], exclude_id=rm_id, type_=to)
        if same is not None:
            raise ConflictError(f"In der Zielart gibt es schon „{same['name']}“ (Nummer {same['number']}).",
                                code="name_taken")
        price = None if ended else _scale(row["price_cents_per_kg"], den, num)
        if price is not None and price > 999999:
            price = None
        fields["price_cents_per_kg"] = price
        conn.execute("UPDATE raw_material SET " + ", ".join(f"{c} = ?" for c in fields)
                     + ", updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?", (*fields.values(), rm_id))
        for s in conn.execute("SELECT id, grams_per_unit, price_cents_per_kg FROM raw_material_source "
                              "WHERE raw_material_id = ?", (rm_id,)).fetchall():
            gpu = None if ended else _scale(s["grams_per_unit"], num, den)
            sp = None if ended else _scale(s["price_cents_per_kg"], den, num)
            conn.execute("UPDATE raw_material_source SET grams_per_unit = ?, price_cents_per_kg = ? WHERE id = ?",
                         (gpu if gpu else None, sp if sp is not None and sp <= 999999 else None, s["id"]))
        sources.sync_price_in_tx(conn, rm_id, SOURCE)
        note = f"Verschoben: {TARGET_TEXT[row['type']]} → {TARGET_TEXT[to]}"
        if row["stock_g"] is not None:
            after = None if ended else _scale(row["stock_g"], num, den)
            if after is None and to == "goods":
                after = 0
            if after != row["stock_g"]:
                stock._book(conn, rm_id, "inventory", row["stock_g"], after, source=SOURCE,
                            note=note + (" – Bestand neu zählen" if ended else " – Bestand umgerechnet"))
        if row["stock_alert_g"] is not None:
            conn.execute("UPDATE raw_material SET stock_alert_g = ? WHERE id = ?",
                         (None if ended else _scale(row["stock_alert_g"], num, den), rm_id))
        _log(conn, "update", rm_id, {"type": row["type"]}, dict(fields, note=note))
    return {"raw_material": service.get_raw_material(conn, rm_id), "stock_ended": ended and row["stock_g"] is not None}


def _move_to_other(conn, row) -> dict:
    src = conn.execute("SELECT * FROM raw_material_source WHERE raw_material_id = ? AND article_no IS NOT NULL "
                       "ORDER BY is_active DESC LIMIT 1", (row["id"],)).fetchone()
    if src is None:
        raise ConflictError("Sonstige Artikel hängen an der BÄKO-Artikelnummer – dieser Artikel hat keine.",
                            code="article_no_missing")
    other = conn.execute("SELECT id FROM other_article WHERE dealer_id = ? AND article_no = ?",
                         (src["dealer_id"], src["article_no"])).fetchone()
    if other is None:
        other_id = conn.execute(
            "INSERT INTO other_article (dealer_id, article_no, description, last_unit, booking_group_id, "
            "booking_group_checked) VALUES (?, ?, ?, ?, ?, ?)",
            (src["dealer_id"], src["article_no"], row["name"], src["unit_code"], row["booking_group_id"],
             row["booking_group_checked"])).lastrowid
    else:
        other_id = other["id"]
        conn.execute("UPDATE other_article SET archived = 0 WHERE id = ?", (other_id,))
    conn.execute("UPDATE receiving_line SET target = 'other', other_article_id = ?, raw_material_id = NULL "
                 "WHERE raw_material_id = ? AND target = 'raw_material' AND stock_movement_id IS NULL "
                 "AND delivered_qty_milli = 0 AND state IN ('open', 'backorder')", (other_id, row["id"]))
    conn.execute("UPDATE raw_material_source SET article_no = NULL WHERE raw_material_id = ?", (row["id"],))
    if row["stock_g"] is not None:
        stock._book(conn, row["id"], "inventory", row["stock_g"], None, source=SOURCE,
                    note="Verschoben nach „Sonstiger Artikel“ – ohne Bestand")
    service.archive_in_tx(conn, row["id"], SOURCE)
    return {"other_article_id": other_id, "archived_raw_material_id": row["id"]}


# -- Kopieren --------------------------------------------------------------------------

def copy(conn: sqlite3.Connection, rm_id: int, payload: dict) -> dict:
    """Neuen Artikel in der anderen Art anlegen, der alte bleibt (K03-89). Rohstoff → Handelsware: Verweis mit
    ``piece_g`` (nur der Rohstoff führt Bestand, K03-93). Handelsware → Rohstoff: der neue Rohstoff übernimmt
    Bestand, Bezugsquellen und Codes, die Handelsware wird Verweis mit Kassennummer."""
    to = _target(payload)
    if to == "other":
        raise ValidationError("Sonstige Artikel haben keinen Bestand – bitte „Verschieben nach …“.", field="to")
    with transaction(conn):
        row = _row(conn, rm_id)
        if row["archived"]:
            raise ConflictError(f"„{row['name']}“ ist archiviert.", code="archived")
        if to == row["type"]:
            raise ConflictError("Kopieren in dieselbe Art geht nicht.", code="same_type")
        name = payload.get("name")
        name = normalize_text(name) if isinstance(name, str) and name.strip() else _free_name(conn, row["name"], to)
        data = {"name": name, "type": to, "display_name": row["display_name"]}
        for n in (1, 2):
            if row[f"location{n}_id"] is not None:
                data[f"location{n}_id"] = row[f"location{n}_id"]
                data[f"location{n}_label"] = row[f"location{n}_label"]
        if to in GRAM_TYPES:
            data.update(tolerance=payload.get("tolerance", 5), tolerance_unit=payload.get("tolerance_unit") or "g")
        if to == "aid":
            data["unit_label"] = row["unit_label"] if row["type"] == "aid" else "VE"
        if to == "goods":
            if payload.get("register_no") not in (None, ""):
                data["register_no"] = payload["register_no"]
            if isinstance(payload.get("is_deposit"), bool):
                data["is_deposit"] = payload["is_deposit"]
        if to == "goods" and row["type"] in GRAM_TYPES:
            # K03-93: Handelsware als Verweis, Bestand bleibt beim Rohstoff
            piece = _pos_int(payload.get("piece_g"), "piece_g", "Gewicht je Stück in g", required=True)
            data.update(stock_ref_id=rm_id, piece_g=piece, start_stock=False)
            new_id = service.create_in_tx(conn, data, SOURCE)
            return {"raw_material": service.get_raw_material(conn, new_id), "reference": True}
        if to in GRAM_TYPES and row["type"] == "goods":
            if row["stock_ref_id"] is not None:
                raise ConflictError("Diese Handelsware verweist schon auf einen Rohstoff.", code="already_reference")
            piece = _pos_int(payload.get("piece_g"), "piece_g", "Gewicht je Stück in g", required=True)
            data["price_per_kg"] = None
            new_id = service.create_in_tx(conn, data, SOURCE)
            _take_over(conn, row, new_id, piece)
            return {"raw_material": service.get_raw_material(conn, new_id), "reference": True,
                    "goods": service.get_raw_material(conn, rm_id)}
        if to == "goods":
            data["start_stock"] = True
        new_id = service.create_in_tx(conn, data, SOURCE)
        return {"raw_material": service.get_raw_material(conn, new_id), "reference": False}


def _take_over(conn, goods, new_id: int, piece: int) -> None:
    """Handelsware → neuer Rohstoff (K03-93): Bestand, Bezugsquellen, Codes und Preis wandern zum Rohstoff."""
    before = goods["stock_g"]
    if before is not None:
        grams = _scale(before, piece, GOODS_UNIT)
        stock._book(conn, goods["id"], "inventory", before, None, source=SOURCE,
                    note="Bestand zum Rohstoff übertragen (Rohstoff + Handelsware, K03-93)")
        stock._book(conn, new_id, "receipt", None, grams, source=SOURCE,
                    note=f"Bestand von Handelsware „{goods['name']}“ übernommen ({before / GOODS_UNIT:g} Stück)")
    for s in conn.execute("SELECT * FROM raw_material_source WHERE raw_material_id = ?", (goods["id"],)).fetchall():
        gpu = _scale(s["grams_per_unit"], piece, GOODS_UNIT) if s["grams_per_unit"] else None
        if gpu is None and (s["unit_code"] or "ST").upper() == "ST":
            gpu = piece
        price = _scale(s["price_cents_per_kg"], GOODS_UNIT, piece)
        conn.execute("UPDATE raw_material_source SET raw_material_id = ?, grams_per_unit = ?, price_cents_per_kg = ? "
                     "WHERE id = ?", (new_id, gpu, price if price is not None and price <= 999999 else None, s["id"]))
    sources.sync_price_in_tx(conn, new_id, SOURCE)
    if not sources.has_sources(conn, new_id) and goods["price_cents_per_kg"] is not None:
        price = _scale(goods["price_cents_per_kg"], GOODS_UNIT, piece)
        if price is not None and price <= 999999:
            conn.execute("UPDATE raw_material SET price_cents_per_kg = ? WHERE id = ?", (price, new_id))
    conn.execute("UPDATE raw_material_barcode SET raw_material_id = ? WHERE raw_material_id = ?", (new_id, goods["id"]))
    conn.execute("UPDATE raw_material SET stock_ref_id = ?, piece_g = ?, price_cents_per_kg = NULL, stock_alert_g = NULL "
                 "WHERE id = ?", (new_id, piece, goods["id"]))
    _log(conn, "update", goods["id"], {"stock_ref_id": None}, {"stock_ref_id": new_id, "piece_g": piece})


# -- Sonstige Artikel -------------------------------------------------------------------

def _other(conn, other_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM other_article WHERE id = ?", (other_id,)).fetchone()
    if row is None:
        raise NotFoundError("Sonstiger Artikel nicht gefunden.", code="not_found")
    return row


def other_to(conn: sqlite3.Connection, other_id: int, payload: dict, *, keep: bool) -> dict:
    """Sonstiger Artikel → Rohstoff/HBS/Handelsware. ``keep`` False = verschieben (Belegzeilen und
    BÄKO-Artikelnummer wandern mit, der sonstige Artikel entfällt), True = kopieren (ohne Artikelnummer).
    Handelsware: ``pieces_per_unit`` (Stück je Liefereinheit), ``is_deposit`` (Vorgabe: Gruppe Leergut);
    Rohstoff mit Belegeinheit ≠ kg: ``grams_per_unit``."""
    to = _target(payload)
    if to == "other":
        raise ConflictError("Ist schon ein sonstiger Artikel.", code="same_type")
    with transaction(conn):
        o = _other(conn, other_id)
        name = payload.get("name")
        name = normalize_text(name) if isinstance(name, str) and name.strip() else \
            _free_name(conn, o["description"] or o["article_no"], to)
        data = {"name": name, "type": to}
        unit = (o["last_unit"] or "ST").upper()
        gpu = None
        if to in GRAM_TYPES:
            data.update(tolerance=payload.get("tolerance", 5), tolerance_unit=payload.get("tolerance_unit") or "g")
            if unit != "KG":
                gpu = _pos_int(payload.get("grams_per_unit"), "grams_per_unit", "Gewicht je Einheit in g",
                               required=False)
        elif to == "aid":
            data["unit_label"] = payload.get("unit_label") or "VE"
        else:
            deposit = payload.get("is_deposit")
            data["is_deposit"] = deposit if isinstance(deposit, bool) else o["booking_group_id"] == booking.LEERGUT
            pieces = _pos_int(payload.get("pieces_per_unit"), "pieces_per_unit", "Stück je Liefereinheit",
                              required=False, maximum=10000)
            if pieces is None and unit == "ST":
                pieces = 1
            gpu = pieces * GOODS_UNIT if pieces else None
        new_id = service.create_in_tx(conn, data, SOURCE)
        if o["booking_group_id"]:
            booking.set_article_group(conn, raw_material_id=new_id, group_id=o["booking_group_id"],
                                      checked=bool(o["booking_group_checked"]))
        src = {"dealer_id": o["dealer_id"], "unit_code": unit}
        if gpu:
            src["grams_per_unit"] = gpu
        if not keep:
            src["article_no"] = o["article_no"]
        sources.add_in_tx(conn, new_id, src, SOURCE)
        if not keep:
            conn.execute("UPDATE receiving_line SET target = 'raw_material', raw_material_id = ?, other_article_id = NULL "
                         "WHERE other_article_id = ?", (new_id, other_id))
            conn.execute("DELETE FROM other_article WHERE id = ?", (other_id,))
    return {"raw_material": service.get_raw_material(conn, new_id), "moved": not keep}


# -- Pfand-Übersicht (K03-87) ----------------------------------------------------------

def deposit_overview(conn: sqlite3.Connection, date_from: str | None = None, date_to: str | None = None) -> dict:
    """Pfand in Euro: BÄKO (Rechnungen + / Gutschriften −, Pfand-Artikel oder Gruppe Leergut), Kunden
    (Kassenimport, Pfand-Artikel), gesamt = BÄKO − Kunden. Zeitraum optional (Belegdatum bzw. Importzeitraum)."""
    for v, f in ((date_from, "from"), (date_to, "to")):
        if v and not (isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-"):
            raise ValidationError("Datum im Format JJJJ-MM-TT.", field=f)
    where, params = "", []
    if date_from:
        where += " AND d.doc_date >= ?"
        params.append(date_from)
    if date_to:
        where += " AND d.doc_date <= ?"
        params.append(date_to)
    rows = conn.execute(
        "SELECT d.kind, d.doc_no, d.doc_date, l.line_no, l.description, l.qty_milli, l.unit_code, "
        "coalesce(l.net_book_cents, l.net_cents) AS cents, r.name AS rm_name FROM receiving_line l "
        "JOIN receiving_document d ON d.id = l.document_id LEFT JOIN raw_material r ON r.id = l.raw_material_id "
        "WHERE d.kind IN ('invoice', 'credit_note') AND (r.is_deposit = 1 OR l.booking_group_id = ?)" + where +
        " ORDER BY d.doc_date, d.doc_no, l.line_no", (booking.LEERGUT, *params)).fetchall()
    baeko, lines = 0, []
    for r in rows:
        cents = abs(r["cents"] or 0) * (-1 if r["kind"] == "credit_note" else 1)
        baeko += cents
        lines.append({"kind": r["kind"], "doc_no": r["doc_no"], "doc_date": r["doc_date"], "line_no": r["line_no"],
                      "description": r["rm_name"] or r["description"], "qty_milli": r["qty_milli"],
                      "unit_code": r["unit_code"], "cents": cents})
    w2, p2 = "", []
    if date_from:
        w2 += " AND s.date_to >= ?"
        p2.append(date_from)
    if date_to:
        w2 += " AND s.date_from <= ?"
        p2.append(date_to)
    imports = conn.execute(
        "SELECT s.id, s.date_from, s.date_to, coalesce(sum(CASE WHEN l.is_deposit = 1 THEN l.value_cents END), 0) "
        "AS cents FROM sales_import s LEFT JOIN sales_import_line l ON l.sales_import_id = s.id WHERE 1 = 1" + w2 +
        " GROUP BY s.id ORDER BY s.date_from", p2).fetchall()
    customers = sum(r["cents"] for r in imports)
    return {"baeko_cents": baeko, "customers_cents": customers, "total_cents": baeko - customers,
            "baeko_lines": lines, "imports": [dict(r) for r in imports],
            "date_from": date_from, "date_to": date_to}
