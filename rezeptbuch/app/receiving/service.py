"""Wareneingang aus BÄKO-Belegen, Teil W1 (Modul 03, docs/wareneingang.md, freigegeben 21.11.2026).

Ablauf: AB hochladen (Add-on 3 liest) → Probelauf mit Zuordnung → speichern als erwarteter Zugang
(bucht nichts) → am Liefertag abhaken/ändern/Ersatz/Rückstand → buchen (eine Transaktion, W3).
Rechnung und Gutschrift folgen mit W2.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path

from ..booking import service as booking
from ..db import transaction
from ..db.connection import default_db_path
from ..errors import ConflictError, NotFoundError, ValidationError
from ..raw_materials import service as raw_materials, sources, stock
from ..raw_materials.models import AID_UNIT, normalize_text
from ..readers import client

READER = "baeko-beleg"
KINDS = {"auftragsbestaetigung": "order_confirmation", "rechnung": "invoice", "gutschrift": "credit_note"}
KIND_TEXT = {"order_confirmation": "Auftragsbestätigung", "invoice": "Rechnung", "credit_note": "Gutschrift"}
RECEIVING = "receiving"
UNIT_WORDS = {"L": "Liter", "DS": "Dose", "ST": "Stück", "BT": "Beutel", "KT": "Karton", "EI": "Eimer", "FL": "Flasche",
              "KA": "Kanister", "PK": "Paket", "SCK": "Sack", "VE": "Verpackungseinheit", "BL": "Block", "TB": "Tube"}
PACK_NAMES = {"SCK": "Sack", "KT": "Karton", "EI": "Eimer", "BT": "Beutel", "DS": "Dose", "FL": "Flasche",
              "KA": "Kanister", "ST": "Stück", "VE": "VE", "PK": "Paket", "BL": "Block", "TB": "Tube"}
_PACK = re.compile(r"^\s*(\d+)\s+(\S+)\s+(?:à|a)\s+([\d.,]+)\s+(\S+)\s*$", re.I)
_WORD = re.compile(r"[a-zäöüß0-9]{3,}")


def documents_dir() -> Path:
    """PDF-Ablage neben der Datenbank (im Betrieb /data/belege, K03-48)."""
    return default_db_path().parent / "belege"


# -- kleine Hilfen ---------------------------------------------------------------------

def _int(value, field: str, *, minimum: int = 0, maximum: int = 10 ** 12) -> int:
    if isinstance(value, bool):
        raise ValidationError("Ganze Zahl erwartet.", field=field)
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValidationError("Ungültige Zahl.", field=field)
    return value


def pack_step(pack_text: str | None, unit_code: str) -> dict:
    """± Gebinde-Tasten (K03-45): „16 SCK à 25 KG“ → Schritt 25 KG, Name Sack."""
    m = _PACK.match(pack_text or "")
    if m and m.group(4).upper() == (unit_code or "").upper():
        size = float(m.group(3).replace(".", "").replace(",", ".")) if "," in m.group(3) else float(m.group(3))
        name = PACK_NAMES.get(m.group(2).upper(), m.group(2))
        return {"step_milli": max(1, round(size * 1000)), "name": name, "count": int(m.group(1))}
    return {"step_milli": 1000, "name": unit_code, "count": None}


def _dealer(conn, printed: str | None) -> int:
    """BÄKO über den gedruckten Namen finden bzw. beim ersten Beleg anlegen (K03-50)."""
    rows = conn.execute("SELECT id, name FROM dealer WHERE archived = 0 ORDER BY id").fetchall()
    for r in rows:
        if "bäko" in r["name"].casefold() or "baeko" in r["name"].casefold():
            return r["id"]
    printed = (printed or "").casefold()
    for r in rows:
        if r["name"].casefold() in printed:
            return r["id"]
    return conn.execute("INSERT INTO dealer (name) VALUES ('BÄKO')").lastrowid


def _source_hit(conn, dealer_id: int, article_no: str | None):
    if not article_no:
        return None
    return conn.execute(
        "SELECT s.raw_material_id, s.grams_per_unit, s.unit_code, r.name, r.type, r.archived FROM raw_material_source s "
        "JOIN raw_material r ON r.id = s.raw_material_id WHERE s.dealer_id = ? AND s.article_no = ? "
        "ORDER BY r.archived, s.is_active DESC LIMIT 1", (dealer_id, article_no)).fetchone()


def _suggestions(conn, text: str, limit: int = 6) -> list[dict]:
    words = set(_WORD.findall((text or "").casefold()))
    rows = conn.execute("SELECT id, number, name, display_name, type FROM raw_material WHERE archived = 0").fetchall()
    scored = []
    for r in rows:
        own = set(_WORD.findall(f"{r['name']} {r['display_name'] or ''}".casefold()))
        score = len(words & own)
        if score:
            scored.append((-score, r["number"], {"id": r["id"], "number": r["number"], "name": r["name"],
                                                  "type": r["type"]}))
    scored.sort(key=lambda x: x[:2])
    return [x[2] for x in scored[:limit]]


# -- Probelauf ---------------------------------------------------------------------------

def _tmp_dir() -> Path:
    d = documents_dir() / "probelauf"
    d.mkdir(parents=True, exist_ok=True)
    return d


def upload(conn: sqlite3.Connection, pdf: bytes, file_name: str | None) -> dict:
    """PDF → Add-on 3 → Zuordnungsvorschläge (nichts gespeichert außer der Probelauf-Datei)."""
    if not pdf.startswith(b"%PDF-"):
        raise ValidationError("Kein PDF.", code="not_pdf")
    res = client.read(READER, pdf, file_name)
    if res.get("status") != "ok" or not res.get("daten"):
        raise ConflictError(res.get("meldung") or f"Beleg nicht übernehmbar ({res.get('status')}).",
                            code="reader_" + str(res.get("status") or "fehler"),
                            warnings=res.get("warnungen") or [])
    sha = hashlib.sha256(pdf).hexdigest()
    tmp = _tmp_dir()
    (tmp / f"{sha}.pdf").write_bytes(pdf)
    (tmp / f"{sha}.json").write_text(json.dumps({"file_name": file_name, "reader": res}, ensure_ascii=False),
                                     encoding="utf-8")
    return dict(_preview(conn, res, sha), token=sha)


def _preview(conn, res: dict, sha: str) -> dict:
    d = res["daten"]
    kind = KINDS.get(d.get("belegart"))
    if kind is None:
        raise ConflictError("Belegart nicht erkannt.", code="kind_unknown")
    billing = kind != "order_confirmation"          # Rechnung/Gutschrift (W2a): Positionen mit Buchungsgruppe
    dealer_id = _dealer(conn, d.get("haendler"))
    dup = conn.execute("SELECT created_at FROM receiving_document WHERE dealer_id = ? AND kind = ? AND doc_no = ?",
                       (dealer_id, kind, d.get("belegnummer"))).fetchone()
    lines = []
    for p in d.get("positionen") or []:
        art = p.get("artikelnummer")
        line = {"line_no": p.get("nr"), "article_no": art, "description": p.get("bezeichnung"),
                "qty_milli": abs(p.get("menge_tausendstel") or 0), "unit_code": (p.get("mengeneinheit") or "KG").upper(),
                "pack_text": p.get("gebinde_text"), "order_item": bool(p.get("bestellartikel")),
                "commodity_group": p.get("warengruppe"), "net_cents": p.get("netto_cent"),
                "net_book_cents": book_cents(p), "vat_percent": p.get("mwst_prozent")}
        hit = _source_hit(conn, dealer_id, art)
        other = conn.execute("SELECT id, description FROM other_article WHERE dealer_id = ? AND article_no = ?",
                             (dealer_id, art)).fetchone() if art else None
        if hit:
            line.update(target="raw_material", raw_material_id=hit["raw_material_id"], raw_material_name=hit["name"],
                        raw_material_type=hit["type"],
                        needs_gpu=line["unit_code"] != "KG" and hit["type"] != "aid" and not hit["grams_per_unit"]
                        and not billing)
        elif other:
            line.update(target="other", other_article_id=other["id"])
        else:
            line.update(target="unknown", suggestions=_suggestions(conn, line["description"]),
                        needs_gpu=line["unit_code"] != "KG" and not billing)
            prior = conn.execute(   # M03-36: kam dieser Artikel schon einmal als Ersatz?
                "SELECT l.raw_material_id, r.name FROM receiving_line l JOIN raw_material r ON r.id = l.raw_material_id "
                "WHERE l.target = 'substitute' AND l.substitute_ref = ? ORDER BY l.id DESC LIMIT 1", (art,)).fetchone() \
                if art else None
            if prior:
                line["prior_substitute"] = {"raw_material_id": prior["raw_material_id"], "name": prior["name"]}
        if billing:
            line["booking"] = booking.proposal(conn, dealer_id, line["commodity_group"],
                                               raw_material_id=line.get("raw_material_id"),
                                               other_article_id=line.get("other_article_id"))
        lines.append(line)
    return {"kind": kind, "billing": billing, "groups": booking.list_groups(conn) if billing else None, "kind_text": KIND_TEXT[kind], "doc_no": d.get("belegnummer"), "doc_date": d.get("belegdatum"),
            "expected_date": d.get("lieferdatum_voraussichtlich"), "chefslist_ref": d.get("ihre_referenz"),
            "dealer_id": dealer_id, "net_cents": (d.get("summen") or {}).get("netto_cent"),
            "duplicate": dup["created_at"] if dup else None, "plausibility": res.get("plausibilitaet") or [],
            "lines": lines}


# -- Speichern mit Entscheidungen ---------------------------------------------------------

def book_cents(p: dict) -> int | None:
    """Betrag, mit dem eine Position in die Belegsumme eingeht – nach Skonto/Konditionen (wie der Leser rechnet)."""
    if p.get("netto_nach_konditionen_cent") is not None:
        return p["netto_nach_konditionen_cent"]
    if p.get("skonto") and p["skonto"].get("cent") is not None and p.get("netto_cent") is not None:
        return p["netto_cent"] + p["skonto"]["cent"]
    return p.get("netto_cent")


def _gpu(value, field: str, where: str = "", unit: str = "") -> int:
    if value is None or value == "":
        word = UNIT_WORDS.get(unit, unit)
        raise ValidationError(f"{where}: Gewicht je {word} fehlt – bitte „Gewicht je {word} eintragen“ tippen.".lstrip(": "),
                              field=field, code="gpu_missing")
    try:
        return _int(value, field, minimum=1, maximum=1_000_000)
    except ValidationError:
        raise ValidationError(f"{where}: Gewicht je {UNIT_WORDS.get(unit, unit)} ungültig (1 bis 1 000 000).".lstrip(": "),
                              field=field, code="gpu_invalid") from None


def _attach_source(conn, rm_id: int, dealer_id: int, article_no: str, unit: str, gpu: int | None, where: str = "") -> None:
    """Bezugsquelle mit Artikelnummer anlegen bzw. leere Nummer füllen (Abschnitt 3, Taste 1)."""
    row = conn.execute("SELECT id, article_no FROM raw_material_source WHERE raw_material_id = ? AND dealer_id = ?",
                       (rm_id, dealer_id)).fetchone()
    data = {"article_no": article_no}
    if gpu is not None:
        data.update(grams_per_unit=gpu, unit_code=unit)
    if row is None:
        sources.add_in_tx(conn, rm_id, dict(data, dealer_id=dealer_id))
    elif row["article_no"] in (None, article_no):
        sources.update_in_tx(conn, rm_id, row["id"], data)
    else:
        raise ConflictError(f"{where + ': ' if where else ''}Der Rohstoff hat schon die BÄKO-Artikelnummer {row['article_no']} – "
                            "bitte einen anderen Rohstoff wählen.",
                            code="article_no_taken")


def commit(conn: sqlite3.Connection, payload: dict) -> dict:
    """Beleg mit Entscheidungen zu unbekannten Positionen speichern (alles oder nichts)."""
    token = payload.get("token")
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise ValidationError("Probelauf fehlt.", field="token")
    tmp = _tmp_dir()
    try:
        saved = json.loads((tmp / f"{token}.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise NotFoundError("Probelauf nicht mehr vorhanden – Beleg bitte neu hochladen.", code="token_gone") from None
    decisions = payload.get("decisions") or {}
    if not isinstance(decisions, dict):
        raise ValidationError("Ungültige Entscheidungen.", field="decisions")
    res = saved["reader"]
    with transaction(conn):
        pre = _preview(conn, res, token)
        if pre["duplicate"]:
            raise ConflictError(f"Beleg {pre['doc_no']} wurde schon am {pre['duplicate'][:10]} eingelesen.",
                                code="duplicate")
        dealer_id = pre["dealer_id"]
        doc_id = conn.execute(
            "INSERT INTO receiving_document (dealer_id, kind, doc_no, doc_date, expected_date, chefslist_ref, status, "
            "reader_version, reader_json, file_name, file_sha256, net_cents) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (dealer_id, pre["kind"], pre["doc_no"], pre["doc_date"], pre["expected_date"], pre["chefslist_ref"],
             "open" if pre["billing"] else "expected", str(res.get("addon_version")), json.dumps(res, ensure_ascii=False), saved.get("file_name"), token,
             pre["net_cents"])).lastrowid
        positions = {p.get("nr"): p for p in res["daten"].get("positionen") or []}
        made: dict[str, tuple[str, int]] = {}   # Artikelnummer → (Ziel, id), wenn im selben Beleg schon angelegt
        for line in pre["lines"]:
            p = positions[line["line_no"]]
            dec = decisions.get(str(line["line_no"])) or {}
            target, rm_id, other_id, gpu_used, note = line["target"], line.get("raw_material_id"), \
                line.get("other_article_id"), None, None
            where = f"Pos. {line['line_no']} ({line['description']})"
            if target == "raw_material" and line.get("needs_gpu") and not pre["billing"]:
                gpu = _gpu(dec.get("grams_per_unit"), f"{line['line_no']}.grams_per_unit", where, line["unit_code"])
                _attach_source(conn, rm_id, dealer_id, line["article_no"], line["unit_code"], gpu, where)
            elif target == "unknown":
                action = dec.get("action")
                gpu = None
                if action in ("assign", "new", "aid_assign", "aid_new", "substitute") and line["needs_gpu"] \
                        and action not in ("aid_assign", "aid_new") and not pre["billing"]:
                    gpu = _gpu(dec.get("grams_per_unit"), f"{line['line_no']}.grams_per_unit", where, line["unit_code"])
                if action in ("assign", "aid_assign"):
                    rm_id = _int(dec.get("raw_material_id"), f"{line['line_no']}.raw_material_id", minimum=1)
                    rm = stock._row(conn, rm_id)
                    if (action == "aid_assign") != (rm["type"] == "aid"):
                        raise ValidationError(f"{where}: Art passt nicht (Rohstoff/Hilfs- und Betriebsstoff).",
                                              field=f"{line['line_no']}.raw_material_id")
                    _attach_source(conn, rm_id, dealer_id, line["article_no"], line["unit_code"], gpu, where)
                    target = "raw_material"
                elif action in ("new", "aid_new") and line["article_no"] and \
                        made.get(line["article_no"], ("", 0))[0] == "raw_material":
                    rm_id = made[line["article_no"]][1]       # gleicher Artikel zweimal im Beleg
                    target = "raw_material"
                elif action in ("new", "aid_new"):
                    data = {"name": dec.get("name") or line["description"]}
                    if action == "new":
                        data.update(type="standard", tolerance_unit=dec.get("tolerance_unit") or "g",
                                    tolerance=dec.get("tolerance"))
                    else:
                        data.update(type="aid", unit_label=dec.get("unit_label") or "VE")
                    rm_id = raw_materials.create_in_tx(conn, data)
                    _attach_source(conn, rm_id, dealer_id, line["article_no"], line["unit_code"], gpu, where)
                    target = "raw_material"
                elif action == "other":
                    row = conn.execute("SELECT id FROM other_article WHERE dealer_id = ? AND article_no IS ?",
                                       (dealer_id, line["article_no"])).fetchone() if line["article_no"] else None
                    other_id = row["id"] if row else conn.execute(
                        "INSERT INTO other_article (dealer_id, article_no, description, last_price_e4, last_unit) "
                        "VALUES (?, ?, ?, ?, ?)", (dealer_id, line["article_no"], line["description"],
                                                  p.get("preis_zehntausendstel_euro"), line["unit_code"])).lastrowid
                    target = "other"
                elif action == "substitute":
                    rm_id = _int(dec.get("raw_material_id"), f"{line['line_no']}.raw_material_id", minimum=1)
                    rm = stock._row(conn, rm_id)
                    gpu_used = gpu
                    note = (f"Ersatz für Rohstoff {rm['name']} – BÄKO {line['article_no']} {line['description']} – "
                            "anderer Hersteller, Pass prüfen")
                    target = "substitute"
                else:
                    raise ValidationError(f"{where} ({line['description']}): bitte zuordnen.",
                                          field=f"{line['line_no']}.action", code="decision_missing")
            if line["article_no"] and target in ("raw_material", "other"):
                made.setdefault(line["article_no"], (target, rm_id if target == "raw_material" else other_id))
            group_id = None
            if pre["billing"]:
                group_id = _line_group(conn, dealer_id, line, dec, where, target=target, rm_id=rm_id, other_id=other_id)
            conn.execute(
                "INSERT INTO receiving_line (document_id, line_no, article_no, description, commodity_group, qty_milli, "
                "unit_code, pack_text, price_e4, price_unit, net_cents, vat_percent, order_item, target, raw_material_id, "
                "other_article_id, grams_per_unit_used, note, booking_group_id, net_book_cents, substitute_ref, "
                "order_no, delivery_note_no, delivery_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, line["line_no"], line["article_no"], line["description"], line["commodity_group"],
                 line["qty_milli"], line["unit_code"], line["pack_text"], p.get("preis_zehntausendstel_euro"),
                 p.get("preiseinheit"), p.get("netto_cent"), p.get("mwst_prozent"), 1 if line["order_item"] else 0,
                 target, rm_id, other_id, gpu_used, note, group_id, line["net_book_cents"],
                 line["article_no"] if target == "substitute" else None,
                 (p.get("auftrag") or {}).get("nummer"), (p.get("lieferung") or {}).get("nummer"),
                 (p.get("lieferung") or {}).get("datum")))
        target_dir = documents_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        final = target_dir / f"{pre['doc_no']}-{token[:8]}.pdf"
        shutil.copyfile(tmp / f"{token}.pdf", final)
        conn.execute("UPDATE receiving_document SET file_path = ? WHERE id = ?", (str(final), doc_id))
    for ext in ("pdf", "json"):
        (tmp / f"{token}.{ext}").unlink(missing_ok=True)
    return get_delivery(conn, doc_id)


def _line_group(conn, dealer_id: int, line: dict, dec: dict, where: str, *, target: str, rm_id, other_id) -> int:
    """Buchungsgruppe der Position (K03-81/K03-84): Wahl beim Einlesen (geprüft, gelernt) oder Vorschlag (ungeprüft)."""
    chosen = dec.get("booking_group_id")
    art_rm = rm_id if target in ("raw_material", "substitute") else None
    art_other = other_id if target == "other" else None
    if chosen is not None:
        g = conn.execute("SELECT id FROM booking_group WHERE id = ? AND archived = 0", (chosen,)).fetchone() \
            if isinstance(chosen, int) and not isinstance(chosen, bool) else None
        if g is None:
            raise ValidationError(f"{where}: Buchungsgruppe ungültig.", field=f"{line['line_no']}.booking_group_id")
        if target != "substitute":                     # Ersatz: Gruppe gilt nur für diese Position
            booking.set_article_group(conn, raw_material_id=art_rm, other_article_id=art_other, group_id=chosen,
                                      checked=True)
        booking.learn(conn, dealer_id, line["commodity_group"], chosen)
        return chosen
    prop = booking.proposal(conn, dealer_id, line["commodity_group"], raw_material_id=art_rm, other_article_id=art_other)
    if prop["id"] is None:
        raise ValidationError(f"{where}: Buchungsgruppe wählen (Warengruppe {line['commodity_group'] or '–'} ist neu).",
                              field=f"{line['line_no']}.booking_group_id", code="group_missing")
    if prop["source"] != "article" and target != "substitute":
        booking.set_article_group(conn, raw_material_id=art_rm, other_article_id=art_other, group_id=prop["id"],
                                  checked=False)
    return prop["id"]


def mark_substitute(conn, rm_id: int, text: str) -> None:
    """M03-35: Marke „Ersatzware im Bestand – Pass prüfen“ am Rohstoff, bis ein Admin sie quittiert."""
    conn.execute("UPDATE raw_material SET substitute_note = ? WHERE id = ?", (text[:300], rm_id))


def substitute_seen(conn, rm_id: int, ref: str | None, exclude_line: int | None = None) -> bool:
    """M03-36: kam derselbe Ersatz (fremde Artikelnummer bzw. Code) für diesen Rohstoff schon einmal?"""
    if not ref:
        return False
    return conn.execute("SELECT 1 FROM receiving_line WHERE target = 'substitute' AND raw_material_id = ? "
                        "AND substitute_ref = ? AND id IS NOT ? LIMIT 1", (rm_id, ref, exclude_line)).fetchone() is not None


def list_substitutes(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, number, name, substitute_note FROM raw_material WHERE substitute_note IS NOT NULL "
                        "ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def pending_substitutes(conn: sqlite3.Connection) -> list[dict]:
    """Ersatz auf einer AB eingetragen, aber noch nicht geliefert/gebucht (Marke M03-35 kommt erst beim Buchen)."""
    rows = conn.execute(
        "SELECT l.id AS line_id, d.doc_no, l.line_no, l.description, l.article_no, r.id, r.number, r.name "
        "FROM receiving_line l JOIN receiving_document d ON d.id = l.document_id "
        "JOIN raw_material r ON r.id = l.raw_material_id "
        "WHERE l.target = 'substitute' AND l.state IN ('open', 'backorder') AND l.delivered_qty_milli = 0 "
        "ORDER BY d.doc_no, l.line_no").fetchall()
    return [dict(r) for r in rows]


def clear_substitute(conn: sqlite3.Connection, rm_id: int) -> None:
    with transaction(conn):
        if not conn.execute("UPDATE raw_material SET substitute_note = NULL WHERE id = ?", (rm_id,)).rowcount:
            raise NotFoundError("Rohstoff nicht gefunden.", code="not_found")


# -- Lieferungen ---------------------------------------------------------------------------

def _gpu_for(conn, line, dealer_id: int) -> int | None:
    if line["unit_code"] == "KG":
        return 1000
    if line["grams_per_unit_used"]:
        return line["grams_per_unit_used"]
    if line["raw_material_id"] is None:
        return None
    row = conn.execute("SELECT r.type, s.grams_per_unit FROM raw_material r LEFT JOIN raw_material_source s "
                       "ON s.raw_material_id = r.id AND s.dealer_id = ? WHERE r.id = ?",
                       (dealer_id, line["raw_material_id"])).fetchone()
    if row is None:
        return None
    if row["type"] == "aid":
        return AID_UNIT                          # 1 Einheit auf dem Beleg = 1 Verpackungseinheit (M03-26)
    return row["grams_per_unit"]


def _line_dict(conn, line, dealer_id: int) -> dict:
    out = {k: line[k] for k in line.keys()}
    out["remaining_milli"] = max(0, line["qty_milli"] - line["delivered_qty_milli"])
    out["grams_per_unit"] = _gpu_for(conn, line, dealer_id)
    out["pack"] = pack_step(line["pack_text"], line["unit_code"])
    if line["raw_material_id"]:
        rm = stock._row(conn, line["raw_material_id"])
        pack_g, pack_label = stock.pack_of(rm)
        out.update(raw_material_name=rm["name"], raw_material_type=rm["type"], stock_g=rm["stock_g"],
                   tracked=rm["stock_g"] is not None, archived=bool(rm["archived"]), rm_pack_g=pack_g,
                   rm_pack_label=pack_label, unit_label=rm["unit_label"])
    return out


def _doc(conn, doc_id: int):
    row = conn.execute("SELECT d.*, dl.name AS dealer_name FROM receiving_document d JOIN dealer dl "
                       "ON dl.id = d.dealer_id WHERE d.id = ?", (doc_id,)).fetchone()
    if row is None:
        raise NotFoundError("Beleg nicht gefunden.", code="not_found")
    return row


def _doc_dict(conn, row, *, open_only: bool) -> dict:
    sql = "SELECT * FROM receiving_line WHERE document_id = ?"
    if open_only:
        sql += " AND state IN ('open', 'backorder')"
    lines = conn.execute(sql + " ORDER BY unexpected, line_no", (row["id"],)).fetchall()
    return {"id": row["id"], "kind": row["kind"], "kind_text": KIND_TEXT[row["kind"]], "doc_no": row["doc_no"],
            "doc_date": row["doc_date"], "expected_date": row["expected_date"], "status": row["status"],
            "dealer_name": row["dealer_name"], "chefslist_ref": row["chefslist_ref"], "created_at": row["created_at"],
            "booked_at": row["booked_at"], "net_cents": row["net_cents"],
            "has_backorder": any(l["state"] == "backorder" for l in lines),
            "lines": [_line_dict(conn, l, row["dealer_id"]) for l in lines]}


def list_deliveries(conn: sqlite3.Connection) -> list[dict]:
    """Erwartete und offene Lieferungen, fällige zuerst (K03-49); Rückstände bleiben drin (K03-44)."""
    rows = conn.execute("SELECT d.*, dl.name AS dealer_name FROM receiving_document d JOIN dealer dl ON dl.id = d.dealer_id "
                        "WHERE d.kind = 'order_confirmation' AND d.status IN ('expected', 'partial') "
                        "ORDER BY coalesce(d.expected_date, d.doc_date), d.id").fetchall()
    return [_doc_dict(conn, r, open_only=True) for r in rows]


def get_delivery(conn: sqlite3.Connection, doc_id: int) -> dict:
    return _doc_dict(conn, _doc(conn, doc_id), open_only=False)


def list_documents(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT d.id, d.kind, d.doc_no, d.doc_date, d.expected_date, d.status, d.created_at, d.booked_at, "
                        "d.net_cents, d.file_name, dl.name AS dealer_name, (SELECT count(*) FROM receiving_line l "
                        "WHERE l.document_id = d.id) AS lines, (SELECT count(*) FROM receiving_line l WHERE "
                        "l.document_id = d.id AND l.delivered_qty_milli > 0) AS booked_lines FROM receiving_document d "
                        "JOIN dealer dl ON dl.id = d.dealer_id ORDER BY d.id DESC LIMIT 300").fetchall()
    return [dict(r, kind_text=KIND_TEXT[r["kind"]]) for r in rows]


def document_pdf(conn: sqlite3.Connection, doc_id: int) -> Path:
    row = _doc(conn, doc_id)
    path = Path(row["file_path"] or "")
    if not row["file_path"] or not path.is_file():
        raise NotFoundError("PDF nicht vorhanden.", code="pdf_missing")
    return path


def delete_document(conn: sqlite3.Connection, doc_id: int, reverse: bool = False) -> dict:
    """Beleg löschen (W1, K03-48). Mit Buchungen nur mit „zurückbuchen“ (M03-33, Michael 23.11.2026, 17:22):
    jeder Zugang aus dem Beleg bekommt eine Gegenbuchung (Art „Rückgängig“), der Bestandsverlauf bleibt."""
    reversed_n = 0
    with transaction(conn):
        row = _doc(conn, doc_id)
        moves = conn.execute(
            "SELECT m.id, m.raw_material_id, m.delta_g, m.kind FROM stock_movement m "
            "JOIN receiving_line l ON l.id = m.receiving_line_id WHERE l.document_id = ? AND m.kind = 'receipt' "
            "AND NOT EXISTS (SELECT 1 FROM stock_movement u WHERE u.undo_of_id = m.id)", (doc_id,)).fetchall()
        booked = conn.execute("SELECT 1 FROM receiving_line WHERE document_id = ? AND delivered_qty_milli > 0 LIMIT 1",
                              (doc_id,)).fetchone()
        if (booked or moves) and not reverse:
            raise ConflictError("Aus diesem Beleg ist schon etwas gebucht.", code="has_bookings",
                                bookings=len(moves))
        for m in moves:
            rm = stock._row(conn, m["raw_material_id"])
            if rm["stock_g"] is None or m["delta_g"] is None:
                continue                                   # Bestand wird nicht (mehr) geführt
            stock._book(conn, m["raw_material_id"], "undo", rm["stock_g"], rm["stock_g"] - m["delta_g"],
                        source=RECEIVING, undo_of_id=m["id"],
                        note=f"Beleg {row['doc_no']} gelöscht – Zugang zurückgebucht")
            reversed_n += 1
        conn.execute("UPDATE stock_movement SET receiving_line_id = NULL WHERE receiving_line_id IN "
                     "(SELECT id FROM receiving_line WHERE document_id = ?)", (doc_id,))
        conn.execute("DELETE FROM receiving_document WHERE id = ?", (doc_id,))
    if row["file_path"]:
        Path(row["file_path"]).unlink(missing_ok=True)
    return {"reversed": reversed_n}


def add_unexpected(conn: sqlite3.Connection, doc_id: int, payload: dict) -> dict:
    """„Nicht in der Lieferung“ / „Zusätzlich aufnehmen?“ (K03-60): Zeile „nicht erwartet“ in kg bzw. VE."""
    rm_id = _int(payload.get("raw_material_id"), "raw_material_id", minimum=1)
    with transaction(conn):
        doc = _doc(conn, doc_id)
        if doc["status"] not in ("expected", "partial"):
            raise ConflictError("Diese Lieferung ist abgeschlossen.", code="closed")
        rm = stock._row(conn, rm_id)
        if rm["archived"]:
            raise ConflictError(f"„{rm['name']}“ ist archiviert.", code="archived")
        existing = conn.execute("SELECT id FROM receiving_line WHERE document_id = ? AND raw_material_id = ? "
                                "AND unexpected = 1 AND state = 'open'", (doc_id, rm_id)).fetchone()
        if existing:
            return {"line_id": existing["id"], "delivery": get_delivery(conn, doc_id)}
        no = conn.execute("SELECT coalesce(max(line_no), 0) + 1 FROM receiving_line WHERE document_id = ?",
                          (doc_id,)).fetchone()[0]
        unit = "KG"
        line_id = conn.execute(
            "INSERT INTO receiving_line (document_id, line_no, description, qty_milli, unit_code, target, "
            "raw_material_id, unexpected, note) VALUES (?, ?, ?, 0, ?, 'raw_material', ?, 1, 'nicht erwartet')",
            (doc_id, no, rm["name"], unit, rm_id)).lastrowid
    return {"line_id": line_id, "delivery": get_delivery(conn, doc_id)}


# -- Buchen --------------------------------------------------------------------------------

def book(conn: sqlite3.Connection, doc_id: int, payload: dict) -> dict:
    """Liefertag buchen (W3: eine Transaktion). Je Zeile: Menge in Belegeinheit (×1000), Rest „backorder“
    (Rückstand, K03-44) oder „cancel“ (streichen), optional Ersatz und „ab jetzt führen“ (K03-46)."""
    items = payload.get("lines")
    if not isinstance(items, list) or not items:
        raise ValidationError("Keine Positionen zum Buchen.", field="lines")
    device = stock._device(payload.get("device_id"), required=False)
    results = []
    with transaction(conn):
        doc = _doc(conn, doc_id)
        if doc["kind"] != "order_confirmation" or doc["status"] not in ("expected", "partial"):
            raise ConflictError("Diese Lieferung ist abgeschlossen.", code="closed")
        seen = set()
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValidationError("Ungültige Position.", field=f"lines.{i}")
            line_id = _int(item.get("id"), f"lines.{i}.id", minimum=1)
            if line_id in seen:
                raise ValidationError("Position doppelt.", field=f"lines.{i}.id")
            seen.add(line_id)
            line = conn.execute("SELECT * FROM receiving_line WHERE id = ? AND document_id = ?",
                                (line_id, doc_id)).fetchone()
            if line is None:
                raise NotFoundError("Position gehört nicht zu dieser Lieferung.", code="not_found")
            if line["state"] not in ("open", "backorder"):
                raise ConflictError(f"Pos. {line['line_no']} ist schon erledigt.", code="line_done")
            qty = _int(item.get("qty_milli", 0), f"lines.{i}.qty_milli", maximum=10 ** 10)
            rest = item.get("rest") or "backorder"
            if rest not in ("backorder", "cancel"):
                raise ValidationError("Rest: Rückstand oder streichen.", field=f"lines.{i}.rest")
            target, rm_id, gpu, note = line["target"], line["raw_material_id"], None, line["note"]
            sub = item.get("substitute")
            sub_ref, repeat = None, False
            if sub:
                rm_id = _int(sub.get("raw_material_id"), f"lines.{i}.substitute", minimum=1)
                sub_rm = stock._row(conn, rm_id)
                target = "substitute"
                note = (f"Ersatz für Rohstoff {sub_rm['name']} – BÄKO {line['article_no'] or ''} "
                        f"{line['description'] or ''} – anderer Hersteller, Pass prüfen")
                if sub.get("pack_g") is not None:
                    pack_g = _int(sub.get("pack_g"), f"lines.{i}.substitute.pack_g", minimum=1, maximum=10 ** 7)
                    note += f" – Gebinde {pack_g / 1000:g} kg".replace(".", ",")
                sub_ref = (str(sub.get("code") or "").strip()[:64]) or None
                repeat = substitute_seen(conn, rm_id, sub_ref)
                if line["unit_code"] != "KG" and sub_rm["type"] != "aid":
                    gpu = _gpu(sub.get("grams_per_unit"), f"lines.{i}.substitute.grams_per_unit")
                elif sub_rm["type"] == "aid":
                    gpu = AID_UNIT
                else:
                    gpu = 1000
            elif target in ("raw_material", "substitute"):
                gpu = _gpu_for(conn, line, doc["dealer_id"])
                if gpu is None and qty:
                    raise ConflictError(f"Pos. {line['line_no']}: g je {line['unit_code']} fehlt.",
                                        code="gpu_missing", line_id=line_id)
            grams = (qty * gpu) // 1000 if gpu and qty else 0
            movement_id, booked_stock = None, None
            if qty and target in ("raw_material", "substitute"):
                rm = stock._row(conn, rm_id)
                if rm["archived"]:
                    raise ConflictError(f"„{rm['name']}“ ist archiviert.", code="archived")
                if rm["stock_g"] is not None or item.get("start_tracking") is True:
                    before = rm["stock_g"]
                    after = (before or 0) + grams
                    text = f"{doc['dealer_name']} {doc['doc_no']} Pos. {line['line_no']}"
                    if note:
                        text += f" · {note}"
                    movement_id = stock._book(conn, rm_id, "receipt", before, after, source=RECEIVING,
                                              note=text[:500], device_id=device, receiving_line_id=line_id)
                    booked_stock = after
            delivered = line["delivered_qty_milli"] + qty
            if delivered > 0 and delivered >= line["qty_milli"]:
                state = "booked"
            elif rest == "cancel":
                state = "booked" if delivered else "cancelled"
            else:
                state = "backorder"
            conn.execute("UPDATE receiving_line SET delivered_qty_milli = ?, grams = grams + ?, state = ?, "
                         "target = ?, raw_material_id = ?, grams_per_unit_used = coalesce(?, grams_per_unit_used), "
                         "note = ?, stock_movement_id = coalesce(?, stock_movement_id), "
                         "substitute_ref = coalesce(?, substitute_ref) WHERE id = ?",
                         (delivered, grams, state, target, rm_id, gpu if target == "substitute" else None, note,
                          movement_id, sub_ref, line_id))
            if sub and qty:
                mark_substitute(conn, rm_id, f"{doc['doc_no']} Pos. {line['line_no']}: {note or ''}")
                if line["target"] == "substitute" and line["substitute_ref"] and not repeat:
                    repeat = substitute_seen(conn, rm_id, line["substitute_ref"], exclude_line=line_id)
            if not sub and qty and line["target"] == "substitute":     # Ersatz schon auf der AB (K03-32)
                mark_substitute(conn, rm_id, f"{doc['doc_no']} Pos. {line['line_no']}: {line['note'] or ''}")
                repeat = substitute_seen(conn, rm_id, line["substitute_ref"], exclude_line=line_id)
            results.append({"line_id": line_id, "line_no": line["line_no"], "grams": grams, "state": state,
                            "raw_material_id": rm_id, "stock_g": booked_stock, "tracked": movement_id is not None,
                            "repeat_substitute": bool(repeat)})
        states = [r["state"] for r in conn.execute("SELECT state FROM receiving_line WHERE document_id = ?", (doc_id,))]
        if all(s in ("booked", "cancelled") for s in states):
            status = "booked"
        elif any(r["delivered_qty_milli"] for r in conn.execute(
                "SELECT delivered_qty_milli FROM receiving_line WHERE document_id = ?", (doc_id,))):
            status = "partial"
        else:
            status = doc["status"]
        conn.execute("UPDATE receiving_document SET status = ?, booked_at = CASE WHEN ? = 'booked' "
                     "THEN strftime('%Y-%m-%dT%H:%M:%SZ', 'now') ELSE booked_at END WHERE id = ?",
                     (status, status, doc_id))
    names = {r["raw_material_id"]: stock._row(conn, r["raw_material_id"])["name"] for r in results if r["raw_material_id"]}
    for r in results:
        r["name"] = names.get(r["raw_material_id"])
    return {"status": status, "lines": results}


# -- Sonstige Artikel -------------------------------------------------------------------------

def list_other_articles(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    rows = conn.execute("SELECT o.*, d.name AS dealer_name, (SELECT count(*) FROM receiving_line l WHERE "
                        "l.other_article_id = o.id) AS lines FROM other_article o JOIN dealer d ON d.id = o.dealer_id"
                        + ("" if include_archived else " WHERE o.archived = 0") + " ORDER BY o.description").fetchall()
    return [dict(r, archived=bool(r["archived"])) for r in rows]


def update_other_article(conn: sqlite3.Connection, other_id: int, payload: dict) -> dict:
    with transaction(conn):
        row = conn.execute("SELECT * FROM other_article WHERE id = ?", (other_id,)).fetchone()
        if row is None:
            raise NotFoundError("Artikel nicht gefunden.", code="not_found")
        if "archived" in payload:
            conn.execute("UPDATE other_article SET archived = ? WHERE id = ?",
                         (1 if payload["archived"] is True else 0, other_id))
        if payload.get("raw_material_id") is not None:
            # „Zum Rohstoff machen“ (K03-27): Bezugsquelle anlegen, bisherige Zeilen umhängen, Bestand erst ab jetzt
            rm_id = _int(payload["raw_material_id"], "raw_material_id", minimum=1)
            _attach_source(conn, rm_id, row["dealer_id"], row["article_no"], row["last_unit"] or "KG",
                           _gpu(payload["grams_per_unit"], "grams_per_unit")
                           if (row["last_unit"] or "KG") != "KG" and payload.get("grams_per_unit") else None)
            conn.execute("UPDATE receiving_line SET target = 'raw_material', raw_material_id = ?, other_article_id = NULL "
                         "WHERE other_article_id = ?", (rm_id, other_id))
            conn.execute("DELETE FROM other_article WHERE id = ?", (other_id,))
            return {"deleted": True, "raw_material_id": rm_id}
    return next(o for o in list_other_articles(conn, True) if o["id"] == other_id)


def normalize(text: str | None) -> str:
    return normalize_text(text or "")
