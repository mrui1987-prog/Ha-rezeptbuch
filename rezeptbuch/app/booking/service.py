"""Buchungsgruppen und Export für die Buchführung (Teil B1, docs/buchfuehrung-export.md, freigegeben 23.11.2026).

* Gruppen pflegbar (K03-79), Reihenfolge = Spaltenfolge im Export.
* Gruppe am Artikel (Rohstoff, Hilfs- und Betriebsstoff, sonstiger Artikel), an der Belegposition mitgespeichert (K03-81).
* Lernende Zuordnung je Warengruppe des Händlers; automatisch gesetzte Gruppen sind „ungeprüft“, bis ein Admin sie
  bestätigt (K03-84). Unbekannte Warengruppe ohne Artikelgruppe → beim Einlesen fragen.
* Export .xlsx je Monat nach Belegdatum, 7 %/19 % getrennt, Spalte A (Buchungsnummer) leer (K03-82/K03-83).
"""

from __future__ import annotations

import io
import re
import sqlite3

from ..db import transaction
from ..errors import ConflictError, NotFoundError, ValidationError

LEERGUT, HANDELSWARE, KAFFEE, ROHSTOFFE, UNKOSTEN = 1, 5, 6, 8, 9
# Vorgabe, solange für eine Warengruppe nichts gelernt ist (BÄKO: 1405 Pfand, 1001 Süß-/Handelswaren, 1002 Kaffee)
DEFAULT_BY_COMMODITY = {"1405": LEERGUT, "1001": HANDELSWARE, "1002": KAFFEE}


# -- Gruppen pflegen ------------------------------------------------------------------------

