"""Planer Teil P-B (docs/planer.md 6–11): Plan je Tag, „Jetzt planen“, Vorschau, Aufträge anlegen, Abbuchen.

Ohne FastAPI (testbar). Mengen werden als Brüche gerechnet und erst in der Summe auf ganze Gramm
aufgerundet (R10-P3). Aufträge entstehen über ``production.orders.prepare_order``/``insert_order_in_tx``
– dieselbe Prüfung wie in der Vorwahl (``validate_basis``), keine Änderung an Modul 06/09 (K10-P21).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from fractions import Fraction

from ..calculation import engine
from ..calculation.loader import active_limit
from ..db import transaction
from ..errors import ConflictError, NotFoundError, ServiceError, ValidationError
from ..production.common import check_date, local_today
from ..production.orders import insert_order_in_tx, prepare_order
from ..raw_materials import stock as stock_service

MODES = ("exact", "up", "down", "drop", "hand")
MODE_TEXT = {"exact": "Genau", "up": "Aufrunden", "down": "Abrunden", "drop": "Streichen", "hand": "Von Hand"}
MAX_PLAN_LINES = 500
MAX_RUN_DAYS = 14
MAX_QTY = 10000
SOURCE = "system"


def _ceil(x: Fraction) -> int:
    return -(-x.numerator // x.denominator)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(value, field: str = "date") -> str:
    day = check_date(value, field)
    if day is None:
        raise ValidationError("Bitte ein Datum angeben.", field=field, code="date_missing")
    return day


def _qty(value, field: str) -> int:
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0
    if isinstance(value, bool):
        raise ValidationError("Bitte eine ganze Zahl eingeben.", field=field)
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ValidationError("Bitte eine ganze Zahl eingeben.", field=field) from None
    if not 0 <= number <= MAX_QTY:
        raise ValidationError(f"Menge 0 bis {MAX_QTY}.", field=field)
    return number


def _order_no(value) -> int:
    if value is None or value == "":
        return 1
    if isinstance(value, bool):
        raise ValidationError("Auftragsnummer 1 bis 99.", field="order_no")
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ValidationError("Auftragsnummer 1 bis 99.", field="order_no") from None
    if not 1 <= number <= 99:
        raise ValidationError("Auftragsnummer 1 bis 99.", field="order_no")
    return number


def quantity_text(pieces: int, halves: int, wholes: int) -> str:
    parts = []
    if pieces:
        parts.append(f"{pieces} Stück")
    if halves:
        parts.append(f"{halves} halbe")
    if wholes:
        parts.append(f"{wholes} ganze")
    return " + ".join(parts) or "0"


def multiplier(pieces: int, halves: int, wholes: int, per_whole: int | None) -> Fraction:
    """R10-P1: wie oft die Stückliste gebraucht wird (für ein Ganzes bzw. für ein Stück)."""
    if per_whole:
        total_pieces = pieces + halves * -(-per_whole // 2) + wholes * per_whole
        return Fraction(-(-total_pieces // per_whole))
    return Fraction(pieces) + Fraction(halves, 2) + Fraction(wholes)


# ---------------------------------------------------------------------------
# Plan je Tag (Abschnitt 6)
# ---------------------------------------------------------------------------

def _plan_row(conn, day: str):
    return conn.execute("SELECT * FROM sales_plan WHERE plan_date = ?", (day,)).fetchone()


def get_plan(conn: sqlite3.Connection, day) -> dict:
    day = _day(day)
    row = _plan_row(conn, day)
    lines = []
    if row is not None:
        for r in conn.execute(
                "SELECT l.*, a.register_no, a.name, a.register_group, a.pieces_per_whole, a.plan_enabled, a.in_register "
                "FROM sales_plan_line l JOIN sales_article a ON a.id = l.article_id WHERE l.plan_id = ? "
                "ORDER BY a.register_group, a.register_no, l.order_no", (row["id"],)):
            lines.append({"article_id": r["article_id"], "register_no": r["register_no"], "name": r["name"],
                          "register_group": r["register_group"], "pieces_per_whole": r["pieces_per_whole"],
                          "order_no": r["order_no"], "pieces": r["pieces"], "halves": r["halves"],
                          "wholes": r["wholes"], "quantity_text": quantity_text(r["pieces"], r["halves"], r["wholes"]),
                          "plan_enabled": bool(r["plan_enabled"]), "in_register": bool(r["in_register"])})
    return {"date": day, "note": row["note"] if row else None, "updated_at": row["updated_at"] if row else None,
            "lines": lines}


def _clean_lines(conn, data) -> list[dict]:
    if not isinstance(data, list):
        raise ValidationError("Zeilen fehlen.", field="lines")
    if len(data) > MAX_PLAN_LINES:
        raise ValidationError(f"Höchstens {MAX_PLAN_LINES} Zeilen je Tag.", field="lines")
    seen, result = set(), []
    for i, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise ValidationError(f"Zeile {i}: ungültig.", field="lines")
        try:
            article_id = int(entry.get("article_id"))
        except (TypeError, ValueError):
            raise ValidationError(f"Zeile {i}: Artikel fehlt.", field="lines") from None
        art = conn.execute("SELECT id, name, plan_enabled, pieces_per_whole FROM sales_article WHERE id = ?",
                           (article_id,)).fetchone()
        if art is None:
            raise NotFoundError(f"Zeile {i}: Artikel nicht gefunden.", field="lines", code="article_not_found")
        order_no = _order_no(entry.get("order_no"))
        pieces, halves, wholes = (_qty(entry.get(k), k) for k in ("pieces", "halves", "wholes"))
        if wholes and not art["pieces_per_whole"]:
            raise ValidationError(f"„{art['name']}“ hat kein „Stück je Ganzes“ – „ganze“ geht nicht.", field="lines")
        if not (pieces or halves or wholes):
            continue                                        # leere Zeile = entfernt
        if (article_id, order_no) in seen:
            raise ValidationError(f"„{art['name']}“ steht zweimal in Auftrag {order_no}.", field="lines",
                                  code="duplicate_line")
        seen.add((article_id, order_no))
        result.append({"article_id": article_id, "order_no": order_no, "pieces": pieces, "halves": halves,
                       "wholes": wholes})
    return result


def _write_lines(conn, day: str, lines: list[dict], note) -> None:
    row = _plan_row(conn, day)
    if row is None:
        plan_id = conn.execute("INSERT INTO sales_plan (plan_date, note) VALUES (?, ?)", (day, note)).lastrowid
    else:
        plan_id = row["id"]
        conn.execute("UPDATE sales_plan SET note = ?, updated_at = ? WHERE id = ?", (note, _now(), plan_id))
    conn.execute("DELETE FROM sales_plan_line WHERE plan_id = ?", (plan_id,))
    for ln in lines:
        conn.execute("INSERT INTO sales_plan_line (plan_id, article_id, order_no, pieces, halves, wholes) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (plan_id, ln["article_id"], ln["order_no"], ln["pieces"], ln["halves"], ln["wholes"]))
        conn.execute("UPDATE sales_article SET last_order_no = ? WHERE id = ?", (ln["order_no"], ln["article_id"]))
    if not lines:
        conn.execute("DELETE FROM sales_plan WHERE id = ?", (plan_id,))
    conn.execute("INSERT INTO change_log (source, entity, entity_id, action, old_values, new_values) "
                 "VALUES (?, 'sales_plan', ?, 'update', NULL, ?)",
                 (SOURCE, plan_id, json.dumps({"date": day, "lines": lines}, ensure_ascii=False)))


def _note(value):
    if value is None:
        return None
    text = str(value).strip()
    if len(text) > 500:
        raise ValidationError("Bemerkung höchstens 500 Zeichen.", field="note")
    return text or None


def save_plan(conn: sqlite3.Connection, day, data) -> dict:
    """Ersetzt den Plan eines Tages (leere Zeilen fallen weg). Ändert keine Aufträge (Abschnitt 6)."""
    day = _day(day)
    if not isinstance(data, dict):
        raise ValidationError("Ungültige Anfrage.")
    lines = _clean_lines(conn, data.get("lines"))
    with transaction(conn):
        _write_lines(conn, day, lines, _note(data.get("note")))
    return get_plan(conn, day)


def add_to_plan(conn: sqlite3.Connection, day, data) -> dict:
    """„Plan übernehmen von …“ (K10-P11): gehakte Zeilen dazuschreiben; gleiche Zeilen nur mit ``overwrite``."""
    day = _day(day)
    if not isinstance(data, dict):
        raise ValidationError("Ungültige Anfrage.")
    new = _clean_lines(conn, data.get("lines"))
    current = get_plan(conn, day)
    have = {(ln["article_id"], ln["order_no"]): ln for ln in current["lines"]}
    clashes = [have[(ln["article_id"], ln["order_no"])] for ln in new if (ln["article_id"], ln["order_no"]) in have]
    if clashes and data.get("overwrite") is not True:
        raise ConflictError(
            f"{len(clashes)} Zeile{'n' if len(clashes) != 1 else ''} gibt es am {day} schon – überschreiben?",
            code="overwrite_question", lines=[{"register_no": c["register_no"], "name": c["name"],
                                               "order_no": c["order_no"], "quantity_text": c["quantity_text"]}
                                              for c in clashes])
    merged = {k: {"article_id": v["article_id"], "order_no": v["order_no"], "pieces": v["pieces"],
                  "halves": v["halves"], "wholes": v["wholes"]} for k, v in have.items()}
    for ln in new:
        merged[(ln["article_id"], ln["order_no"])] = ln
    with transaction(conn):
        _write_lines(conn, day, list(merged.values()), current["note"])
    return get_plan(conn, day)


def plan_days(conn: sqlite3.Connection, date_from, date_to) -> list[dict]:
    """Tage mit Plan in einem Zeitraum (für die Tagauswahl bei „Jetzt planen“)."""
    a, b = _day(date_from, "from"), _day(date_to, "to")
    return [{"date": r["plan_date"], "lines": r["n"]} for r in conn.execute(
        "SELECT p.plan_date, count(l.id) AS n FROM sales_plan p LEFT JOIN sales_plan_line l ON l.plan_id = p.id "
        "WHERE p.plan_date BETWEEN ? AND ? GROUP BY p.id ORDER BY p.plan_date", (a, b))]


# ---------------------------------------------------------------------------
# Bedarf (Abschnitt 7, R10-P1 bis R10-P3, R10-P8, R10-P9)
# ---------------------------------------------------------------------------

def _article_lines(conn, article_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT l.kind, l.recipe_id, l.piece_weight_id, l.raw_material_id, l.amount_g, l.amount_pieces, "
        "       r.number AS recipe_number, r.archived AS recipe_archived, r.locked AS recipe_locked, "
        "       r.current_version_id, v.name AS recipe_name, "
        "       p.weight_g AS pw_g, p.label AS pw_label, "
        "       m.number AS raw_number, m.name AS raw_name, m.archived AS raw_archived, m.unit_size_g, "
        "       m.unit_label, m.stock_g "
        "FROM sales_article_line l "
        "LEFT JOIN recipe r ON r.id = l.recipe_id "
        "LEFT JOIN recipe_version v ON v.id = r.current_version_id "
        "LEFT JOIN recipe_piece_weight p ON p.id = l.piece_weight_id "
        "LEFT JOIN raw_material m ON m.id = l.raw_material_id "
        "WHERE l.article_id = ? ORDER BY l.position", (article_id,)).fetchall()


def demand(conn: sqlite3.Connection, dates: list[str]) -> dict:
    """Teile je Rezept/Tag/Auftragsnummer, Rohstoffbedarf je Tag, Fehler (sperren das Anlegen)."""
    parts: dict[tuple[int, str, int], dict] = {}
    raw: dict[tuple[int, str], dict] = {}
    errors: list[dict] = []
    recipes: dict[int, dict] = {}
    for day in dates:
        plan = get_plan(conn, day)
        for pl in plan["lines"]:
            art = {"article_id": pl["article_id"], "register_no": pl["register_no"], "name": pl["name"]}
            lines = _article_lines(conn, pl["article_id"])
            if not pl["plan_enabled"]:
                errors.append({**art, "date": day, "message": "steht auf „nicht planen“"})
                continue
            if not lines:
                errors.append({**art, "date": day, "message": "Stückliste fehlt"})
                continue
            mult = multiplier(pl["pieces"], pl["halves"], pl["wholes"], pl["pieces_per_whole"])
            qtext = pl["quantity_text"]
            for ln in lines:
                if ln["kind"] == "recipe":
                    problem = ("Rezept archiviert" if ln["recipe_archived"] else
                               "Rezept ohne Version" if ln["current_version_id"] is None else
                               "Rezept gesperrt" if ln["recipe_locked"] else None)
                    if problem:
                        errors.append({**art, "date": day,
                                       "message": f"{problem}: {ln['recipe_number']} {ln['recipe_name'] or ''}".strip()})
                    rid = ln["recipe_id"]
                    recipes.setdefault(rid, {"id": rid, "number": ln["recipe_number"], "name": ln["recipe_name"]})
                    part = parts.setdefault((rid, day, pl["order_no"]),
                                            {"grams": Fraction(0), "pieces": {}, "sources": {}})
                    if ln["piece_weight_id"] is not None:
                        grams = mult * ln["pw_g"]
                        pw = part["pieces"].setdefault(ln["piece_weight_id"],
                                                       {"count": Fraction(0), "weight_g": ln["pw_g"],
                                                        "label": ln["pw_label"]})
                        pw["count"] += mult
                    else:
                        grams = mult * ln["amount_g"]
                    part["grams"] += grams
                    src = part["sources"].setdefault(pl["article_id"], {**art, "date": day, "order_no": pl["order_no"],
                                                                         "quantity_text": qtext,
                                                                         "grams": Fraction(0)})
                    src["grams"] += grams
                else:
                    if ln["raw_archived"]:
                        errors.append({**art, "date": day, "message": f"Rohstoff archiviert: {ln['raw_number']} "
                                                                       f"{ln['raw_name']}"})
                    entry = raw.setdefault((ln["raw_material_id"], day), {
                        "raw_material_id": ln["raw_material_id"], "number": ln["raw_number"], "name": ln["raw_name"],
                        "date": day, "grams": Fraction(0), "pieces_without_size": Fraction(0),
                        "unit_label": ln["unit_label"], "stock_g": ln["stock_g"]})
                    if ln["amount_g"] is not None:
                        entry["grams"] += mult * ln["amount_g"]
                    elif ln["unit_size_g"]:
                        entry["grams"] += mult * ln["amount_pieces"] * ln["unit_size_g"]
                    else:
                        entry["pieces_without_size"] += mult * ln["amount_pieces"]
    return {"parts": parts, "raw": raw, "errors": errors, "recipes": recipes}


# ---------------------------------------------------------------------------
# Vorschau (Abschnitt 8) und Wahl (R10-P4, R10-P7, R10-P10, R10-P11)
# ---------------------------------------------------------------------------

def part_key(rid: int, day: str, order_no: int) -> str:
    return f"{rid}|{day}|{order_no}"


def _parse_key(key: str) -> tuple[int, str, int]:
    rid, day, no = key.split("|")
    return int(rid), day, int(no)


def clean_choices(data) -> dict:
    """Wahl aus der Vorschau prüfen (gespeichert in ``plan_run.choices``)."""
    data = data if isinstance(data, dict) else {}
    out = {"merges": [], "modes": {}, "manual": {}, "surcharge": {}, "dates": {}, "carry_into": {}}
    for group in data.get("merges") or []:
        if isinstance(group, list) and len(group) >= 2 and all(isinstance(k, str) for k in group):
            try:
                rids = {_parse_key(k)[0] for k in group}
            except ValueError:
                raise ValidationError("Ungültige Zusammenfassung.", field="merges") from None
            if len(rids) != 1:
                raise ValidationError("Nur Aufträge desselben Rezepts lassen sich zusammenfassen.", field="merges")
            out["merges"].append(sorted(set(group)))
    for key, mode in (data.get("modes") or {}).items():
        if mode not in MODES:
            raise ValidationError("Ungültige Wahl.", field="modes")
        out["modes"][str(key)] = mode
    for key, value in (data.get("manual") or {}).items():
        try:
            grams = int(value)
        except (TypeError, ValueError):
            raise ValidationError("Von Hand: ganze Gramm.", field="manual") from None
        if not 1 <= grams <= engine.MAX_DOUGH_G * engine.MAX_DOUGHS:
            raise ValidationError("Von Hand: 1 g bis 50 000 kg.", field="manual")
        out["manual"][str(key)] = grams
    for key, sur in (data.get("surcharge") or {}).items():
        if sur is None:
            out["surcharge"][str(key)] = None
            continue
        if not isinstance(sur, dict) or sur.get("unit") not in ("%", "g"):
            raise ValidationError("Zuschlag: % oder g.", field="surcharge")
        try:
            value = int(sur.get("value"))
        except (TypeError, ValueError):
            raise ValidationError("Zuschlag: ganze Zahl (Zehntelprozent bzw. Gramm).", field="surcharge") from None
        if sur["unit"] == "%" and not 0 <= value <= 200:
            raise ValidationError("Zuschlag 0 bis 20 %.", field="surcharge")
        if sur["unit"] == "g" and not 0 <= value <= 100000:
            raise ValidationError("Zuschlag 0 bis 100 000 g je Teig.", field="surcharge")
        out["surcharge"][str(key)] = {"unit": sur["unit"], "value": value}
    for key, day in (data.get("dates") or {}).items():
        out["dates"][str(key)] = _day(day, "dates")
    for key, target in (data.get("carry_into") or {}).items():
        if target is not None:
            out["carry_into"][str(key)] = str(target)
    return out


def _existing(conn, rid: int, day: str, order_no: int) -> list[dict]:
    rows = conn.execute(
        "SELECT o.id, o.status, sum(s.amount_g) AS amount_g, "
        "       EXISTS (SELECT 1 FROM batch b WHERE b.order_id = o.id) AS started "
        "FROM order_article_source s JOIN production_order o ON o.id = s.order_id "
        "WHERE o.recipe_id = ? AND s.plan_date = ? AND s.order_no = ? AND s.carryover = 0 "
        "GROUP BY o.id ORDER BY o.id", (rid, day, order_no)).fetchall()
    return [{"order_id": r["id"], "status": r["status"], "amount_g": r["amount_g"] or 0,
             "started": bool(r["started"]) or r["status"] != "open"} for r in rows]


def _recipe_info(conn, rid: int, cache: dict) -> dict:
    if rid not in cache:
        row = conn.execute("SELECT r.number, r.preproduce, r.weigh_surcharge_tenths, v.name FROM recipe r "
                           "LEFT JOIN recipe_version v ON v.id = r.current_version_id WHERE r.id = ?",
                           (rid,)).fetchone()
        limit = active_limit(conn, rid)
        cache[rid] = {"id": rid, "number": row["number"], "name": row["name"], "preproduce": bool(row["preproduce"]),
                      "surcharge_tenths": row["weigh_surcharge_tenths"],
                      "limit_g": limit["limit_g"] if limit else None,
                      "limit_label": limit["label"] if limit else None}
    return cache[rid]


def _surcharge_g(sur: dict | None, base: int, n: int) -> int:
    if not sur or not sur["value"]:
        return 0
    if sur["unit"] == "%":
        return _ceil(Fraction(base * sur["value"], 1000))
    return sur["value"] * n


def _sur_text(sur: dict | None) -> str | None:
    if not sur or not sur["value"]:
        return None
    if sur["unit"] == "%":
        v = sur["value"]
        return f"+{v // 10}{',' + str(v % 10) if v % 10 else ''} %"
    return f"+{sur['value']} g je Teig"


def _plan(entry: dict, info: dict) -> None:
    """Teige eines Auftrags nach Wahl, Zuschlag und Obergrenze (R10-P6, R10-P7, R10-P10, R10-P11)."""
    limit = info["limit_g"]
    mode = entry["mode"]
    base = entry["manual_g"] if mode == "hand" and entry.get("manual_g") else entry["demand_g"]
    carry_in = entry.get("carry_in_g", 0)
    entry.update(target_g=0, doughs=[], surcharge_g=0, carry_g=0, hint=None)
    if mode == "drop" or base + carry_in <= 0:
        if mode != "drop" and base + carry_in <= 0:
            entry["hint"] = "nichts mehr anzulegen"
        return
    if limit is None:
        z = _surcharge_g(entry["surcharge"], base, 1)
        entry.update(target_g=base + z + carry_in, doughs=[base + z + carry_in], surcharge_g=z)
        return
    total_in = base + carry_in
    n = max(1, _ceil(Fraction(total_in, limit)))
    if mode == "up":
        entry.update(target_g=n * limit, doughs=[limit] * n)
        if entry["surcharge"] and entry["surcharge"]["value"]:
            entry["hint"] = "Zuschlag im Aufrunden enthalten"
        return
    if mode == "down":
        if n == 1:
            entry["hint"] = "Abrunden bei einem Teig = Streichen (alles aus Vorrat)"
            return
        entry.update(target_g=(n - 1) * limit, doughs=[limit] * (n - 1))
        entry["hint"] = f"{total_in - (n - 1) * limit} g aus Vorrat"
        return
    z = _surcharge_g(entry["surcharge"], base, n)
    target = base + z + carry_in
    if target > n * limit:                                  # Übertrag (K10-P23)
        entry.update(target_g=n * limit, doughs=[limit] * n, surcharge_g=z, carry_g=target - n * limit)
        return
    if n > engine.MAX_DOUGHS:
        entry["hint"] = f"mehr als {engine.MAX_DOUGHS} Teige"
    entry.update(target_g=target, doughs=engine.plan_doughs(target, limit, n, "even"), surcharge_g=z)


def preview(conn: sqlite3.Connection, dates: list[str], choices: dict, *, subtract: str | None = None) -> dict:
    """Vorschau. ``subtract``: ``replace`` (gestartete/fertige abziehen) oder ``delta`` (alle angelegten abziehen)."""
    dem = demand(conn, dates)
    cache: dict = {}
    parts = dem["parts"]
    key_of = {part_key(*k): k for k in parts}
    groups: list[list[str]] = []
    used: set[str] = set()
    for group in choices["merges"]:
        members = [k for k in group if k in key_of and k not in used]
        if len(members) >= 2:
            groups.append(sorted(members, key=lambda k: (key_of[k][1], key_of[k][2])))
            used.update(members)
    for k in sorted(key_of, key=lambda k: (key_of[k][1], key_of[k][2])):
        if k not in used:
            groups.append([k])

    entries = []
    hints = []
    for members in groups:
        rid = key_of[members[0]][0]
        info = _recipe_info(conn, rid, cache)
        key = "+".join(members)
        demand_total, sources, existing, pieces = Fraction(0), [], [], {}
        subtracted = 0
        for m in members:
            p = parts[key_of[m]]
            _r, day, no = key_of[m]
            ex = _existing(conn, rid, day, no)
            existing.extend({**e, "date": day, "order_no": no} for e in ex)
            already = sum(e["amount_g"] for e in ex if subtract == "delta" or (subtract == "replace" and e["started"]))
            subtracted += already
            demand_total += p["grams"]
            for pid, pw in p["pieces"].items():
                acc = pieces.setdefault(pid, {"count": Fraction(0), "weight_g": pw["weight_g"], "label": pw["label"]})
                acc["count"] += pw["count"]
            for s in p["sources"].values():
                sources.append({k: v for k, v in s.items() if k != "grams"} | {"amount_g": _ceil(s["grams"])})
        demand_g = _ceil(demand_total)
        effective = max(0, demand_g - subtracted)
        if subtract == "delta" and subtracted > demand_g:
            hints.append(f"{info['number']} {info['name']}: weniger als bereits angelegt (−{subtracted - demand_g} g)")
        first_day = min(key_of[m][1] for m in members)
        default_mode = "up" if info["preproduce"] and info["limit_g"] else "exact"
        mode = choices["modes"].get(key, default_mode)
        if info["limit_g"] is None and mode in ("up", "down"):
            mode = "exact"
        sur = choices["surcharge"].get(key, "default")
        if sur == "default":
            sur = {"unit": "%", "value": info["surcharge_tenths"]} if info["surcharge_tenths"] else None
        entry = {
            "key": key, "kind": "order", "recipe_id": rid, "members": members,
            "parts": [{"date": key_of[m][1], "order_no": key_of[m][2]} for m in members],
            "merged": len(members) > 1, "demand_g": effective, "full_demand_g": demand_g,
            "subtracted_g": subtracted, "mode": mode, "manual_g": choices["manual"].get(key),
            "surcharge": sur, "surcharge_text": _sur_text(sur),
            "production_date": choices["dates"].get(key, first_day),
            "rank": (min(key_of[m][2] for m in members), first_day),
            "existing": existing, "sources": sources,
            "pieces": {pid: v for pid, v in pieces.items()},
        }
        entries.append(entry)

    # Reihenfolge je Rezept und Produktionstag, Überträge direkt dahinter
    entries.sort(key=lambda e: (e["production_date"], cache[e["recipe_id"]]["number"], e["rank"]))
    by_key = {e["key"]: e for e in entries}
    result_entries = []
    for e in entries:
        info = cache[e["recipe_id"]]
        _plan(e, info)
        result_entries.append(e)
        if e["carry_g"]:
            ckey = e["key"] + "|U"
            target_key = choices["carry_into"].get(ckey)
            target = by_key.get(target_key) if target_key else None
            if (target is not None and target["recipe_id"] == e["recipe_id"]
                    and target["production_date"] == e["production_date"] and target is not e
                    and entries.index(target) > entries.index(e)):
                target["carry_in_g"] = target.get("carry_in_g", 0) + e["carry_g"]
                target.setdefault("carry_from", []).append(e["key"])
                e["carry_merged_into"] = target_key
                continue
            cmode = choices["modes"].get(ckey, "exact")
            if cmode not in ("exact", "drop"):
                cmode = "exact"
            carry = {"key": ckey, "kind": "carry", "recipe_id": e["recipe_id"], "members": [],
                     "parts": e["parts"], "merged": False, "demand_g": e["carry_g"], "full_demand_g": e["carry_g"],
                     "subtracted_g": 0, "mode": cmode, "manual_g": None, "surcharge": None, "surcharge_text": None,
                     "production_date": e["production_date"], "rank": e["rank"], "existing": [],
                     "sources": e["sources"], "pieces": {}, "carry_of": e["key"]}
            _plan(carry, info)
            result_entries.append(carry)
            later = [x for x in entries if x["recipe_id"] == e["recipe_id"]
                     and x["production_date"] == e["production_date"] and entries.index(x) > entries.index(e)]
            carry["next_key"] = later[0]["key"] if later else None
            e["hint"] = (f"Durch den Zuschlag entsteht ein Übertrag von {e['carry_g']} g"
                         + (f" – folgende Aufträge rücken nach hinten" if later else ""))

    # Tage → Rezepte
    days: dict[str, dict] = {}
    for e in result_entries:
        info = cache[e["recipe_id"]]
        day = days.setdefault(e["production_date"], {"date": e["production_date"], "recipes": {}})
        block = day["recipes"].setdefault(e["recipe_id"], {
            "recipe_id": e["recipe_id"], "number": info["number"], "name": info["name"],
            "preproduce": info["preproduce"], "limit_g": info["limit_g"], "limit_label": info["limit_label"],
            "default_surcharge_tenths": info["surcharge_tenths"], "sum_g": 0, "entries": []})
        if e["kind"] == "order":
            block["sum_g"] += e["full_demand_g"]
        block["entries"].append(_entry_out(e, info))
    out_days = []
    for d in sorted(days):
        blocks = sorted(days[d]["recipes"].values(), key=lambda b: b["number"])
        out_days.append({"date": d, "recipes": blocks})

    raw = []
    for (rmid, day), r in sorted(dem["raw"].items(), key=lambda kv: (kv[0][1], kv[1]["number"])):
        grams = _ceil(r["grams"])
        booked = booked_g(conn, day, rmid)
        raw.append({"raw_material_id": rmid, "number": r["number"], "name": r["name"], "date": day,
                    "amount_g": grams, "pieces_without_size": _ceil(r["pieces_without_size"]) or None,
                    "unit_label": r["unit_label"], "stock_g": r["stock_g"], "stock_managed": r["stock_g"] is not None,
                    "short": r["stock_g"] is not None and r["stock_g"] - (grams - booked) < 0, "booked_g": booked})
    return {"dates": dates, "errors": dem["errors"], "hints": hints, "days": out_days, "raw": raw,
            "entries": result_entries}


def _entry_out(e: dict, info: dict) -> dict:
    modes = (["exact", "up", "down", "drop"] if info["limit_g"] else ["exact", "drop"]) if e["kind"] == "order" \
        else ["exact", "drop"]
    label = ("Übertrag" if e["kind"] == "carry" else
             " + ".join(f"{p['date'][8:10]}.{p['date'][5:7]}. · Auftrag {p['order_no']}" for p in e["parts"]))
    return {
        "key": e["key"], "kind": e["kind"], "label": label, "parts": e["parts"], "merged": e["merged"],
        "demand_g": e["demand_g"], "full_demand_g": e["full_demand_g"], "subtracted_g": e["subtracted_g"],
        "mode": e["mode"], "mode_text": MODE_TEXT[e["mode"]], "modes": modes, "manual_g": e["manual_g"],
        "surcharge": e["surcharge"], "surcharge_text": e["surcharge_text"], "surcharge_g": e["surcharge_g"],
        "target_g": e["target_g"], "doughs": e["doughs"], "dough_count": len(e["doughs"]),
        "carry_g": e["carry_g"], "carry_in_g": e.get("carry_in_g", 0), "carry_merged_into": e.get("carry_merged_into"),
        "carry_of": e.get("carry_of"), "next_key": e.get("next_key"),
        "production_date": e["production_date"], "hint": e["hint"],
        "existing": e["existing"], "sources": e["sources"],
        "pieces": [{"piece_weight_id": pid, "label": v["label"], "weight_g": v["weight_g"],
                    "count": float(v["count"])} for pid, v in e["pieces"].items()],
    }


# ---------------------------------------------------------------------------
# Planlauf (plan_run) und Aufträge anlegen (Abschnitt 9)
# ---------------------------------------------------------------------------

def _run(conn, run_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM plan_run WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise NotFoundError("Planlauf nicht gefunden.", code="not_found")
    return row


def _run_out(conn, row, prev: dict) -> dict:
    prev = {k: v for k, v in prev.items() if k != "entries"}
    existing = any(x["existing"] for d in prev["days"] for b in d["recipes"] for x in b["entries"])
    return {"id": row["id"], "status": row["status"], "mode": row["mode"], "created_at": row["created_at"],
            "done_at": row["done_at"], "choices": json.loads(row["choices"] or "{}"), "has_existing": existing,
            "order_ids": [r[0] for r in conn.execute("SELECT order_id FROM plan_run_order WHERE run_id = ?",
                                                     (row["id"],))], **prev}


def _dates(data) -> list[str]:
    days = data.get("dates") if isinstance(data, dict) else None
    if not isinstance(days, list) or not days:
        raise ValidationError("Bitte mindestens einen Tag wählen.", field="dates")
    if len(days) > MAX_RUN_DAYS:
        raise ValidationError(f"Höchstens {MAX_RUN_DAYS} Tage auf einmal.", field="dates")
    return sorted({_day(d, "dates") for d in days})


def create_run(conn: sqlite3.Connection, data) -> dict:
    dates = _dates(data)
    choices = clean_choices((data or {}).get("choices"))
    with transaction(conn):
        run_id = conn.execute("INSERT INTO plan_run (dates, choices) VALUES (?, ?)",
                              (json.dumps(dates), json.dumps(choices))).lastrowid
    return get_run(conn, run_id)


def get_run(conn: sqlite3.Connection, run_id: int) -> dict:
    row = _run(conn, run_id)
    dates = json.loads(row["dates"])
    choices = clean_choices(json.loads(row["choices"] or "{}"))
    return _run_out(conn, row, preview(conn, dates, choices))


def update_run(conn: sqlite3.Connection, run_id: int, data) -> dict:
    row = _run(conn, run_id)
    if row["status"] != "preview":
        raise ConflictError("Dieser Planlauf ist schon angelegt – bitte neu planen.", code="run_done")
    choices = clean_choices((data or {}).get("choices"))
    with transaction(conn):
        conn.execute("UPDATE plan_run SET choices = ? WHERE id = ?", (json.dumps(choices), run_id))
    return get_run(conn, run_id)


def _basis_payload(e: dict, info: dict) -> dict:
    """Bezugsart (Abschnitt 9): nur Stückgewichte → pieces; gemischt → combined; sonst total."""
    target = e["target_g"]
    payload = {"recipe_id": e["recipe_id"], "planned_date": e["production_date"]}
    pieces = [(pid, int(v["count"]), v["weight_g"]) for pid, v in e["pieces"].items() if int(v["count"]) >= 1]
    piece_g = sum(c * w for _pid, c, w in pieces)
    if pieces and e["mode"] in ("exact", "hand", "up") and target >= piece_g:
        plist = [{"piece_weight_id": pid, "count": c} for pid, c, _w in pieces]
        if target == piece_g:
            payload.update(basis_type="pieces", pieces=plist)
        else:
            payload.update(basis_type="combined", pieces=plist, total_part=target - piece_g)
    else:
        payload.update(basis_type="total", value=target, input_unit="g")
    n = len(e["doughs"])
    if info["limit_g"] is not None:
        payload.update(split=n > 1, dough_count=n,
                       split_mode="fill" if e["mode"] in ("up", "down") or e["carry_g"] else "even")
    return payload


def commit_run(conn: sqlite3.Connection, run_id: int, data) -> dict:
    """„Aufträge anlegen“ – alles in einer Transaktion (Abschnitt 9, K10-P10)."""
    row = _run(conn, run_id)
    if row["status"] != "preview":
        raise ConflictError("Dieser Planlauf ist schon angelegt.", code="run_done")
    mode = (data or {}).get("mode") if isinstance(data, dict) else None
    if mode not in (None, "replace", "delta"):
        raise ValidationError("„Ersetzen“ oder „Nur Unterschied“.", field="mode")
    dates = json.loads(row["dates"])
    choices = clean_choices(json.loads(row["choices"] or "{}"))
    first = preview(conn, dates, choices)
    if first["errors"]:
        raise ConflictError("Erst die Fehler in den Stücklisten beheben: "
                            + "; ".join(f"{e['register_no']} {e['name']}: {e['message']}" for e in first["errors"][:5]),
                            code="plan_errors", errors=first["errors"])
    existing = [x for x in first["entries"] if x["existing"]]
    if existing and mode is None:
        raise ConflictError("Für einige Aufträge gibt es schon angelegte Aufträge aus früheren Läufen. "
                            "„Ersetzen“ oder „Nur Unterschied dazu“?", code="existing_orders",
                            entries=[{"key": x["key"], "recipe_id": x["recipe_id"], "existing": x["existing"]}
                                     for x in existing])
    prev = preview(conn, dates, choices, subtract=mode) if mode else first
    cache: dict = {}
    prepared, problems = [], []
    order_keys = []
    sorted_entries = sorted(prev["entries"], key=lambda e: (e["production_date"], e["rank"],
                                                            _recipe_info(conn, e["recipe_id"], cache)["number"],
                                                            e["kind"] == "carry"))
    for e in sorted_entries:
        if not e["target_g"]:
            continue
        info = _recipe_info(conn, e["recipe_id"], cache)
        try:
            prep = prepare_order(conn, _basis_payload(e, info))
        except ServiceError as exc:
            problems.append(f"{info['number']} {info['name']} ({e['production_date']}): {exc.message}")
            continue
        if prep["doughs"] != e["doughs"]:
            problems.append(f"{info['number']} {info['name']}: Teige {prep['doughs']} statt {e['doughs']}")
            continue
        prepared.append((e, prep))
        order_keys.append(e["key"])
    if problems:
        raise ConflictError("Aufträge können nicht angelegt werden: " + "; ".join(problems), code="order_problems",
                            problems=problems)
    removed = []
    with transaction(conn):
        if mode == "replace":
            for x in prev["entries"]:
                for ex in x["existing"]:
                    if ex["started"] or ex["order_id"] in removed:
                        continue
                    if conn.execute("SELECT 1 FROM production_order WHERE parent_order_id = ?",
                                    (ex["order_id"],)).fetchone():
                        continue
                    conn.execute("DELETE FROM production_order WHERE id = ? AND status = 'open'", (ex["order_id"],))
                    removed.append(ex["order_id"])
        ids: dict[str, int] = {}
        for e, prep in prepared:
            extra = {}
            if e["surcharge_g"] and e["surcharge"]:
                if e["surcharge"]["unit"] == "%":
                    extra["surcharge_tenths"] = e["surcharge"]["value"]
                else:
                    extra["surcharge_g"] = e["surcharge"]["value"]
            if e["kind"] == "carry":
                extra["carryover_of_order_id"] = ids.get(e["carry_of"])
            order_id = insert_order_in_tx(conn, prep, extra=extra)
            ids[e["key"]] = order_id
            carried = e["kind"] == "carry"
            for s in e["sources"]:
                conn.execute(
                    "INSERT INTO order_article_source (order_id, article_id, article_name, register_no, plan_date, "
                    "order_no, quantity_text, amount_g, carryover) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (order_id, s["article_id"], s["name"], s["register_no"], s["date"], s["order_no"],
                     s["quantity_text"], None if carried else s["amount_g"], 1 if carried else 0))
            for origin in e.get("carry_from", []):          # Übertrag mit diesem Auftrag zusammengefasst
                origin_entry = next((x for x in prev["entries"] if x["key"] == origin), None)
                for s in (origin_entry or {}).get("sources", []):
                    conn.execute(
                        "INSERT INTO order_article_source (order_id, article_id, article_name, register_no, "
                        "plan_date, order_no, quantity_text, amount_g, carryover) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 1)",
                        (order_id, s["article_id"], s["name"], s["register_no"], s["date"], s["order_no"],
                         s["quantity_text"]))
            conn.execute("INSERT INTO plan_run_order (run_id, order_id) VALUES (?, ?)", (run_id, order_id))
        conn.execute("UPDATE plan_run SET status = 'done', mode = ?, done_at = ? WHERE id = ?",
                     (mode, _now(), run_id))
    return {"run_id": run_id, "created": list(ids.values()), "removed": removed, "hints": prev["hints"],
            "count": len(ids)}


# ---------------------------------------------------------------------------
# Artikel je Auftrag (Chargen-Taste, K10-P22)
# ---------------------------------------------------------------------------

def order_articles(conn: sqlite3.Connection, order_id: int) -> dict:
    order = conn.execute("SELECT id, dough_count, carryover_of_order_id, surcharge_tenths, surcharge_g, "
                         "parent_order_id FROM production_order WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise NotFoundError("Auftrag nicht gefunden.", code="not_found")
    rows = conn.execute("SELECT * FROM order_article_source WHERE order_id = ? ORDER BY carryover, plan_date, "
                        "order_no, register_no", (order_id,)).fetchall()
    return {
        "order_id": order_id, "dough_count": order["dough_count"], "from_planner": bool(rows),
        "carryover_of_order_id": order["carryover_of_order_id"],
        "surcharge_text": _sur_text({"unit": "%", "value": order["surcharge_tenths"]} if order["surcharge_tenths"]
                                    else {"unit": "g", "value": order["surcharge_g"]} if order["surcharge_g"] else None),
        "articles": [{"register_no": r["register_no"], "name": r["article_name"], "plan_date": r["plan_date"],
                      "order_no": r["order_no"], "quantity_text": r["quantity_text"], "amount_g": r["amount_g"],
                      "carryover": bool(r["carryover"])} for r in rows],
    }


# ---------------------------------------------------------------------------
# Rohstoffe abbuchen (K10-P12, Abschnitt 10)
# ---------------------------------------------------------------------------

def booked_g(conn, day: str, raw_material_id: int) -> int:
    return conn.execute("SELECT COALESCE(sum(amount_g), 0) FROM plan_stock_booking WHERE production_date = ? "
                        "AND raw_material_id = ? AND reversed_at IS NULL", (day, raw_material_id)).fetchone()[0]


def stock_needs(conn: sqlite3.Connection, day) -> dict:
    day = _day(day)
    prev = preview(conn, [day], clean_choices({}))
    rows = [{k: r[k] for k in ("raw_material_id", "number", "name", "amount_g", "pieces_without_size", "unit_label",
                                "stock_g", "stock_managed", "booked_g", "short")} | {"diff_g": r["amount_g"] - r["booked_g"]}
            for r in prev["raw"]]
    return {"date": day, "today": local_today(), "rows": rows}


def book_stock(conn: sqlite3.Connection, day, data) -> dict:
    """„Rohstoffe für heute abbuchen“: nur bestandsgeführte; erneut = nur der Unterschied; weniger = Zurückbuchen?"""
    day = _day(day)
    if day > local_today():
        raise ConflictError("Abgebucht wird erst am Produktionstag.", code="not_yet")
    data = data if isinstance(data, dict) else {}
    needs = [r for r in stock_needs(conn, day)["rows"] if r["stock_managed"]]
    # bestandsgeführte Rohstoffe, die nicht mehr im Plan stehen, aber gebucht sind
    planned_ids = {r["raw_material_id"] for r in needs}
    for r in conn.execute("SELECT b.raw_material_id, m.number, m.name, m.stock_g, sum(b.amount_g) AS booked "
                          "FROM plan_stock_booking b JOIN raw_material m ON m.id = b.raw_material_id "
                          "WHERE b.production_date = ? AND b.reversed_at IS NULL GROUP BY b.raw_material_id",
                          (day,)):
        if r["raw_material_id"] not in planned_ids and r["stock_g"] is not None:
            needs.append({"raw_material_id": r["raw_material_id"], "number": r["number"], "name": r["name"],
                          "amount_g": 0, "booked_g": r["booked"], "diff_g": -r["booked"], "stock_g": r["stock_g"]})
    returns = [r for r in needs if r["diff_g"] < 0]
    if returns and data.get("return") is None:
        raise ConflictError("Der Bedarf ist kleiner als bereits abgebucht. Zurückbuchen?", code="return_question",
                            rows=[{"number": r["number"], "name": r["name"], "diff_g": r["diff_g"]} for r in returns])
    booked, returned = [], []
    now = _now()
    with transaction(conn):
        for r in needs:
            rmid = r["raw_material_id"]
            if r["diff_g"] > 0:
                row = stock_service._row(conn, rmid)
                mid = stock_service._book(conn, rmid, "planner", row["stock_g"], row["stock_g"] - r["diff_g"],
                                          source="system", note=f"Planer {day}")
                conn.execute("INSERT INTO plan_stock_booking (production_date, raw_material_id, amount_g, "
                             "stock_movement_id) VALUES (?, ?, ?, ?)", (day, rmid, r["diff_g"], mid))
                booked.append({"number": r["number"], "name": r["name"], "amount_g": r["diff_g"]})
            elif r["diff_g"] < 0 and data.get("return") is True:
                row = stock_service._row(conn, rmid)
                back = r["booked_g"]
                stock_service._book(conn, rmid, "planner_return", row["stock_g"], row["stock_g"] + back,
                                    source="system", note=f"Planer {day} zurück")
                conn.execute("UPDATE plan_stock_booking SET reversed_at = ? WHERE production_date = ? AND "
                             "raw_material_id = ? AND reversed_at IS NULL", (now, day, rmid))
                if r["amount_g"] > 0:
                    row = stock_service._row(conn, rmid)
                    mid = stock_service._book(conn, rmid, "planner", row["stock_g"], row["stock_g"] - r["amount_g"],
                                              source="system", note=f"Planer {day}")
                    conn.execute("INSERT INTO plan_stock_booking (production_date, raw_material_id, amount_g, "
                                 "stock_movement_id) VALUES (?, ?, ?, ?)", (day, rmid, r["amount_g"], mid))
                returned.append({"number": r["number"], "name": r["name"], "amount_g": -r["diff_g"]})
    return {"date": day, "booked": booked, "returned": returned}


# ---------------------------------------------------------------------------
# Einstellung „Planer in der Vorwahl“ (K10-P5)
# ---------------------------------------------------------------------------

def get_settings(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT value FROM setting WHERE key = 'planner_in_preselection'").fetchone()
    return {"in_preselection": row is None or str(row["value"]) != "0"}


def save_settings(conn: sqlite3.Connection, data) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("in_preselection"), bool):
        raise ValidationError("„Planer in der Vorwahl“: ja oder nein.", field="in_preselection")
    with transaction(conn):
        conn.execute("INSERT INTO setting (key, value) VALUES ('planner_in_preselection', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", ("1" if data["in_preselection"] else "0",))
    return get_settings(conn)
