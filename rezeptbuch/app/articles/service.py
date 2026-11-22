"""Verkaufsartikel und Stückliste (Modul 10, Teil P-A, docs/planer.md 3 und 5).

* Artikel kommen aus der Vectron-Artikelliste (``vectron.py``, K10-P1); Nummer, Name und Warengruppe
  sind hier nur lesbar. Gepflegt werden „Stück je Ganzes“ (K10-P2), „nicht planen“ (K10-P3), Bemerkung.
* Die Stückliste gilt für **1 Stück** bzw. bei „Stück je Ganzes“ für **1 Ganzes**. Jede Zeile ist ein
  Rezept (Menge in g oder ein Stückgewicht des Rezepts, K10-P6) oder ein Rohstoff (g oder Stück, M10-19).
  Keine Artikel aus Artikeln (M10-19). Unterrezepte werden nicht aufgelöst (K10-P7).
* Archivierte Rezepte/Rohstoffe dürfen nicht neu in eine Stückliste; stehen sie schon drin, bleibt die
  Zeile erhalten und wird als Warnung gemeldet (R10-P8: erst nach Korrektur planbar).
"""

from __future__ import annotations

import json
from fractions import Fraction
import sqlite3

from ..db import transaction
from ..errors import NotFoundError, ValidationError
from ..raw_materials.models import normalize_text
from ..text_rules import check_no_formula_start

MAX_LINES = 30
MAX_NOTE = 500
MAX_PIECES_PER_WHOLE = 1000
MAX_AMOUNT_G = 1_000_000
MAX_AMOUNT_PIECES = 10_000
_NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"

# Vorgabe „Stück je Ganzes“ nach Warengruppe beim Import (K10-P2): Kuchen 12, Torten 14
DEFAULT_PIECES_PER_WHOLE = {12: 12, 13: 14}


def _json(value) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def log(conn: sqlite3.Connection, action: str, article_id: int, old, new, source: str) -> None:
    conn.execute(
        "INSERT INTO change_log (source, entity, entity_id, action, old_values, new_values) "
        "VALUES (?, 'sales_article', ?, ?, ?, ?)",
        (source, article_id, action, _json(old), _json(new)))


def _int(value, field: str, label: str, low: int, high: int, allow_none: bool = False) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_none:
            return None
        raise ValidationError(f"{label}: Pflichtfeld.", field=field)
    if isinstance(value, bool):
        raise ValidationError(f"{label}: bitte eine ganze Zahl.", field=field)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str):
        text = value.strip().replace(".", "").replace(" ", "")
        if not text.lstrip("-").isdigit():
            raise ValidationError(f"{label}: bitte eine ganze Zahl.", field=field)
        value = int(text)
    if not isinstance(value, int):
        raise ValidationError(f"{label}: bitte eine ganze Zahl.", field=field)
    if not low <= value <= high:
        raise ValidationError(f"{label}: {low:,} bis {high:,}.".replace(",", "."), field=field)
    return value


# -- Lesen --------------------------------------------------------------------------

