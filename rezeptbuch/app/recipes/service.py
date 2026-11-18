"""Rezeptverwaltung: Regeln, Versionen, Transaktionen und Änderungsprotokoll (Modul 05).

Die Regeln R05-1 bis R05-28 stehen in docs/rezepte.md, Abschnitt 4. Alle Funktionen
arbeiten auf einer übergebenen Datenbankverbindung (eine eigene je Anfrage, K03-1).
Schreibvorgänge laufen in einer Transaktion mit ``BEGIN IMMEDIATE``. Router und Seiten
enthalten keine Fachlogik; der Vorlagen-Import (Teil C3) nutzt die Funktionen mit
``_in_tx`` in seiner einen Transaktion.

Begriffe:

* **Rezept** (Tabelle ``recipe``): Nummer, Gruppe, gesperrt, archiviert, Bearbeitungsstand.
* **Version** (``recipe_version``): Name, Knetzeit, Hinweis, Schritte und Zeilen. Eine
  gewogene Version (``frozen_at`` gesetzt) wird nie mehr geändert (K4, R05-16).
* Stückgewichte und Chargengrößen gehören zum Rezept, nicht zur Version (M05-2).
"""

from __future__ import annotations

import json
import sqlite3

from ..db import transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from ..raw_materials.models import normalize_text, tolerance_display
from ..text_rules import check_no_formula_start
from .models import (
    MAX_NAME,
    VERSION_MODES,
    validate_batch_sizes,
    validate_piece_weights,
    validate_recipe,
)

MSG_NEW_VERSION_FROZEN = "Neue Version angelegt, da bereits produziert."
MSG_NEW_VERSION = "Neue Version angelegt."
MSG_OVERWRITTEN = "Aktuelle Version überschrieben."
MSG_UNCHANGED = "Keine Änderung am Rezeptinhalt."


# -- Hilfen ----------------------------------------------------------------------

def _json(value) -> str | None:
    return json.dumps(value, ensure_ascii=False) if value is not None else None


def _log(conn: sqlite3.Connection, action: str, recipe_id: int, old, new, source: str) -> None:
    conn.execute(
        "INSERT INTO change_log (source, entity, entity_id, action, old_values, new_values) "
        "VALUES (?, 'recipe', ?, ?, ?, ?)",
        (source, recipe_id, action, _json(old), _json(new)))


def name_key(name: str) -> str:
    """Vergleichsschlüssel für Rezeptnamen (wie R03-2): ohne Randleerzeichen, ohne Groß-/Kleinschreibung."""
    return normalize_text(name or "").casefold()


_RECIPE_SELECT = (
    "SELECT r.id, r.number, r.group_id, r.current_version_id, r.locked, r.archived, r.created_at, "
    "       r.revision, r.internal_note, v.version_no, v.name, v.knead_slow_min, v.knead_fast_min, v.note, v.note_display, "
    "       v.created_at AS version_created_at, v.frozen_at, g.name AS group_name "
    "FROM recipe r "
    "LEFT JOIN recipe_version v ON v.id = r.current_version_id "
    "LEFT JOIN recipe_group g ON g.id = r.group_id ")


def _fetch(conn: sqlite3.Connection, recipe_id: int) -> sqlite3.Row:
    row = conn.execute(_RECIPE_SELECT + "WHERE r.id = ?", (recipe_id,)).fetchone()
    if row is None:
        raise NotFoundError("Rezept nicht gefunden.", code="not_found")
    return row


def _find_active_with_name(conn: sqlite3.Connection, name: str, exclude_id: int | None = None):
    """Nicht archiviertes Rezept mit gleichem Namen der aktuellen Version (R05-2)."""
    key = name_key(name)
    for row in conn.execute(
            "SELECT r.id, r.number, v.name FROM recipe r JOIN recipe_version v ON v.id = r.current_version_id "
            "WHERE r.archived = 0"):
        if row["id"] != exclude_id and name_key(row["name"]) == key:
            return row
    return None


def _check_name_free(conn, name: str, exclude_id: int | None = None) -> None:
    same = _find_active_with_name(conn, name, exclude_id)
    if same is not None:
        raise ConflictError(f"Ein Rezept „{same['name']}“ gibt es schon (Nummer {same['number']}).",
                            field="name", code="name_taken")


def _integrity(exc: sqlite3.IntegrityError) -> ConflictError:
    return ConflictError(f"Das Rezept konnte nicht gespeichert werden: {exc}", code="integrity")


def knead_text(slow: int | None, fast: int | None) -> str | None:
    """Knetzeit als „5+6“ (M02-13); leer, wenn beide fehlen."""
    if slow is None and fast is None:
        return None
    return f"{slow if slow is not None else 0}+{fast if fast is not None else 0}"


# -- Lesen ----------------------------------------------------------------------

def next_number(conn: sqlite3.Connection) -> int:
    """Nummernvorschlag: höchste vorhandene Nummer + 1 (archivierte zählen mit, R05-1)."""
    return conn.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM recipe").fetchone()[0]


def usage(conn: sqlite3.Connection, recipe_id: int) -> dict:
    """Wo das Rezept verwendet wird.

    * ``orders``: Aufträge mit diesem Rezept
    * ``sub_recipe_any``: Anzahl Zeilen in irgendeiner Version irgendeines Rezepts (sperrt Nummer und Löschen)
    * ``parents``: nicht archivierte Rezepte, deren **aktuelle** Version es als Unterrezept enthält (R05-22)
    """
    orders = conn.execute("SELECT count(*) FROM production_order WHERE recipe_id = ?",
                          (recipe_id,)).fetchone()[0]
    sub_any = conn.execute("SELECT count(*) FROM recipe_item WHERE sub_recipe_id = ?",
                           (recipe_id,)).fetchone()[0]
    parents = [
        {"id": r["id"], "number": r["number"], "name": r["name"]}
        for r in conn.execute(
            "SELECT DISTINCT r.id, r.number, v.name FROM recipe_item i "
            "JOIN recipe r ON r.current_version_id = i.recipe_version_id "
            "JOIN recipe_version v ON v.id = r.current_version_id "
            "WHERE i.sub_recipe_id = ? AND r.archived = 0 AND r.id <> ? ORDER BY r.number",
            (recipe_id, recipe_id))]
    return {"orders": orders, "sub_recipe_any": sub_any, "parents": parents,
            "used": bool(orders or sub_any)}


def _tolerance(unit: str | None, value: int | None) -> dict | None:
    if unit is None:
        return None
    return {"unit": unit, "value": tolerance_display(unit, value)}