def list_groups(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    sql = "SELECT id, name, short_name, sort, archived FROM booking_group"
    if not include_archived:
        sql += " WHERE archived = 0"
    return [dict(r, archived=bool(r["archived"])) for r in conn.execute(sql + " ORDER BY sort, id")]


def _group(conn, group_id) -> sqlite3.Row:
    if isinstance(group_id, bool) or not isinstance(group_id, int):
        raise ValidationError("Buchungsgruppe fehlt.", field="booking_group_id")
    row = conn.execute("SELECT * FROM booking_group WHERE id = ?", (group_id,)).fetchone()
    if row is None:
        raise NotFoundError("Buchungsgruppe nicht gefunden.", code="not_found")
    return row


def _name(value, field: str, maximum: int) -> str:
    text = (value or "").strip() if isinstance(value, str) else ""
    if not text or len(text) > maximum:
        raise ValidationError(f"Bitte 1 bis {maximum} Zeichen.", field=field)
    if text[0] in "=+-@":
        raise ValidationError("Darf nicht mit = + - @ beginnen.", field=field)
    return text


def save_group(conn: sqlite3.Connection, payload: dict, group_id: int | None = None) -> dict:
    """Anlegen (ohne id) oder ändern: name, short_name, archived. Reihenfolge über move_group."""
    with transaction(conn):
        if group_id is None:
            name = _name(payload.get("name"), "name", 60)
            short = _name(payload.get("short_name") or name, "short_name", 15)
            sort = (conn.execute("SELECT max(sort) FROM booking_group").fetchone()[0] or 0) + 1
            try:
                group_id = conn.execute("INSERT INTO booking_group (name, short_name, sort) VALUES (?, ?, ?)",
                                        (name, short, sort)).lastrowid
            except sqlite3.IntegrityError:
                raise ConflictError(f"Gruppe „{name}“ gibt es schon.", code="duplicate") from None
        else:
            row = _group(conn, group_id)
            name = _name(payload.get("name", row["name"]), "name", 60)
            short = _name(payload.get("short_name", row["short_name"]), "short_name", 15)
            archived = payload.get("archived", bool(row["archived"]))
            if not isinstance(archived, bool):
                raise ValidationError("archiviert: ja/nein.", field="archived")
            try:
                conn.execute("UPDATE booking_group SET name = ?, short_name = ?, archived = ? WHERE id = ?",
                             (name, short, 1 if archived else 0, group_id))
            except sqlite3.IntegrityError:
                raise ConflictError(f"Gruppe „{name}“ gibt es schon.", code="duplicate") from None
    return dict(_group(conn, group_id))


def move_group(conn: sqlite3.Connection, group_id: int, direction: int) -> list[dict]:
    """Eine Stelle nach vorn (−1) oder hinten (+1) – bestimmt die Spaltenfolge im Export."""
    if direction not in (-1, 1):
        raise ValidationError("Richtung −1 oder +1.", field="direction")
    with transaction(conn):
        ids = [r["id"] for r in conn.execute("SELECT id FROM booking_group ORDER BY sort, id")]
        if group_id not in ids:
            raise NotFoundError("Buchungsgruppe nicht gefunden.", code="not_found")
        i = ids.index(group_id)
        j = i + direction
        if 0 <= j < len(ids):
            ids[i], ids[j] = ids[j], ids[i]
        for n, gid in enumerate(ids, start=1):
            conn.execute("UPDATE booking_group SET sort = ? WHERE id = ?", (n, gid))
    return list_groups(conn, include_archived=True)


# -- Zuordnung ------------------------------------------------------------------------------

def learned(conn, dealer_id: int, commodity_group: str | None) -> int | None:
    if not commodity_group:
        return None
    row = conn.execute("SELECT booking_group_id FROM commodity_group_booking WHERE dealer_id = ? AND commodity_group = ?",
                       (dealer_id, commodity_group)).fetchone()
    return row["booking_group_id"] if row else DEFAULT_BY_COMMODITY.get(commodity_group)


def learn(conn, dealer_id: int, commodity_group: str | None, group_id: int) -> None:
    """Erste Wahl je Warengruppe merken (K03-84); spätere Einzelfälle überschreiben nichts."""
    if commodity_group:
        conn.execute("INSERT OR IGNORE INTO commodity_group_booking (dealer_id, commodity_group, booking_group_id) "
                     "VALUES (?, ?, ?)", (dealer_id, commodity_group, group_id))


def proposal(conn, dealer_id: int, commodity_group: str | None, *, raw_material_id: int | None = None,
             other_article_id: int | None = None, new_type: str | None = None) -> dict:
    """Vorschlag für eine Belegposition: {id, checked, source} – id None = muss gefragt werden."""
    if raw_material_id:
        row = conn.execute("SELECT booking_group_id, booking_group_checked, type FROM raw_material WHERE id = ?",
                           (raw_material_id,)).fetchone()
        if row and row["booking_group_id"]:
            return {"id": row["booking_group_id"], "checked": bool(row["booking_group_checked"]), "source": "article"}
        new_type = row["type"] if row else new_type
    if other_article_id:
        row = conn.execute("SELECT booking_group_id, booking_group_checked FROM other_article WHERE id = ?",
                           (other_article_id,)).fetchone()
        if row and row["booking_group_id"]:
            return {"id": row["booking_group_id"], "checked": bool(row["booking_group_checked"]), "source": "article"}
    gid = learned(conn, dealer_id, commodity_group)
    if gid:
        return {"id": gid, "checked": False, "source": "commodity_group"}
    if new_type is not None or raw_material_id:
        return {"id": UNKOSTEN if new_type == "aid" else ROHSTOFFE, "checked": False, "source": "type"}
    return {"id": None, "checked": False, "source": None}


def set_article_group(conn, *, raw_material_id: int | None = None, other_article_id: int | None = None,
                      group_id: int, checked: bool) -> None:
    table, key = ("raw_material", raw_material_id) if raw_material_id else ("other_article", other_article_id)
    if not key:
        return
    conn.execute(f"UPDATE {table} SET booking_group_id = ?, booking_group_checked = ? WHERE id = ?",
                 (group_id, 1 if checked else 0, key))


# -- Prüfen (Admin) -------------------------------------------------------------------------

def unchecked(conn: sqlite3.Connection) -> list[dict]:
    """Artikel mit automatisch gesetzter Gruppe, die noch keiner bestätigt hat (K03-84)."""
    rows = conn.execute(
        "SELECT 'raw_material' AS kind, r.id, r.number, r.name, r.type, r.booking_group_id, g.name AS group_name "
        "FROM raw_material r JOIN booking_group g ON g.id = r.booking_group_id WHERE r.booking_group_checked = 0 "
        "UNION ALL SELECT 'other_article', o.id, NULL, coalesce(o.description, o.article_no), 'other', "
        "o.booking_group_id, g.name FROM other_article o JOIN booking_group g ON g.id = o.booking_group_id "
        "WHERE o.booking_group_checked = 0 ORDER BY 7, 4").fetchall()
    return [dict(r) for r in rows]


def articles(conn: sqlite3.Connection) -> list[dict]:
    """Alle nicht archivierten Artikel mit Buchungsgruppe, geprüfte und ungeprüfte (Prüfliste, M03-40)."""
    rows = conn.execute(
        "SELECT 'raw_material' AS kind, r.id, r.number, r.name, r.type, r.booking_group_id, g.name AS group_name, "
        "r.booking_group_checked AS checked FROM raw_material r JOIN booking_group g ON g.id = r.booking_group_id "
        "WHERE r.archived = 0 "
        "UNION ALL SELECT 'other_article', o.id, NULL, coalesce(o.description, o.article_no), 'other', "
        "o.booking_group_id, g.name, o.booking_group_checked FROM other_article o "
        "JOIN booking_group g ON g.id = o.booking_group_id WHERE o.archived = 0 ORDER BY 8, 7, 4").fetchall()
    return [dict(r) | {"checked": bool(r["checked"])} for r in rows]


def months(conn: sqlite3.Connection) -> dict:
    """Monate mit eingelesenen Rechnungen/Gutschriften (neueste zuerst) und Zahl der ABs (zählen nicht)."""
    rows = conn.execute(
        "SELECT substr(doc_date, 1, 7) AS month, count(*) AS n FROM receiving_document "
        "WHERE kind IN ('invoice', 'credit_note') AND doc_date IS NOT NULL GROUP BY 1 ORDER BY 1 DESC").fetchall()
    ab = conn.execute("SELECT count(*) FROM receiving_document WHERE kind = 'order_confirmation'").fetchone()[0]
    return {"months": [dict(r) for r in rows], "order_confirmations": ab}


def confirm(conn: sqlite3.Connection, items: list) -> int:
    """Gruppen bestätigen bzw. umstellen: [{kind, id, booking_group_id}] – bestätigt ist danach jede."""
    if not isinstance(items, list) or not items:
        raise ValidationError("Nichts ausgewählt.", field="items")
    with transaction(conn):
        for i, it in enumerate(items):
            if not isinstance(it, dict) or it.get("kind") not in ("raw_material", "other_article"):
                raise ValidationError("Ungültiger Eintrag.", field=f"items.{i}")
            gid = it.get("booking_group_id")
            g = _group(conn, gid)
            if g["archived"]:
                raise ConflictError(f"Gruppe „{g['name']}“ ist archiviert.", code="archived")
            table = it["kind"]
            n = conn.execute(f"UPDATE {table} SET booking_group_id = ?, booking_group_checked = 1 WHERE id = ?",
                             (gid, it.get("id"))).rowcount
            if not n:
                raise NotFoundError("Artikel nicht gefunden.", code="not_found")
    return len(items)


# -- Export ---------------------------------------------------------------------------------

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def month_rows(conn: sqlite3.Connection, month: str) -> dict:
    """Belege (Rechnung, Gutschrift) eines Monats nach Belegdatum mit Summen je Steuersatz und Gruppe."""
    if not isinstance(month, str) or not _MONTH.match(month):
        raise ValidationError("Monat als JJJJ-MM.", field="month")
    groups = list_groups(conn, include_archived=True)
    docs = conn.execute(
        "SELECT d.id, d.kind, d.doc_no, d.doc_date, dl.name AS dealer_name FROM receiving_document d "
        "JOIN dealer dl ON dl.id = d.dealer_id WHERE d.kind IN ('invoice', 'credit_note') AND substr(d.doc_date, 1, 7) = ? "
        "ORDER BY d.doc_date, d.doc_no", (month,)).fetchall()
    out, open_checks = [], 0
    for d in docs:
        lines = conn.execute("SELECT net_book_cents, net_cents, vat_percent, booking_group_id, raw_material_id, "
                             "other_article_id FROM receiving_line WHERE document_id = ?", (d["id"],)).fetchall()
        by_group: dict = {}
        by_rate = {7: 0, 19: 0}
        other_rates = 0
        for l in lines:
            cents = l["net_book_cents"] if l["net_book_cents"] is not None else (l["net_cents"] or 0)
            by_group[l["booking_group_id"]] = by_group.get(l["booking_group_id"], 0) + cents
            if l["vat_percent"] in by_rate:
                by_rate[l["vat_percent"]] += cents
            else:
                other_rates += cents
        for l in lines:
            for col, table in (("raw_material_id", "raw_material"), ("other_article_id", "other_article")):
                if l[col]:
                    row = conn.execute(f"SELECT booking_group_checked FROM {table} WHERE id = ?", (l[col],)).fetchone()
                    if row and not row["booking_group_checked"]:
                        open_checks += 1
        vat = {rate: _vat(conn, d["id"], rate, net) for rate, net in by_rate.items()}
        net = sum(by_rate.values()) + other_rates
        mwst = sum(v for v in vat.values())
        out.append({"id": d["id"], "kind": d["kind"], "doc_no": d["doc_no"], "doc_date": d["doc_date"],
                    "dealer": d["dealer_name"], "net": net, "vat": mwst, "gross": net + mwst,
                    "net_7": by_rate[7], "vat_7": vat[7], "net_19": by_rate[19], "vat_19": vat[19],
                    "groups": by_group, "ungrouped": by_group.get(None, 0)})
    return {"month": month, "groups": groups, "documents": out, "unchecked": open_checks}


def _vat(conn, doc_id: int, rate: int, net: int) -> int:
    """MwSt. je Satz: wie auf dem Beleg gedruckt (summen.mwst_saetze), sonst gerechnet (kaufmännisch)."""
    import json
    row = conn.execute("SELECT reader_json FROM receiving_document WHERE id = ?", (doc_id,)).fetchone()
    try:
        saetze = (json.loads(row["reader_json"])["daten"].get("summen") or {}).get("mwst_saetze") or []
    except (TypeError, ValueError, KeyError):
        saetze = []
    for s in saetze:
        if s.get("satz") == rate and s.get("mwst_cent") is not None:
            v = abs(int(s["mwst_cent"]))
            return -v if net < 0 else v          # Gutschrift: MwSt. mit dem Vorzeichen des Nettos
    q, r = divmod(abs(net) * rate, 100)
    v = q + (1 if r >= 50 else 0)
    return -v if net < 0 else v


def export_xlsx(conn: sqlite3.Connection, month: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    data = month_rows(conn, month)
    groups = [g for g in data["groups"] if not g["archived"] or any(g["id"] in d["groups"] for d in data["documents"])]
    wb = Workbook()
    ws = wb.active
    ws.title = "Wareneingang " + month
    head = ["Nr.", "Tag", "Händler", "Beleg", "Brutto", "MwSt.", "Netto"] + [g["short_name"] for g in groups] + \
           ["ohne Gruppe", "Netto 7 %", "MwSt. 7 %", "Netto 19 %", "MwSt. 19 %", "Prüfung"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    euro = '#,##0.00;[Red]-#,##0.00'
    red = PatternFill("solid", fgColor="F8D7DA")
    for d in data["documents"]:
        y, m, day = d["doc_date"].split("-")
        cells = [None, f"{day}.{m}.", d["dealer"], ("Gutschrift " if d["kind"] == "credit_note" else "") + d["doc_no"],
                 d["gross"] / 100, d["vat"] / 100, d["net"] / 100]
        cells += [(d["groups"].get(g["id"]) or 0) / 100 or None for g in groups]
        cells += [d["ungrouped"] / 100 or None, d["net_7"] / 100, d["vat_7"] / 100, d["net_19"] / 100, d["vat_19"] / 100]
        diff = d["net"] - sum(v for k, v in d["groups"].items())
        cells.append("ok" if diff == 0 and not d["ungrouped"] else "prüfen")
        ws.append(cells)
        row = ws.max_row
        for col in range(5, len(head)):
            ws.cell(row=row, column=col).number_format = euro
        if cells[-1] != "ok":
            ws.cell(row=row, column=len(head)).fill = red
    if data["documents"]:
        first, last = 2, ws.max_row
        total = ["", "", "Summe", ""]
        ws.append(total + [None] * (len(head) - 5) + [""])
        from openpyxl.utils import get_column_letter
        r = ws.max_row
        for col in range(5, len(head)):
            L = get_column_letter(col)
            ws.cell(row=r, column=col, value=f"=SUM({L}{first}:{L}{last})").number_format = euro
            ws.cell(row=r, column=col).font = Font(bold=True)
        ws.cell(row=r, column=3).font = Font(bold=True)
    ws.freeze_panes = "E2"
    widths = {1: 6, 2: 8, 3: 14, 4: 16}
    for col in range(1, len(head) + 1):
        from openpyxl.utils import get_column_letter
        ws.column_dimensions[get_column_letter(col)].width = widths.get(col, 11)
    if data["unchecked"]:
        ws2 = wb.create_sheet("Hinweis")
        ws2.append([f"{data['unchecked']} Belegpositionen gehören zu Artikeln mit ungeprüfter Buchungsgruppe – "
                    "bitte im Wareneingang unter „Buchführung → Gruppen prüfen“ bestätigen."])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