def _fetch(conn: sqlite3.Connection, article_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM sales_article WHERE id = ?", (article_id,)).fetchone()
    if row is None:
        raise NotFoundError("Verkaufsartikel nicht gefunden.", code="not_found")
    return row


def _line_rows(conn: sqlite3.Connection, article_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT l.*, r.number AS recipe_number, r.archived AS recipe_archived, r.locked AS recipe_locked, "
        "       v.name AS recipe_name, p.label AS piece_label, p.weight_g AS piece_g, "
        "       m.number AS raw_number, m.name AS raw_name, m.archived AS raw_archived, "
        "       m.unit_size_g AS raw_unit_g, m.unit_label AS raw_unit_label, m.stock_g AS raw_stock_g "
        "FROM sales_article_line l "
        "LEFT JOIN recipe r ON r.id = l.recipe_id "
        "LEFT JOIN recipe_version v ON v.id = r.current_version_id "
        "LEFT JOIN recipe_piece_weight p ON p.id = l.piece_weight_id "
        "LEFT JOIN raw_material m ON m.id = l.raw_material_id "
        "WHERE l.article_id = ? ORDER BY l.position", (article_id,)).fetchall()


def _line_view(r: sqlite3.Row) -> dict:
    if r["kind"] == "recipe":
        grams = r["amount_g"] if r["amount_g"] is not None else r["piece_g"]
        warning = "Rezept archiviert" if r["recipe_archived"] else None
        return {
            "position": r["position"], "kind": "recipe", "recipe_id": r["recipe_id"],
            "recipe_number": r["recipe_number"], "name": r["recipe_name"],
            "piece_weight_id": r["piece_weight_id"], "piece_weight_label": r["piece_label"],
            "piece_weight_g": r["piece_g"], "amount_g": r["amount_g"], "amount_pieces": None,
            "grams": grams, "warning": warning,
        }
    grams = r["amount_g"]
    if grams is None and r["raw_unit_g"]:
        grams = r["amount_pieces"] * r["raw_unit_g"]
    return {
        "position": r["position"], "kind": "raw", "raw_material_id": r["raw_material_id"],
        "raw_number": r["raw_number"], "name": r["raw_name"], "amount_g": r["amount_g"],
        "amount_pieces": r["amount_pieces"], "unit_size_g": r["raw_unit_g"], "unit_label": r["raw_unit_label"],
        "stock_managed": r["raw_stock_g"] is not None,
        "grams": grams, "warning": "Rohstoff archiviert" if r["raw_archived"] else None,
    }


def _view(conn: sqlite3.Connection, row: sqlite3.Row, with_lines: bool = True) -> dict:
    result = {
        "id": row["id"], "register_no": row["register_no"], "name": row["name"],
        "register_group": row["register_group"], "pieces_per_whole": row["pieces_per_whole"],
        "plan_enabled": bool(row["plan_enabled"]), "in_register": bool(row["in_register"]),
        "last_order_no": row["last_order_no"], "note": row["note"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }
    if with_lines:
        lines = [_line_view(r) for r in _line_rows(conn, row["id"])]
        known = [ln["grams"] for ln in lines if ln["grams"] is not None]
        result["lines"] = lines
        result["sum_g"] = sum(known) if lines else 0
        result["sum_complete"] = len(known) == len(lines)
        result["warnings"] = [f"Zeile {ln['position']}: {ln['warning']}" for ln in lines if ln["warning"]]
        result["per"] = "Ganzes" if row["pieces_per_whole"] else "Stück"
    return result


def get_article(conn: sqlite3.Connection, article_id: int) -> dict:
    return _view(conn, _fetch(conn, article_id))


def list_articles(conn: sqlite3.Connection, *, search: str | None = None, group: int | None = None,
                  status: str = "active", without_lines: bool = False, not_planned: bool = False) -> list[dict]:
    """Liste mit Filtern (docs/planer.md 5).

    ``status``: ``active`` (in der Kasse, Vorgabe), ``missing`` (nicht mehr in der Kasse), ``all``.
    ``search``: Nummer (genau) oder Teil des Namens.
    """
    where, params = [], []
    if status == "active":
        where.append("a.in_register = 1")
    elif status == "missing":
        where.append("a.in_register = 0")
    elif status != "all":
        raise ValidationError("Status: active, missing oder all.", field="status")
    if group is not None:
        where.append("a.register_group = ?")
        params.append(group)
    if not_planned:
        where.append("a.plan_enabled = 0")
    sql = ("SELECT a.*, (SELECT count(*) FROM sales_article_line l WHERE l.article_id = a.id) AS line_count, "
           "(SELECT count(*) FROM sales_article_line l LEFT JOIN recipe r ON r.id = l.recipe_id "
           " LEFT JOIN raw_material m ON m.id = l.raw_material_id "
           " WHERE l.article_id = a.id AND (r.archived = 1 OR m.archived = 1)) AS warn_count "
           "FROM sales_article a" + (" WHERE " + " AND ".join(where) if where else "")
           + " ORDER BY a.register_group, a.register_no")
    result = []
    needle = normalize_text(search).casefold() if isinstance(search, str) and search.strip() else None
    for row in conn.execute(sql, params):
        if without_lines and row["line_count"]:
            continue
        if needle and not (needle == str(row["register_no"]) or needle in row["name"].casefold()):
            continue
        item = _view(conn, row, with_lines=False)
        item["line_count"] = row["line_count"]
        item["has_warning"] = row["warn_count"] > 0
        result.append(item)
    return result


def groups(conn: sqlite3.Connection) -> list[dict]:
    """Warengruppen der vorhandenen Artikel mit Anzahl (Filter der Liste)."""
    return [{"group": r["register_group"], "count": r["n"]} for r in conn.execute(
        "SELECT register_group, count(*) AS n FROM sales_article WHERE in_register = 1 "
        "GROUP BY register_group ORDER BY register_group")]


# -- Ändern -------------------------------------------------------------------------

def _clean_note(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("Bemerkung: bitte Text.", field="note")
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_NOTE:
        raise ValidationError(f"Bemerkung: höchstens {MAX_NOTE} Zeichen.", field="note")
    check_no_formula_start(text, field="note", label="Bemerkung")
    return text


def update_article(conn: sqlite3.Connection, article_id: int, data, source: str = "admin") -> dict:
    """Ändert „Stück je Ganzes“, „nicht planen“ (über ``plan_enabled``) und Bemerkung; fehlende Schlüssel bleiben."""
    if not isinstance(data, dict):
        raise ValidationError("Ungültige Anfrage.")
    with transaction(conn):
        row = _fetch(conn, article_id)
        new = {"pieces_per_whole": row["pieces_per_whole"], "plan_enabled": bool(row["plan_enabled"]),
               "note": row["note"]}
        if "pieces_per_whole" in data:
            new["pieces_per_whole"] = _int(data["pieces_per_whole"], "pieces_per_whole", "Stück je Ganzes",
                                           1, MAX_PIECES_PER_WHOLE, allow_none=True)
        if "plan_enabled" in data:
            if not isinstance(data["plan_enabled"], bool):
                raise ValidationError("„planen“: ja oder nein.", field="plan_enabled")
            new["plan_enabled"] = data["plan_enabled"]
        if "note" in data:
            new["note"] = _clean_note(data["note"])
        old = {"pieces_per_whole": row["pieces_per_whole"], "plan_enabled": bool(row["plan_enabled"]),
               "note": row["note"]}
        if new != old:
            conn.execute(f"UPDATE sales_article SET pieces_per_whole = ?, plan_enabled = ?, note = ?, "
                         f"updated_at = {_NOW} WHERE id = ?",
                         (new["pieces_per_whole"], int(new["plan_enabled"]), new["note"], article_id))
            log(conn, "update", article_id, old, new, source)
    return get_article(conn, article_id)


def _validate_line(conn: sqlite3.Connection, index: int, line, old_refs: set) -> dict:
    prefix = f"Zeile {index}"
    if not isinstance(line, dict):
        raise ValidationError(f"{prefix}: ungültig.", field=f"lines.{index}")
    kind = line.get("kind")
    if kind == "recipe":
        recipe_id = _int(line.get("recipe_id"), f"lines.{index}.recipe_id", f"{prefix}: Rezept", 1, 2**62)
        rec = conn.execute("SELECT id, archived FROM recipe WHERE id = ?", (recipe_id,)).fetchone()
        if rec is None:
            raise ValidationError(f"{prefix}: Rezept nicht gefunden.", field=f"lines.{index}.recipe_id",
                                  code="recipe_not_found")
        if rec["archived"] and ("recipe", recipe_id) not in old_refs:
            raise ValidationError(f"{prefix}: Das Rezept ist archiviert.", field=f"lines.{index}.recipe_id",
                                  code="recipe_archived")
        piece_id = line.get("piece_weight_id")
        if piece_id is not None:
            piece_id = _int(piece_id, f"lines.{index}.piece_weight_id", f"{prefix}: Stückgewicht", 1, 2**62)
            p = conn.execute("SELECT recipe_id FROM recipe_piece_weight WHERE id = ?", (piece_id,)).fetchone()
            if p is None or p["recipe_id"] != recipe_id:
                raise ValidationError(f"{prefix}: Das Stückgewicht gehört nicht zu diesem Rezept.",
                                      field=f"lines.{index}.piece_weight_id", code="piece_weight_missing")
            return {"kind": "recipe", "recipe_id": recipe_id, "piece_weight_id": piece_id, "raw_material_id": None,
                    "amount_g": None, "amount_pieces": None}
        amount = _int(line.get("amount_g"), f"lines.{index}.amount_g", f"{prefix}: Menge in g", 1, MAX_AMOUNT_G)
        return {"kind": "recipe", "recipe_id": recipe_id, "piece_weight_id": None, "raw_material_id": None,
                "amount_g": amount, "amount_pieces": None}
    if kind == "raw":
        raw_id = _int(line.get("raw_material_id"), f"lines.{index}.raw_material_id", f"{prefix}: Rohstoff", 1, 2**62)
        raw = conn.execute("SELECT id, archived, type FROM raw_material WHERE id = ?", (raw_id,)).fetchone()
        if raw is None:
            raise ValidationError(f"{prefix}: Rohstoff nicht gefunden.", field=f"lines.{index}.raw_material_id",
                                  code="raw_material_not_found")
        if raw["type"] == "aid":
            raise ValidationError(f"{prefix}: Hilfs- und Betriebsstoffe stehen nicht in der Stückliste (F-2).",
                                  field=f"lines.{index}.raw_material_id", code="raw_material_aid")
        if raw["archived"] and ("raw", raw_id) not in old_refs:
            raise ValidationError(f"{prefix}: Der Rohstoff ist archiviert.", field=f"lines.{index}.raw_material_id",
                                  code="raw_material_archived")
        has_g = line.get("amount_g") not in (None, "")
        has_pcs = line.get("amount_pieces") not in (None, "")
        if has_g == has_pcs:
            raise ValidationError(f"{prefix}: Menge in g oder in Stück angeben (genau eins).",
                                  field=f"lines.{index}.amount_g")
        if has_g:
            amount = _int(line["amount_g"], f"lines.{index}.amount_g", f"{prefix}: Menge in g", 1, MAX_AMOUNT_G)
            return {"kind": "raw", "recipe_id": None, "piece_weight_id": None, "raw_material_id": raw_id,
                    "amount_g": amount, "amount_pieces": None}
        pieces = _int(line["amount_pieces"], f"lines.{index}.amount_pieces", f"{prefix}: Stück", 1, MAX_AMOUNT_PIECES)
        return {"kind": "raw", "recipe_id": None, "piece_weight_id": None, "raw_material_id": raw_id,
                "amount_g": None, "amount_pieces": pieces}
    raise ValidationError(f"{prefix}: Art „Rezept“ oder „Rohstoff“ wählen.", field=f"lines.{index}.kind")


def _stored_lines(conn: sqlite3.Connection, article_id: int) -> list[dict]:
    return [{k: r[k] for k in ("kind", "recipe_id", "piece_weight_id", "raw_material_id", "amount_g",
                               "amount_pieces")}
            for r in conn.execute("SELECT * FROM sales_article_line WHERE article_id = ? ORDER BY position",
                                  (article_id,))]


def set_lines_in_tx(conn: sqlite3.Connection, article_id: int, lines, source: str = "admin") -> None:
    if not isinstance(lines, list):
        raise ValidationError("Stückliste: bitte eine Liste von Zeilen.", field="lines")
    if len(lines) > MAX_LINES:
        raise ValidationError(f"Stückliste: höchstens {MAX_LINES} Zeilen.", field="lines")
    _fetch(conn, article_id)
    old = _stored_lines(conn, article_id)
    old_refs = {("recipe", ln["recipe_id"]) for ln in old if ln["recipe_id"]} | \
               {("raw", ln["raw_material_id"]) for ln in old if ln["raw_material_id"]}
    clean = [_validate_line(conn, i, line, old_refs) for i, line in enumerate(lines, start=1)]
    if clean == old:
        return
    conn.execute("DELETE FROM sales_article_line WHERE article_id = ?", (article_id,))
    for position, ln in enumerate(clean, start=1):
        conn.execute(
            "INSERT INTO sales_article_line (article_id, position, kind, recipe_id, piece_weight_id, "
            "raw_material_id, amount_g, amount_pieces) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (article_id, position, ln["kind"], ln["recipe_id"], ln["piece_weight_id"], ln["raw_material_id"],
             ln["amount_g"], ln["amount_pieces"]))
    conn.execute(f"UPDATE sales_article SET updated_at = {_NOW} WHERE id = ?", (article_id,))
    log(conn, "update", article_id, {"lines": old}, {"lines": clean}, source)


def set_lines(conn: sqlite3.Connection, article_id: int, lines, source: str = "admin") -> dict:
    """Ersetzt die ganze Stückliste eines Artikels (Reihenfolge = Liste)."""
    with transaction(conn):
        set_lines_in_tx(conn, article_id, lines, source)
    return get_article(conn, article_id)


def copy_lines(conn: sqlite3.Connection, article_id: int, from_article_id, source: str = "admin") -> dict:
    """„Stückliste kopieren von …“ (docs/planer.md 5): ersetzt die Stückliste durch die des anderen Artikels."""
    from_id = _int(from_article_id, "from_article_id", "Artikel", 1, 2**62)
    if from_id == article_id:
        raise ValidationError("Bitte einen anderen Artikel wählen.", field="from_article_id")
    with transaction(conn):
        _fetch(conn, from_id)
        set_lines_in_tx(conn, article_id, _stored_lines(conn, from_id), source)
    return get_article(conn, article_id)


BULK_ACTIONS = ("plan_disable", "plan_enable", "pieces_per_whole")


def bulk(conn: sqlite3.Connection, data, source: str = "admin") -> dict:
    """Sammelaktionen (docs/planer.md 5): „nicht planen“ setzen/entfernen, „Stück je Ganzes“ setzen/leeren."""
    if not isinstance(data, dict):
        raise ValidationError("Ungültige Anfrage.")
    ids = data.get("ids")
    if not isinstance(ids, list) or not ids or len(ids) > 2000 or \
            not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise ValidationError("Bitte 1 bis 2000 Artikel auswählen.", field="ids")
    action = data.get("action")
    if action not in BULK_ACTIONS:
        raise ValidationError("Unbekannte Sammelaktion.", field="action")
    value = None
    if action == "pieces_per_whole":
        value = _int(data.get("value"), "value", "Stück je Ganzes", 1, MAX_PIECES_PER_WHOLE, allow_none=True)
    changed = 0
    with transaction(conn):
        for article_id in dict.fromkeys(ids):
            row = conn.execute("SELECT * FROM sales_article WHERE id = ?", (article_id,)).fetchone()
            if row is None:
                continue
            if action == "pieces_per_whole":
                if row["pieces_per_whole"] == value:
                    continue
                conn.execute(f"UPDATE sales_article SET pieces_per_whole = ?, updated_at = {_NOW} WHERE id = ?",
                             (value, article_id))
                log(conn, "update", article_id, {"pieces_per_whole": row["pieces_per_whole"]},
                    {"pieces_per_whole": value}, source)
            else:
                flag = 1 if action == "plan_enable" else 0
                if row["plan_enabled"] == flag:
                    continue
                conn.execute(f"UPDATE sales_article SET plan_enabled = ?, updated_at = {_NOW} WHERE id = ?",
                             (flag, article_id))
                log(conn, "update", article_id, {"plan_enabled": bool(row["plan_enabled"])},
                    {"plan_enabled": bool(flag)}, source)
            changed += 1
    return {"changed": changed}


# ---------------------------------------------------------------------------
# Sammelaktion „Austauschen“ (K10-P25, docs/planer.md 5)
# ---------------------------------------------------------------------------

REPLACE_KINDS = ("recipe", "raw", "piece_weight")


def parse_factor(value) -> Fraction:
    """Faktor wie „1,25“ (0,01 bis 100, höchstens zwei Nachkommastellen); leer = 1."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return Fraction(1)
    text = str(value).strip().replace(",", ".")
    try:
        f = Fraction(text)
    except (ValueError, ZeroDivisionError):
        raise ValidationError("Faktor bitte als Zahl, z. B. 1,25.", field="factor") from None
    if (f * 100).denominator != 1 or not Fraction(1, 100) <= f <= 100:
        raise ValidationError("Faktor 0,01 bis 100 mit höchstens zwei Nachkommastellen.", field="factor")
    return f


def _round(x: Fraction) -> int:
    return max(1, int(x + Fraction(1, 2)))


def replace_in_lines(conn: sqlite3.Connection, data, source: str = "admin") -> dict:
    """Rezept, Rohstoff oder Stückgewicht in allen oder ausgewählten Stücklisten ersetzen (``mode`` check/run)."""
    if not isinstance(data, dict):
        raise ValidationError("Ungültige Anfrage.")
    kind = data.get("kind")
    if kind not in REPLACE_KINDS:
        raise ValidationError("Was soll ersetzt werden: Rezept, Rohstoff oder Stückgewicht?", field="kind")
    from_id = _int(data.get("from_id"), "from_id", "Bisher", 1, 10**9)
    to_id = _int(data.get("to_id"), "to_id", "Neu", 1, 10**9)
    if from_id == to_id:
        raise ValidationError("Bisher und neu sind gleich.", field="to_id")
    factor = parse_factor(data.get("factor"))
    mode = data.get("mode") or "check"
    if mode not in ("check", "run"):
        raise ValidationError("mode: check oder run.", field="mode")
    ids = data.get("article_ids")
    if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, int) for i in ids)):
        raise ValidationError("Ungültige Artikelauswahl.", field="article_ids")

    hints: list[str] = []
    if kind == "recipe":
        target = conn.execute("SELECT r.id, r.archived, r.number, v.name FROM recipe r LEFT JOIN recipe_version v "
                              "ON v.id = r.current_version_id WHERE r.id = ?", (to_id,)).fetchone()
        column = "recipe_id"
    elif kind == "raw":
        target = conn.execute("SELECT id, archived, number, name FROM raw_material WHERE id = ?", (to_id,)).fetchone()
        column = "raw_material_id"
    else:
        target = conn.execute("SELECT p.id, p.recipe_id, p.label AS name, r.archived, r.number FROM recipe_piece_weight p "
                              "JOIN recipe r ON r.id = p.recipe_id WHERE p.id = ?", (to_id,)).fetchone()
        column = "piece_weight_id"
    if target is None:
        raise NotFoundError("Ersatz nicht gefunden.", field="to_id", code="not_found")
    if target["archived"]:
        raise ValidationError("Der Ersatz ist archiviert.", field="to_id", code="target_archived")
    sql = (f"SELECT l.*, a.register_no, a.name AS article_name, p.weight_g AS pw_g FROM sales_article_line l "
           f"JOIN sales_article a ON a.id = l.article_id LEFT JOIN recipe_piece_weight p ON p.id = l.piece_weight_id "
           f"WHERE l.{column} = ?")
    params: list = [from_id]
    if ids:
        sql += f" AND l.article_id IN ({','.join('?' * len(ids))})"
        params += ids
    lines = conn.execute(sql + " ORDER BY a.register_no, l.position", params).fetchall()
    converted = 0
    updates = []
    for ln in lines:
        if kind == "recipe":
            if ln["piece_weight_id"] is not None:
                converted += 1
                updates.append((ln["id"], {"recipe_id": to_id, "piece_weight_id": None,
                                           "amount_g": _round(ln["pw_g"] * factor)}))
            else:
                updates.append((ln["id"], {"recipe_id": to_id, "amount_g": _round(ln["amount_g"] * factor)}))
        elif kind == "raw":
            if ln["amount_g"] is not None:
                updates.append((ln["id"], {"raw_material_id": to_id, "amount_g": _round(ln["amount_g"] * factor)}))
            else:
                updates.append((ln["id"], {"raw_material_id": to_id,
                                           "amount_pieces": _round(ln["amount_pieces"] * factor)}))
        else:
            updates.append((ln["id"], {"recipe_id": target["recipe_id"], "piece_weight_id": to_id}))
    if converted:
        hints.append(f"{converted} Zeile{'n' if converted != 1 else ''} mit Stückgewicht werden in Gramm umgewandelt "
                     "(das Stückgewicht gehört zum bisherigen Rezept).")
    if kind == "piece_weight" and factor != 1:
        hints.append("Beim Stückgewicht gilt kein Faktor – es wird nur ausgetauscht.")
    articles = sorted({f"{ln['register_no']} {ln['article_name']}" for ln in lines})
    report = {"kind": kind, "lines": len(lines), "articles": articles, "hints": hints,
              "target": f"{target['number']} {target['name']}" if kind != "piece_weight" else target["name"],
              "done": False}
    if mode == "check" or not lines:
        return report
    with transaction(conn):
        touched = set()
        for line_id, values in updates:
            sets = ", ".join(f"{k} = ?" for k in values)
            conn.execute(f"UPDATE sales_article_line SET {sets} WHERE id = ?", (*values.values(), line_id))
        for ln in lines:
            touched.add(ln["article_id"])
        for article_id in touched:
            log(conn, "update", article_id, {"replace": {"kind": kind, "from_id": from_id}},
                {"replace": {"kind": kind, "to_id": to_id, "factor": str(factor)}}, source)
            conn.execute("UPDATE sales_article SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                         (article_id,))
    report["done"] = True
    return report