def _items(conn: sqlite3.Connection, version_id: int) -> list[dict]:
    """Zeilen einer Version mit allem, was Admin-Seite und Station brauchen."""
    rows = conn.execute(
        "SELECT i.id, i.position, i.item_type, i.raw_material_id, i.sub_recipe_id, i.amount_g, "
        "       i.tolerance_unit, i.tolerance_value, i.step_no, i.needs_review, "
        "       m.number AS rm_number, m.name AS rm_name, m.display_name AS rm_display, m.type AS rm_type, "
        "       m.tolerance_unit AS rm_tol_unit, m.tolerance_value AS rm_tol_value, "
        "       m.unit_size_g, m.unit_label, m.archived AS rm_archived, "
        "       s.number AS sub_number, s.locked AS sub_locked, s.archived AS sub_archived, "
        "       sv.name AS sub_name "
        "FROM recipe_item i "
        "LEFT JOIN raw_material m ON m.id = i.raw_material_id "
        "LEFT JOIN recipe s ON s.id = i.sub_recipe_id "
        "LEFT JOIN recipe_version sv ON sv.id = s.current_version_id "
        "WHERE i.recipe_version_id = ? ORDER BY i.position", (version_id,))
    result = []
    for r in rows:
        item = {
            "id": r["id"],
            "position": r["position"],
            "type": r["item_type"],
            "step_no": r["step_no"],
            "amount_g": r["amount_g"],
            "needs_review": bool(r["needs_review"]),
        }
        if r["item_type"] == "raw_material":
            override = _tolerance(r["tolerance_unit"], r["tolerance_value"])
            effective = override or _tolerance(r["rm_tol_unit"], r["rm_tol_value"])
            item.update({
                # 0 g = Handzugabe nach Bedarf (M02-15)
                "hand_addition": r["amount_g"] == 0,
                "tolerance_override": override,
                "tolerance": effective,
                "raw_material": {
                    "id": r["raw_material_id"],
                    "number": r["rm_number"],
                    "name": r["rm_name"],
                    "display_name": r["rm_display"],
                    "station_name": r["rm_display"] or r["rm_name"],
                    "type": r["rm_type"],
                    "unit_size_g": r["unit_size_g"],
                    "unit_label": r["unit_label"],
                    "archived": bool(r["rm_archived"]),
                },
            })
        else:
            item.update({
                "hand_addition": False,
                "tolerance_override": None,
                "tolerance": None,
                "sub_recipe": {
                    "id": r["sub_recipe_id"],
                    "number": r["sub_number"],
                    "name": r["sub_name"],
                    "locked": bool(r["sub_locked"]),
                    "archived": bool(r["sub_archived"]),
                },
            })
        result.append(item)
    return result


def _steps(conn: sqlite3.Connection, version_id: int) -> list[dict]:
    return [{"step_no": r["step_no"], "name": r["name"]} for r in conn.execute(
        "SELECT step_no, name FROM recipe_version_step WHERE recipe_version_id = ? ORDER BY step_no",
        (version_id,))]


def _sums(items: list[dict]) -> dict:
    """Gesamtgewicht und Summe Mehl der direkten Zeilen (R05-27, M05-10)."""
    total = sum(i["amount_g"] for i in items)
    flour = sum(i["amount_g"] for i in items
                if i["type"] == "raw_material" and i["raw_material"]["type"] == "flour")
    return {"total_g": total, "flour_g": flour}


def _versions(conn: sqlite3.Connection, recipe_id: int, current_id: int | None) -> list[dict]:
    """Versionsliste, neueste zuerst; alte Versionen als „old (n)“ (M02-4b, R05-18)."""
    rows = conn.execute(
        "SELECT v.id, v.version_no, v.name, v.created_at, v.frozen_at, "
        "       EXISTS (SELECT 1 FROM production_order o WHERE o.recipe_version_id = v.id) AS produced "
        "FROM recipe_version v WHERE v.recipe_id = ? ORDER BY v.version_no DESC", (recipe_id,))
    return [{
        "version_no": r["version_no"],
        "name": r["name"],
        "current": r["id"] == current_id,
        "label": "aktuell" if r["id"] == current_id else f"old ({r['version_no']})",
        "created_at": r["created_at"],
        "frozen": r["frozen_at"] is not None,
        "produced": bool(r["produced"]),
    } for r in rows]


def _piece_weights(conn: sqlite3.Connection, recipe_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, label, weight_g FROM recipe_piece_weight WHERE recipe_id = ? ORDER BY sort_order, id",
        (recipe_id,))]


def _batch_sizes(conn: sqlite3.Connection, recipe_id: int) -> list[dict]:
    return [{
        "id": r["id"], "label": r["label"], "kind": r["kind"], "value": r["value"],
        "piece_weight_id": r["piece_weight_id"], "piece_weight_label": r["piece_label"],
        "piece_weight_g": r["piece_g"],
    } for r in conn.execute(
        "SELECT b.id, b.label, b.kind, b.value, b.piece_weight_id, p.label AS piece_label, p.weight_g AS piece_g "
        "FROM recipe_batch_size b LEFT JOIN recipe_piece_weight p ON p.id = b.piece_weight_id "
        "WHERE b.recipe_id = ? ORDER BY b.sort_order, b.id", (recipe_id,))]


def _version_view(conn, recipe_id: int, version_row) -> dict:
    items = _items(conn, version_row["id"])
    return {
        "version_no": version_row["version_no"],
        "name": version_row["name"],
        "knead_slow_min": version_row["knead_slow_min"],
        "knead_fast_min": version_row["knead_fast_min"],
        "knead": knead_text(version_row["knead_slow_min"], version_row["knead_fast_min"]),
        "note": version_row["note"],
        "note_display": version_row["note_display"],
        "created_at": version_row["created_at"],
        "frozen": version_row["frozen_at"] is not None,
        "steps": _steps(conn, version_row["id"]),
        "items": items,
        "sums": _sums(items),
        "review_count": sum(1 for i in items if i["needs_review"]),
    }


def get_recipe(conn: sqlite3.Connection, recipe_id: int, include_internal: bool = True) -> dict:
    """Rezept mit aktueller Version, Stückgewichten, Chargengrößen, Summen und Versionsliste.

    Die interne Notiz (KC2-2) steht nur mit ``include_internal`` im Ergebnis; die Lese-
    Schnittstelle der Stationen (ohne PIN) ruft ohne sie auf.
    """
    row = _fetch(conn, recipe_id)
    version = conn.execute("SELECT * FROM recipe_version WHERE id = ?", (row["current_version_id"],)).fetchone()
    use = usage(conn, recipe_id)
    result = {
        "id": row["id"],
        "number": row["number"],
        "number_locked": use["used"],
        "group_id": row["group_id"],
        "group_name": row["group_name"],
        "locked": bool(row["locked"]),
        "archived": bool(row["archived"]),
        "revision": row["revision"],
        "created_at": row["created_at"],
        "piece_weights": _piece_weights(conn, recipe_id),
        "batch_sizes": _batch_sizes(conn, recipe_id),
        "versions": _versions(conn, recipe_id, row["current_version_id"]),
        "usage": use,
    }
    if include_internal:
        result["internal_note"] = row["internal_note"]
    result.update(_version_view(conn, recipe_id, version))
    return result


def _item_key(item: dict) -> tuple:
    if item["type"] == "raw_material":
        return ("raw_material", item["raw_material"]["id"])
    return ("sub_recipe", item["sub_recipe"]["id"])


def _compare_with_current(old_items: list[dict], current_items: list[dict]) -> list[dict]:
    """Vergleich einer alten Version mit der aktuellen (C3-E10).

    Zuordnung über den Rohstoff bzw. das Unterrezept, nicht über die Position; kommt er mehrfach
    vor, der Reihe nach. Jede alte Zeile bekommt ``current`` (Menge der aktuellen Version, ``same``)
    oder ``current = {"missing": True}``. Rückgabe: Zeilen, die es nur in der aktuellen Version gibt.
    """
    queues: dict[tuple, list[dict]] = {}
    for item in current_items:
        queues.setdefault(_item_key(item), []).append(item)
    for item in old_items:
        queue = queues.get(_item_key(item))
        if queue:
            match = queue.pop(0)
            item["current"] = {"amount_g": match["amount_g"], "same": match["amount_g"] == item["amount_g"],
                               "missing": False}
        else:
            item["current"] = {"amount_g": None, "same": False, "missing": True}
    rest = [i for queue in queues.values() for i in queue]
    rest.sort(key=lambda i: i["position"])
    return [{
        "position": i["position"], "type": i["type"], "amount_g": i["amount_g"],
        "name": i["raw_material"]["name"] if i["type"] == "raw_material" else i["sub_recipe"]["name"],
        "number": i["raw_material"]["number"] if i["type"] == "raw_material" else i["sub_recipe"]["number"],
    } for i in rest]


def get_version(conn: sqlite3.Connection, recipe_id: int, version_no: int) -> dict:
    """Eine (auch alte) Version, nur zum Ansehen (M05-8).

    Bei einer alten Version enthält jede Zeile zusätzlich ``current`` (Menge in der aktuellen
    Version) und das Ergebnis ``current_only`` (Zeilen nur in der aktuellen Version, C3-E10).
    """
    row = _fetch(conn, recipe_id)
    version = conn.execute("SELECT * FROM recipe_version WHERE recipe_id = ? AND version_no = ?",
                           (recipe_id, version_no)).fetchone()
    if version is None:
        raise NotFoundError("Version nicht gefunden.", code="not_found")
    current = version["id"] == row["current_version_id"]
    result = {"recipe_id": recipe_id, "number": row["number"], "current": current,
              "label": "aktuell" if current else f"old ({version['version_no']})"}
    result.update(_version_view(conn, recipe_id, version))
    result["display_name"] = result["name"] if current else f"{result['name']} {result['label']}"
    if not current and row["current_version_id"] is not None:
        current_items = _items(conn, row["current_version_id"])
        result["current_only"] = _compare_with_current(result["items"], current_items)
        result["current_version_no"] = row["version_no"]
    return result


_ARCHIVED_RM_COUNT = (
    "(SELECT count(*) FROM recipe_item ai JOIN raw_material am ON am.id = ai.raw_material_id "
    " WHERE ai.recipe_version_id = v.id AND am.archived = 1)")


def list_recipes(conn: sqlite3.Connection, search: str | None = None, group_id: int | None = None,
                 include_locked: bool = False, include_archived: bool = False,
                 archived_raw_materials: bool = False, include_public: bool = True,
                 never_weighed: bool = False, has_sub_recipes: bool = False) -> list[dict]:
    """Liste nach Nummer. Vorgabe = was die Vorwahl zeigt: freigeschaltet, nicht archiviert (M05-5).

    ``archived_raw_materials``: nur Rezepte, deren aktuelle Version einen archivierten Rohstoff
    enthält (KC2-5).
    """
    where, params = [], []
    if archived_raw_materials:
        where.append(_ARCHIVED_RM_COUNT + " > 0")
    if not include_public:
        where.append("r.locked = 1")                      # „öffentlich“ ausblenden
    if never_weighed:                                      # nie in einem Auftrag oder einer Charge verwendet
        where.append("NOT EXISTS (SELECT 1 FROM production_order po WHERE po.recipe_id = r.id) AND NOT EXISTS "
                     "(SELECT 1 FROM batch b JOIN recipe_version bv ON bv.id = b.recipe_version_id WHERE bv.recipe_id = r.id)")
    if has_sub_recipes:                                    # aktuelle Version enthält Unterrezepte
        where.append("EXISTS (SELECT 1 FROM recipe_item si WHERE si.recipe_version_id = v.id AND si.sub_recipe_id IS NOT NULL)")
    if not include_locked:
        where.append("r.locked = 0")
    if not include_archived:
        where.append("r.archived = 0")
    if group_id is not None:
        where.append("r.group_id = ?")
        params.append(group_id)
    sql = (
        "SELECT r.id, r.number, r.group_id, g.name AS group_name, r.locked, r.archived, "
        "       v.version_no, v.name, v.knead_slow_min, v.knead_fast_min, "
        "       (SELECT COALESCE(SUM(amount_g), 0) FROM recipe_item WHERE recipe_version_id = v.id) AS total_g, "
        "       (SELECT count(*) FROM recipe_item WHERE recipe_version_id = v.id) AS item_count, "
        "       (SELECT count(*) FROM recipe_item WHERE recipe_version_id = v.id AND needs_review = 1) AS review_count, "
        "       " + _ARCHIVED_RM_COUNT + " AS archived_rm_count "
        "FROM recipe r JOIN recipe_version v ON v.id = r.current_version_id "
        "LEFT JOIN recipe_group g ON g.id = r.group_id "
        + ("WHERE " + " AND ".join(where) + " " if where else "") + "ORDER BY r.number")
    result = [{
        "id": r["id"], "number": r["number"], "name": r["name"],
        "group_id": r["group_id"], "group_name": r["group_name"],
        "locked": bool(r["locked"]), "archived": bool(r["archived"]),
        "version_no": r["version_no"], "knead": knead_text(r["knead_slow_min"], r["knead_fast_min"]),
        "total_g": r["total_g"], "item_count": r["item_count"], "review_count": r["review_count"],
        "archived_raw_material_count": r["archived_rm_count"],
    } for r in conn.execute(sql, params)]
    if search and search.strip():
        text = normalize_text(search).strip()
        prefix = text[:2].upper()
        if prefix in ("R:", "K:"):
            # Operatoren: „R:Sonnenblumen“ = Rohstoffname, „K:Sonnenbl“ = Kurzname (nur Zeilen der aktuellen Version)
            needle = text[2:].strip().casefold()
            column = "am.name" if prefix == "R:" else "am.display_name"
            matches = {row["rid"] for row in conn.execute(
                "SELECT DISTINCT r.id AS rid, " + column + " AS value FROM recipe r "
                "JOIN recipe_item ai ON ai.recipe_version_id = r.current_version_id "
                "JOIN raw_material am ON am.id = ai.raw_material_id") if row["value"] and needle in row["value"].casefold()}
            result = [r for r in result if r["id"] in matches] if needle else result
        else:
            needle = text.casefold()
            result = [r for r in result if needle in r["name"].casefold() or needle in str(r["number"])]
    return result


# -- Prüfungen beim Speichern -------------------------------------------------------------

def _current_rows(conn, version_id: int | None) -> list[sqlite3.Row]:
    if version_id is None:
        return []
    return conn.execute("SELECT * FROM recipe_item WHERE recipe_version_id = ? ORDER BY position",
                        (version_id,)).fetchall()


def _apply_review_rule(clean_items: list[dict], current_items: list[sqlite3.Row]) -> None:
    """„*“ bleibt nur, wenn die Seite es mitschickt und die Zeile unverändert ist (R05-14).

    Unverändert = dieselbe Zeile (ID aus der aktuellen Version) mit gleichem Rohstoff bzw.
    Unterrezept und gleicher Menge. Neue Zeilen bekommen nie ein „*“.
    """
    by_id = {r["id"]: r for r in current_items}
    for item in clean_items:
        original = by_id.get(item["original_id"])
        keep = (item["needs_review"] and original is not None and original["needs_review"] == 1
                and original["item_type"] == item["item_type"]
                and original["raw_material_id"] == item["raw_material_id"]
                and original["sub_recipe_id"] == item["sub_recipe_id"]
                and original["amount_g"] == item["amount_g"])
        item["needs_review"] = bool(keep)


def _check_references(conn, recipe_id: int | None, clean: dict, current_items: list[sqlite3.Row]) -> None:
    """Rohstoffe und Unterrezepte vorhanden, archivierte nicht neu wählbar (R05-8, R05-9)."""
    kept_rm = {r["raw_material_id"] for r in current_items if r["raw_material_id"] is not None}
    kept_sub = {r["sub_recipe_id"] for r in current_items if r["sub_recipe_id"] is not None}
    for item in clean["items"]:
        where = f"Zeile {item['position']}"
        if item["item_type"] == "raw_material":
            rm = conn.execute("SELECT name, archived FROM raw_material WHERE id = ?",
                              (item["raw_material_id"],)).fetchone()
            if rm is None:
                raise ValidationError(f"{where}: Rohstoff nicht gefunden.",
                                      field=f"items.{item['position']}.raw_material_id", code="not_found")
            if rm["archived"] and item["raw_material_id"] not in kept_rm:
                raise ValidationError(
                    f"{where}: Der Rohstoff „{rm['name']}“ ist archiviert und kann nicht neu verwendet werden.",
                    field=f"items.{item['position']}.raw_material_id", code="raw_material_archived")
        else:
            sub = conn.execute(
                "SELECT r.archived, v.name FROM recipe r JOIN recipe_version v ON v.id = r.current_version_id "
                "WHERE r.id = ?", (item["sub_recipe_id"],)).fetchone()
            if sub is None:
                raise ValidationError(f"{where}: Unterrezept nicht gefunden.",
                                      field=f"items.{item['position']}.sub_recipe_id", code="not_found")
            if sub["archived"] and item["sub_recipe_id"] not in kept_sub:
                raise ValidationError(
                    f"{where}: Das Rezept „{sub['name']}“ ist archiviert und kann nicht als Unterrezept "
                    "verwendet werden.", field=f"items.{item['position']}.sub_recipe_id", code="sub_recipe_archived")


def _check_cycle(conn, recipe_id: int, name: str, sub_ids: list[int]) -> None:
    """Keine Kreise über die aktuellen Versionen aller Rezepte (R05-10); Meldung mit dem Weg."""
    edges: dict[int, set[int]] = {}
    for r in conn.execute(
            "SELECT r.id AS parent, i.sub_recipe_id AS child FROM recipe r "
            "JOIN recipe_item i ON i.recipe_version_id = r.current_version_id WHERE i.sub_recipe_id IS NOT NULL"):
        edges.setdefault(r["parent"], set()).add(r["child"])
    edges[recipe_id] = set(sub_ids)

    def names(ids: list[int]) -> list[str]:
        result = []
        for rid in ids:
            if rid == recipe_id:
                result.append(name)
            else:
                row = conn.execute("SELECT v.name FROM recipe r JOIN recipe_version v ON v.id = r.current_version_id "
                                   "WHERE r.id = ?", (rid,)).fetchone()
                result.append(row["name"] if row else str(rid))
        return result

    # Tiefensuche ab dem gespeicherten Rezept: führt ein Weg zurück zu ihm?
    stack = [(child, [recipe_id, child]) for child in sorted(edges[recipe_id])]
    seen: set[int] = set()
    while stack:
        node, path = stack.pop()
        if node == recipe_id:
            raise ConflictError("Kreis bei Unterrezepten: " + " → ".join(names(path)),
                                field="items", code="cycle", path=names(path))
        if node in seen:
            continue
        seen.add(node)
        for child in sorted(edges.get(node, ())):
            stack.append((child, [*path, child]))


def _check_step_names(clean: dict, old_names: set[str]) -> None:
    """Sperre B2 für neue oder geänderte Schrittnamen (R05-3)."""
    for index, step in enumerate(clean["steps"], start=1):
        if step not in old_names:
            check_no_formula_start(step, field=f"steps.{index}.name", label=f"Schritt {index}: Name")


def _check_group(conn, group_id: int | None) -> None:
    if group_id is not None and conn.execute("SELECT 1 FROM recipe_group WHERE id = ?", (group_id,)).fetchone() is None:
        raise ValidationError("Gruppe nicht gefunden.", field="group_id", code="group_not_found")


# -- Inhalt einer Version -----------------------------------------------------------------

def _content(clean: dict) -> dict:
    """Vergleichbarer Inhalt einer Version (Name, Knetzeit, Hinweis, Schritte, Zeilen)."""
    return {
        "name": clean["name"],
        "knead_slow_min": clean["knead_slow_min"],
        "knead_fast_min": clean["knead_fast_min"],
        "note": clean["note"],
        "note_display": clean["note_display"],
        "steps": list(clean["steps"]),
        "items": [
            {"position": i["position"], "item_type": i["item_type"], "raw_material_id": i["raw_material_id"],
             "sub_recipe_id": i["sub_recipe_id"], "amount_g": i["amount_g"], "tolerance_unit": i["tolerance_unit"],
             "tolerance_value": i["tolerance_value"], "step_no": i["step_no"],
             "needs_review": 1 if i["needs_review"] else 0}
            for i in clean["items"]],
    }


def _stored_content(conn, version_id: int) -> dict:
    version = conn.execute("SELECT * FROM recipe_version WHERE id = ?", (version_id,)).fetchone()
    return {
        "name": version["name"],
        "knead_slow_min": version["knead_slow_min"],
        "knead_fast_min": version["knead_fast_min"],
        "note": version["note"],
        "note_display": version["note_display"],
        "steps": [s["name"] for s in _steps(conn, version_id)],
        "items": [
            {"position": r["position"], "item_type": r["item_type"], "raw_material_id": r["raw_material_id"],
             "sub_recipe_id": r["sub_recipe_id"], "amount_g": r["amount_g"], "tolerance_unit": r["tolerance_unit"],
             "tolerance_value": r["tolerance_value"], "step_no": r["step_no"], "needs_review": r["needs_review"]}
            for r in _current_rows(conn, version_id)],
    }


def _without_review(content: dict) -> dict:
    copy = dict(content)
    copy["items"] = [{k: v for k, v in item.items() if k != "needs_review"} for item in content["items"]]
    return copy


def _write_content(conn, version_id: int, content: dict) -> None:
    """Schreibt Schritte und Zeilen in eine (leere, nicht gewogene) Version."""
    for step_no, step_name in enumerate(content["steps"], start=1):
        conn.execute("INSERT INTO recipe_version_step (recipe_version_id, step_no, name) VALUES (?, ?, ?)",
                     (version_id, step_no, step_name))
    for item in content["items"]:
        conn.execute(
            "INSERT INTO recipe_item (recipe_version_id, position, item_type, raw_material_id, sub_recipe_id, "
            "amount_g, tolerance_unit, tolerance_value, step_no, needs_review) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (version_id, item["position"], item["item_type"], item["raw_material_id"], item["sub_recipe_id"],
             item["amount_g"], item["tolerance_unit"], item["tolerance_value"], item["step_no"],
             item["needs_review"]))


def _insert_version(conn, recipe_id: int, version_no: int, content: dict) -> int:
    version_id = conn.execute(
        "INSERT INTO recipe_version (recipe_id, version_no, name, knead_slow_min, knead_fast_min, note, note_display) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (recipe_id, version_no, content["name"], content["knead_slow_min"], content["knead_fast_min"],
         content["note"], content["note_display"])).lastrowid
    _write_content(conn, version_id, content)
    return version_id


def _overwrite_version(conn, version_id: int, content: dict) -> None:
    conn.execute("DELETE FROM recipe_item WHERE recipe_version_id = ?", (version_id,))
    conn.execute("DELETE FROM recipe_version_step WHERE recipe_version_id = ?", (version_id,))
    conn.execute(
        "UPDATE recipe_version SET name = ?, knead_slow_min = ?, knead_fast_min = ?, note = ?, note_display = ? "
        "WHERE id = ?",
        (content["name"], content["knead_slow_min"], content["knead_fast_min"], content["note"],
         content["note_display"], version_id))
    _write_content(conn, version_id, content)


# -- Anlegen und Speichern ------------------------------------------------------------------

def _prepare_number(conn, number: int | None, recipe_id: int | None = None) -> int:
    if number is None:
        return next_number(conn)
    row = conn.execute("SELECT id FROM recipe WHERE number = ?", (number,)).fetchone()
    if row is not None and row["id"] != recipe_id:
        raise ConflictError(f"Die Rezeptnummer {number} ist schon vergeben.", field="number", code="number_taken")
    return number


def create_in_tx(conn: sqlite3.Connection, data: dict, source: str = "admin",
                 clean: dict | None = None) -> int:
    """Legt ein Rezept mit Version 1 an, Status gesperrt (R05-7, K05-4). Liefert die ID."""
    clean = clean or validate_recipe(data)
    check_no_formula_start(clean["name"], field="name", label="Name")
    _check_step_names(clean, set())
    _check_group(conn, clean["group_id"])
    number = _prepare_number(conn, clean["number"])
    _check_name_free(conn, clean["name"])
    _check_references(conn, None, clean, [])
    for item in clean["items"]:
        item["needs_review"] = item["needs_review"] and source == "import"   # „*“ setzt nur der Import
    recipe_id = conn.execute("INSERT INTO recipe (number, group_id, locked, internal_note) VALUES (?, ?, 1, ?)",
                             (number, clean["group_id"], clean["internal_note"])).lastrowid
    _check_cycle(conn, recipe_id, clean["name"],
                 [i["sub_recipe_id"] for i in clean["items"] if i["sub_recipe_id"] is not None])
    content = _content(clean)
    version_id = _insert_version(conn, recipe_id, 1, content)
    conn.execute("UPDATE recipe SET current_version_id = ? WHERE id = ?", (version_id, recipe_id))
    _log(conn, "create", recipe_id, None,
         {"number": number, "group_id": clean["group_id"], "locked": 1, "internal_note": clean["internal_note"],
          "version_no": 1, **content}, source)
    return recipe_id


def create_recipe(conn: sqlite3.Connection, data: dict, source: str = "admin") -> dict:
    """Legt ein Rezept an (eigene Transaktion)."""
    validate_recipe(data)        # Eingabefehler vor dem Sperren der Datenbank melden
    try:
        with transaction(conn):
            recipe_id = create_in_tx(conn, data, source)
    except sqlite3.IntegrityError as exc:
        raise _integrity(exc) from exc
    return get_recipe(conn, recipe_id)


def _check_revision(row, revision) -> None:
    """Gleichzeitiges Bearbeiten an zwei Geräten (R05-17)."""
    if revision is None:
        raise ValidationError("Bearbeitungsstand (revision) fehlt.", field="revision", code="revision_missing")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision != row["revision"]:
        raise ConflictError("Rezept wurde inzwischen an einem anderen Gerät geändert – bitte neu laden.",
                            code="changed_elsewhere", revision=row["revision"])


def save_in_tx(conn: sqlite3.Connection, recipe_id: int, data: dict, *, revision, version_mode=None,
               source: str = "admin", keep_review: bool = False) -> dict:
    """Speichert Kopf, Schritte und Zeilen (R05-15 bis R05-17, K4, K05-5).

    ``keep_review``: Prüfmarkierungen „*“ so übernehmen, wie sie in ``data`` stehen (nur für
    Funktionen des Servers, z. B. Rohstoff austauschen C3-E9; die Seite kann „*“ nie setzen).

    Liefert ``{"result": "unchanged" | "overwritten" | "new_version", "message": …}``.
    """
    if version_mode is not None and version_mode not in VERSION_MODES:
        raise ValidationError("version_mode muss „new“ oder „overwrite“ sein.", field="version_mode")
    row = _fetch(conn, recipe_id)
    _check_revision(row, revision)
    if row["archived"]:
        raise ConflictError("Das Rezept ist archiviert. Bitte zuerst wiederherstellen.", code="archived")
    clean = validate_recipe(data)
    version_id = row["current_version_id"]
    current_items = _current_rows(conn, version_id)
    stored = _stored_content(conn, version_id)

    # Rezeptfelder (erzeugen nie eine Version)
    header_old, header_new = {}, {}
    if clean["number"] is not None and clean["number"] != row["number"]:
        if usage(conn, recipe_id)["used"]:
            raise ConflictError("Rezeptnummer ist bereits verwendet und kann nicht mehr geändert werden.",
                                field="number", code="number_locked")
        _prepare_number(conn, clean["number"], recipe_id)
        header_old["number"], header_new["number"] = row["number"], clean["number"]
    group_id = clean["group_id"] if "group_id" in data else row["group_id"]
    if group_id != row["group_id"]:
        _check_group(conn, group_id)
        header_old["group_id"], header_new["group_id"] = row["group_id"], group_id
    if "internal_note" in data and clean["internal_note"] != row["internal_note"]:
        header_old["internal_note"], header_new["internal_note"] = row["internal_note"], clean["internal_note"]

    # Inhalt der Version
    if clean["name"] != stored["name"]:
        check_no_formula_start(clean["name"], field="name", label="Name")
    _check_name_free(conn, clean["name"], exclude_id=recipe_id)
    _check_step_names(clean, set(stored["steps"]))
    if source != "import" and not keep_review:   # „*“ setzt nur der Server (Import, Austausch), die Seite nur bestätigen
        _apply_review_rule(clean["items"], current_items)
    _check_references(conn, recipe_id, clean, current_items)
    _check_cycle(conn, recipe_id, clean["name"],
                 [i["sub_recipe_id"] for i in clean["items"] if i["sub_recipe_id"] is not None])
    content = _content(clean)

    frozen = row["frozen_at"] is not None
    if content == stored:
        result, message = "unchanged", MSG_UNCHANGED
    elif frozen:
        result, message = "new_version", MSG_NEW_VERSION_FROZEN          # K4: gewogen → immer neu
    elif _without_review(content) == _without_review(stored):
        result, message = "overwritten", "Prüfmarkierung bestätigt."    # K05-5: nur „*“ bestätigt
    elif version_mode is None:
        raise ConflictError("Neue Version anlegen oder aktuelle Version überschreiben?",
                            code="version_choice_required")
    elif version_mode == "new":
        result, message = "new_version", MSG_NEW_VERSION
    else:
        result, message = "overwritten", MSG_OVERWRITTEN

    if header_new:
        sets = ", ".join(f"{k} = ?" for k in header_new)
        conn.execute(f"UPDATE recipe SET {sets} WHERE id = ?", (*header_new.values(), recipe_id))
        _log(conn, "update", recipe_id, header_old, header_new, source)
    if result == "new_version":
        version_no = conn.execute("SELECT MAX(version_no) + 1 FROM recipe_version WHERE recipe_id = ?",
                                  (recipe_id,)).fetchone()[0]
        new_id = _insert_version(conn, recipe_id, version_no, content)
        conn.execute("UPDATE recipe SET current_version_id = ? WHERE id = ?", (new_id, recipe_id))
        _log(conn, "new_version", recipe_id, {"version_no": row["version_no"]},
             {"version_no": version_no, **content}, source)
    elif result == "overwritten":
        _overwrite_version(conn, version_id, content)
        _log(conn, "update", recipe_id, {"version_no": row["version_no"], **stored},
             {"version_no": row["version_no"], **content}, source)
    if header_new or result != "unchanged":
        conn.execute("UPDATE recipe SET revision = revision + 1 WHERE id = ?", (recipe_id,))
    if result == "unchanged" and header_new:
        message = "Gespeichert."
    return {"result": result, "message": message}


def save_recipe(conn: sqlite3.Connection, recipe_id: int, data: dict, *, revision, version_mode=None,
                source: str = "admin") -> dict:
    """Speichert ein Rezept (eigene Transaktion). Antwort = Rezept mit ``save_result``."""
    if not isinstance(data, dict):
        raise ValidationError("Ungültige Eingabe.")
    validate_recipe(data)
    try:
        with transaction(conn):
            outcome = save_in_tx(conn, recipe_id, data, revision=revision, version_mode=version_mode,
                                 source=source)
    except sqlite3.IntegrityError as exc:
        raise _integrity(exc) from exc
    result = get_recipe(conn, recipe_id)
    result["save_result"] = outcome
    return result


# -- Stückgewichte und Chargengrößen (R05-20, ohne Version) ---------------------------------

def _check_revision_optional(row, revision) -> None:
    if revision is not None:
        _check_revision(row, revision)


def set_piece_weights(conn: sqlite3.Connection, recipe_id: int, data, *, revision=None,
                      confirm_delete_batch_sizes: bool = False, source: str = "admin") -> dict:
    """Ersetzt die Stückgewichte eines Rezepts (ganze Liste). Vorhandene behalten ihre ID.

    Wird ein Stückgewicht gelöscht, auf das Chargengrößen verweisen, werden diese mit gelöscht
    (Datenbank CASCADE) – vorher Rückfrage (409 ``confirmation_required``).
    """
    clean = validate_piece_weights(data)
    try:
        with transaction(conn):
            set_piece_weights_in_tx(conn, recipe_id, clean, revision=revision,
                                    confirm_delete_batch_sizes=confirm_delete_batch_sizes, source=source)
    except sqlite3.IntegrityError as exc:
        raise _integrity(exc) from exc
    return get_recipe(conn, recipe_id)


def set_piece_weights_in_tx(conn: sqlite3.Connection, recipe_id: int, clean: list[dict], *, revision=None,
                            confirm_delete_batch_sizes: bool = False, source: str = "admin") -> None:
    """Wie ``set_piece_weights``, in einer bereits offenen Transaktion (``clean`` aus ``validate_piece_weights``)."""
    row = _fetch(conn, recipe_id)
    _check_revision_optional(row, revision)
    existing = {r["id"]: r for r in conn.execute(
        "SELECT id, label, weight_g, sort_order FROM recipe_piece_weight WHERE recipe_id = ?", (recipe_id,))}
    keep_ids = {p["id"] for p in clean if p["id"] in existing}
    for p in clean:
        if p["id"] not in existing:
            p["id"] = None
    removed = [i for i in existing if i not in keep_ids]
    affected = [dict(r) for r in conn.execute(
        "SELECT b.id, b.label, p.label AS piece_label FROM recipe_batch_size b "
        "JOIN recipe_piece_weight p ON p.id = b.piece_weight_id "
        f"WHERE b.piece_weight_id IN ({','.join('?' * len(removed)) or 'NULL'}) ORDER BY b.sort_order",
        removed)]
    if affected and not confirm_delete_batch_sizes:
        labels = ", ".join(f"„{a['label']}“" for a in affected)
        raise ConflictError(
            f"Mit dem Stückgewicht werden auch diese Chargengrößen gelöscht: {labels}. Bitte bestätigen.",
            code="confirmation_required", batch_sizes=affected)
    old_labels = {r["label"] for r in existing.values()}
    for index, p in enumerate(clean, start=1):
        before = existing.get(p["id"])
        if (before is None and p["label"] not in old_labels) or (before is not None and before["label"] != p["label"]):
            check_no_formula_start(p["label"], field=f"piece_weights.{index}.label",
                                   label=f"Stückgewicht {index}: Bezeichnung")
    old_list = _piece_weights(conn, recipe_id)
    for pid in removed:
        conn.execute("DELETE FROM recipe_piece_weight WHERE id = ?", (pid,))
    # Zwischenbezeichnung, damit ein Tausch von Bezeichnungen nicht an UNIQUE scheitert
    for p in clean:
        if p["id"] is not None:
            conn.execute("UPDATE recipe_piece_weight SET label = ? WHERE id = ?", (f"\u0001{p['id']}", p["id"]))
    for order, p in enumerate(clean, start=1):
        if p["id"] is None:
            conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g, sort_order) "
                         "VALUES (?, ?, ?, ?)", (recipe_id, p["label"], p["weight_g"], order))
        else:
            conn.execute("UPDATE recipe_piece_weight SET label = ?, weight_g = ?, sort_order = ? WHERE id = ?",
                         (p["label"], p["weight_g"], order, p["id"]))
    new_list = _piece_weights(conn, recipe_id)
    if [(p["label"], p["weight_g"]) for p in old_list] != [(p["label"], p["weight_g"]) for p in new_list] \
            or removed:
        _log(conn, "update", recipe_id, {"piece_weights": old_list}, {"piece_weights": new_list}, source)
        conn.execute("UPDATE recipe SET revision = revision + 1 WHERE id = ?", (recipe_id,))


def set_batch_sizes(conn: sqlite3.Connection, recipe_id: int, data, *, revision=None,
                    source: str = "admin") -> dict:
    """Ersetzt die Chargengrößen eines Rezepts (ganze Liste). Vorhandene behalten ihre ID.

    „Stückzahl“ verweist auf ein Stückgewicht desselben Rezepts (ID oder Bezeichnung).
    """
    clean = validate_batch_sizes(data)
    try:
        with transaction(conn):
            set_batch_sizes_in_tx(conn, recipe_id, clean, revision=revision, source=source)
    except sqlite3.IntegrityError as exc:
        raise _integrity(exc) from exc
    return get_recipe(conn, recipe_id)


def set_batch_sizes_in_tx(conn: sqlite3.Connection, recipe_id: int, clean: list[dict], *, revision=None,
                          source: str = "admin") -> None:
    """Wie ``set_batch_sizes``, in einer bereits offenen Transaktion (``clean`` aus ``validate_batch_sizes``)."""
    row = _fetch(conn, recipe_id)
    _check_revision_optional(row, revision)
    pieces = {r["id"]: r for r in conn.execute(
        "SELECT id, label FROM recipe_piece_weight WHERE recipe_id = ?", (recipe_id,))}
    by_label = {r["label"].casefold(): r["id"] for r in pieces.values()}
    existing = {r["id"]: r for r in conn.execute(
        "SELECT id, label FROM recipe_batch_size WHERE recipe_id = ?", (recipe_id,))}
    old_labels = {r["label"] for r in existing.values()}
    for index, b in enumerate(clean, start=1):
        if b["kind"] == "pieces":
            pid = b["piece_weight_id"] if b["piece_weight_id"] in pieces else None
            if pid is None and b["piece_weight_label"]:
                pid = by_label.get(b["piece_weight_label"].casefold())
            if pid is None:
                raise ValidationError(f"Chargengröße {index}: Das Stückgewicht gibt es bei diesem Rezept nicht.",
                                      field=f"batch_sizes.{index}.piece_weight_id", code="piece_weight_missing")
            b["piece_weight_id"] = pid
        else:
            b["piece_weight_id"] = None
        if b["id"] not in existing:
            b["id"] = None
        before = existing.get(b["id"])
        if (before is None and b["label"] not in old_labels) or (before is not None and before["label"] != b["label"]):
            check_no_formula_start(b["label"], field=f"batch_sizes.{index}.label",
                                   label=f"Chargengröße {index}: Bezeichnung")
    old_list = _batch_sizes(conn, recipe_id)
    keep = {b["id"] for b in clean if b["id"] is not None}
    for bid in existing:
        if bid not in keep:
            conn.execute("DELETE FROM recipe_batch_size WHERE id = ?", (bid,))
    for order, b in enumerate(clean, start=1):
        if b["id"] is None:
            conn.execute("INSERT INTO recipe_batch_size (recipe_id, label, kind, value, piece_weight_id, sort_order) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (recipe_id, b["label"], b["kind"], b["value"], b["piece_weight_id"], order))
        else:
            conn.execute("UPDATE recipe_batch_size SET label = ?, kind = ?, value = ?, piece_weight_id = ?, "
                         "sort_order = ? WHERE id = ?",
                         (b["label"], b["kind"], b["value"], b["piece_weight_id"], order, b["id"]))
    new_list = _batch_sizes(conn, recipe_id)
    strip = lambda items: [(i["label"], i["kind"], i["value"], i["piece_weight_id"]) for i in items]  # noqa: E731
    if strip(old_list) != strip(new_list):
        _log(conn, "update", recipe_id, {"batch_sizes": old_list}, {"batch_sizes": new_list}, source)
        conn.execute("UPDATE recipe SET revision = revision + 1 WHERE id = ?", (recipe_id,))


# -- Status, Archiv, Kopie, Löschen ---------------------------------------------------------

def unlock_recipe(conn: sqlite3.Connection, recipe_id: int, confirm: bool = False, source: str = "admin") -> dict:
    """Freischalten (R05-21, K05-3): nur mit Zeilen; bei „*“ oder 0 % Warnung mit Bestätigung."""
    with transaction(conn):
        unlock_in_tx(conn, recipe_id, confirm=confirm, source=source)
    return get_recipe(conn, recipe_id)


def unlock_in_tx(conn: sqlite3.Connection, recipe_id: int, *, confirm: bool = False,
                 source: str = "admin") -> dict | None:
    """Wie ``unlock_recipe`` in einer offenen Transaktion. Gibt die Warnungen zurück (oder None)."""
    row = _fetch(conn, recipe_id)
    if not row["locked"]:
        return None
    items = _items(conn, row["current_version_id"])
    if not items:
        raise ConflictError("Ein Rezept ohne Zeilen kann nicht freigeschaltet werden.", code="empty_recipe")
    review = [{"position": i["position"], "name": _item_name(i)} for i in items if i["needs_review"]]
    zero = [{"position": i["position"], "name": _item_name(i)} for i in items
            if i["tolerance"] and i["tolerance"]["unit"] == "percent" and i["tolerance"]["value"] == 0]
    if (review or zero) and not confirm:
        parts = []
        if review:
            parts.append(f"{len(review)} Zeile{'n' if len(review) != 1 else ''} mit „*“ (noch nicht geprüft)")
        if zero:
            parts.append(f"{len(zero)} Zeile{'n' if len(zero) != 1 else ''} mit Toleranz 0 % "
                         "(wird auf ±1 g genau gewogen)")
        raise ConflictError("Trotzdem freischalten? " + "; ".join(parts) + ".",
                            code="confirmation_required", review_items=review, zero_percent_items=zero)
    conn.execute("UPDATE recipe SET locked = 0 WHERE id = ?", (recipe_id,))
    _log(conn, "update", recipe_id, {"locked": 1}, {"locked": 0}, source)
    return {"review_items": review, "zero_percent_items": zero} if (review or zero) else None


def _item_name(item: dict) -> str:
    if item["type"] == "raw_material":
        return item["raw_material"]["name"]
    return item["sub_recipe"]["name"]


def lock_recipe(conn: sqlite3.Connection, recipe_id: int, source: str = "admin") -> dict:
    """Sperren: blendet das Rezept in der Vorwahl aus (M05-5). Geht jederzeit."""
    with transaction(conn):
        lock_in_tx(conn, recipe_id, source=source)
    return get_recipe(conn, recipe_id)


def lock_in_tx(conn: sqlite3.Connection, recipe_id: int, *, source: str = "admin") -> bool:
    """Sperren in einer offenen Transaktion; True, wenn sich etwas geändert hat."""
    row = _fetch(conn, recipe_id)
    if row["locked"]:
        return False
    conn.execute("UPDATE recipe SET locked = 1 WHERE id = ?", (recipe_id,))
    _log(conn, "update", recipe_id, {"locked": 0}, {"locked": 1}, source)
    return True


def archive_recipe(conn: sqlite3.Connection, recipe_id: int, source: str = "admin") -> dict:
    """Archivieren (R05-22, M05-6): nicht, solange es als Unterrezept in einem aktiven Rezept steckt."""
    with transaction(conn):
        archive_in_tx(conn, recipe_id, source=source)
    return get_recipe(conn, recipe_id)


def archive_in_tx(conn: sqlite3.Connection, recipe_id: int, *, source: str = "admin") -> None:
    """Archivieren in einer offenen Transaktion (Regeln wie ``archive_recipe``)."""
    row = _fetch(conn, recipe_id)
    if row["archived"]:
        raise ConflictError("Das Rezept ist bereits archiviert.", code="already_archived")
    parents = usage(conn, recipe_id)["parents"]
    if parents:
        n = len(parents)
        names = ", ".join(f"„{p['name']}“ (Nr. {p['number']})" for p in parents)
        raise ConflictError(f"Das Rezept wird in {n} Rezept{'en' if n != 1 else ''} als Unterrezept verwendet "
                            f"und kann nicht archiviert werden: {names}.", code="in_use_as_sub_recipe",
                            parents=parents)
    conn.execute("UPDATE recipe SET archived = 1 WHERE id = ?", (recipe_id,))
    _log(conn, "archive", recipe_id, {"archived": 0}, {"archived": 1}, source)


def archived_sub_recipes(conn: sqlite3.Connection, recipe_id: int) -> list[dict]:
    """Archivierte Unterrezepte der **aktuellen** Version eines Rezepts (R05-23, Befund B1)."""
    return [
        {"id": r["id"], "number": r["number"], "name": r["name"]}
        for r in conn.execute(
            "SELECT DISTINCT s.id, s.number, sv.name FROM recipe r "
            "JOIN recipe_item i ON i.recipe_version_id = r.current_version_id "
            "JOIN recipe s ON s.id = i.sub_recipe_id "
            "JOIN recipe_version sv ON sv.id = s.current_version_id "
            "WHERE r.id = ? AND s.archived = 1 ORDER BY s.number", (recipe_id,))]


def _check_no_archived_sub_recipes(conn: sqlite3.Connection, recipe_id: int, what: str) -> None:
    """Meldung, wenn die aktuelle Version ein archiviertes Unterrezept enthält (R05-23)."""
    subs = archived_sub_recipes(conn, recipe_id)
    if not subs:
        return
    if len(subs) == 1:
        text = f"enthält das archivierte Unterrezept „{subs[0]['name']}“ (Nr. {subs[0]['number']})"
    else:
        text = "enthält die archivierten Unterrezepte " + ", ".join(
            f"„{s['name']}“ (Nr. {s['number']})" for s in subs)
    raise ConflictError(f"{what} nicht möglich: Das Rezept {text} – bitte zuerst wiederherstellen.",
                        code="archived_sub_recipe", sub_recipes=subs)


def restore_recipe(conn: sqlite3.Connection, recipe_id: int, source: str = "admin") -> dict:
    """Wiederherstellen (R05-23): nur ohne gleichnamiges aktives Rezept und ohne archiviertes
    Unterrezept in der aktuellen Version; Status bleibt."""
    with transaction(conn):
        restore_in_tx(conn, recipe_id, source=source)
    return get_recipe(conn, recipe_id)


def restore_in_tx(conn: sqlite3.Connection, recipe_id: int, *, source: str = "admin") -> None:
    """Wiederherstellen in einer offenen Transaktion (Regeln wie ``restore_recipe``, Sammelaktion C3-E8)."""
    row = _fetch(conn, recipe_id)
    if not row["archived"]:
        raise ConflictError("Das Rezept ist nicht archiviert.", code="not_archived")
    same = _find_active_with_name(conn, row["name"], exclude_id=recipe_id)
    if same is not None:
        raise ConflictError(
            f"Wiederherstellen nicht möglich: Das aktive Rezept „{same['name']}“ (Nummer {same['number']}) "
            "hat denselben Namen. Bitte zuerst einen der beiden umbenennen.", field="name", code="name_taken")
    _check_no_archived_sub_recipes(conn, recipe_id, "Wiederherstellen")
    conn.execute("UPDATE recipe SET archived = 0 WHERE id = ?", (recipe_id,))
    _log(conn, "restore", recipe_id, {"archived": 1}, {"archived": 0}, source)


def _copy_name(conn, name: str) -> str:
    """„Kopie von <Name>“, bei Namensgleichheit „Kopie 2 von …“ usw. (R05-24)."""
    n = 1
    while True:
        prefix = "Kopie von " if n == 1 else f"Kopie {n} von "
        candidate = prefix + name[: MAX_NAME - len(prefix)]
        if _find_active_with_name(conn, candidate) is None:
            return candidate
        n += 1


def copy_recipe(conn: sqlite3.Connection, recipe_id: int, source: str = "admin") -> dict:
    """Kopie der aktuellen Version mit Schritten, Zeilen (inkl. „*“), Stückgewichten und Chargengrößen.

    Nicht möglich, wenn die aktuelle Version ein archiviertes Unterrezept enthält (R05-23, 0.5.11)."""
    try:
        with transaction(conn):
            row = _fetch(conn, recipe_id)
            _check_no_archived_sub_recipes(conn, recipe_id, "Kopieren")
            content = _stored_content(conn, row["current_version_id"])
            content["name"] = _copy_name(conn, row["name"])
            number = next_number(conn)
            new_id = conn.execute("INSERT INTO recipe (number, group_id, locked, internal_note) VALUES (?, ?, 1, ?)",
                                  (number, row["group_id"], row["internal_note"])).lastrowid
            version_id = _insert_version(conn, new_id, 1, content)
            conn.execute("UPDATE recipe SET current_version_id = ? WHERE id = ?", (version_id, new_id))
            mapping = {}
            for p in conn.execute("SELECT id, label, weight_g, sort_order FROM recipe_piece_weight WHERE recipe_id = ?",
                                  (recipe_id,)).fetchall():
                mapping[p["id"]] = conn.execute(
                    "INSERT INTO recipe_piece_weight (recipe_id, label, weight_g, sort_order) VALUES (?, ?, ?, ?)",
                    (new_id, p["label"], p["weight_g"], p["sort_order"])).lastrowid
            for b in conn.execute("SELECT label, kind, value, piece_weight_id, sort_order FROM recipe_batch_size "
                                  "WHERE recipe_id = ?", (recipe_id,)).fetchall():
                conn.execute("INSERT INTO recipe_batch_size (recipe_id, label, kind, value, piece_weight_id, sort_order) "
                             "VALUES (?, ?, ?, ?, ?, ?)",
                             (new_id, b["label"], b["kind"], b["value"], mapping.get(b["piece_weight_id"]), b["sort_order"]))
            _log(conn, "create", new_id, None,
                 {"number": number, "group_id": row["group_id"], "locked": 1, "internal_note": row["internal_note"],
                  "version_no": 1, "copied_from": {"id": recipe_id, "number": row["number"], "version_no": row["version_no"]},
                  **content}, source)
    except sqlite3.IntegrityError as exc:
        raise _integrity(exc) from exc
    return get_recipe(conn, new_id)


def delete_recipe(conn: sqlite3.Connection, recipe_id: int, source: str = "admin") -> None:
    """Löscht ein nie verwendetes Rezept samt Versionen, Stückgewichten, Chargengrößen (R05-25)."""
    try:
        with transaction(conn):
            delete_in_tx(conn, recipe_id, source=source)
    except sqlite3.IntegrityError as exc:
        raise ConflictError("Das Rezept wird noch verwendet – bitte archivieren.", code="in_use") from exc


def delete_in_tx(conn: sqlite3.Connection, recipe_id: int, *, source: str = "admin") -> None:
    """Löschen in einer offenen Transaktion (Regeln wie ``delete_recipe``)."""
    row = _fetch(conn, recipe_id)
    use = usage(conn, recipe_id)
    if use["used"]:
        what = "in Aufträgen" if use["orders"] else "als Unterrezept"
        raise ConflictError(f"Das Rezept wird {what} verwendet – bitte archivieren.",
                            code="in_use", usage=use)
    snapshot = {"number": row["number"], "name": row["name"], "group_id": row["group_id"],
                "versions": conn.execute("SELECT count(*) FROM recipe_version WHERE recipe_id = ?",
                                         (recipe_id,)).fetchone()[0]}
    conn.execute("DELETE FROM recipe WHERE id = ?", (recipe_id,))
    _log(conn, "delete", recipe_id, snapshot, None, source)
