"""Rezeptgruppen (Modul 05, M05-9, Regel R05-26).

Anlegen, umbenennen, Reihenfolge, löschen nur wenn leer (auch archivierte Rezepte
zählen). Name eindeutig ohne Rücksicht auf Groß-/Kleinschreibung, Sperre B2.
"""

from __future__ import annotations

import json
import sqlite3

from ..db import transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from ..text_rules import check_no_formula_start
from .models import validate_group_name


def _key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _log(conn, action: str, group_id: int, old, new, source: str) -> None:
    conn.execute(
        "INSERT INTO change_log (source, entity, entity_id, action, old_values, new_values) "
        "VALUES (?, 'recipe_group', ?, ?, ?, ?)",
        (source, group_id, action,
         json.dumps(old, ensure_ascii=False) if old is not None else None,
         json.dumps(new, ensure_ascii=False) if new is not None else None))


def _fetch(conn: sqlite3.Connection, group_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT id, name, sort_order FROM recipe_group WHERE id = ?", (group_id,)).fetchone()
    if row is None:
        raise NotFoundError("Rezeptgruppe nicht gefunden.", code="not_found")
    return row


def _check_name_free(conn, name: str, exclude_id: int | None = None) -> None:
    key = _key(name)
    for row in conn.execute("SELECT id, name FROM recipe_group"):
        if row["id"] != exclude_id and _key(row["name"]) == key:
            raise ConflictError(f"Eine Gruppe „{row['name']}“ gibt es schon.", field="name", code="name_taken")


def list_groups(conn: sqlite3.Connection) -> list[dict]:
    """Gruppen in Reihenfolge, mit Anzahl der Rezepte (aktiv und archiviert)."""
    rows = conn.execute(
        "SELECT g.id, g.name, g.sort_order, "
        "       (SELECT count(*) FROM recipe r WHERE r.group_id = g.id AND r.archived = 0) AS active, "
        "       (SELECT count(*) FROM recipe r WHERE r.group_id = g.id) AS total "
        "FROM recipe_group g ORDER BY g.sort_order, g.name COLLATE NOCASE")
    return [{"id": r["id"], "name": r["name"], "sort_order": r["sort_order"],
             "recipe_count": r["active"], "recipe_count_all": r["total"]} for r in rows]


def create_in_tx(conn: sqlite3.Connection, name, source: str = "admin") -> int:
    clean = validate_group_name(name)
    check_no_formula_start(clean, field="name", label="Name der Gruppe")
    _check_name_free(conn, clean)
    order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM recipe_group").fetchone()[0]
    group_id = conn.execute("INSERT INTO recipe_group (name, sort_order) VALUES (?, ?)",
                            (clean, order)).lastrowid
    _log(conn, "create", group_id, None, {"name": clean, "sort_order": order}, source)
    return group_id


def create_group(conn: sqlite3.Connection, name, source: str = "admin") -> dict:
    validate_group_name(name)
    with transaction(conn):
        group_id = create_in_tx(conn, name, source)
    return get_group(conn, group_id)


def get_group(conn: sqlite3.Connection, group_id: int) -> dict:
    for group in list_groups(conn):
        if group["id"] == group_id:
            return group
    raise NotFoundError("Rezeptgruppe nicht gefunden.", code="not_found")


def rename_group(conn: sqlite3.Connection, group_id: int, name, source: str = "admin") -> dict:
    clean = validate_group_name(name)
    with transaction(conn):
        row = _fetch(conn, group_id)
        if clean != row["name"]:
            check_no_formula_start(clean, field="name", label="Name der Gruppe")
            _check_name_free(conn, clean, exclude_id=group_id)
            conn.execute("UPDATE recipe_group SET name = ? WHERE id = ?", (clean, group_id))
            _log(conn, "update", group_id, {"name": row["name"]}, {"name": clean}, source)
    return get_group(conn, group_id)


def reorder_groups(conn: sqlite3.Connection, group_ids, source: str = "admin") -> list[dict]:
    """Neue Reihenfolge: Liste aller Gruppen-IDs in der gewünschten Folge."""
    if not isinstance(group_ids, list) or not all(isinstance(g, int) and not isinstance(g, bool)
                                                  for g in group_ids):
        raise ValidationError("Reihenfolge muss eine Liste von Gruppen-IDs sein.", field="group_ids")
    with transaction(conn):
        existing = {r["id"]: r["sort_order"] for r in conn.execute("SELECT id, sort_order FROM recipe_group")}
        if sorted(group_ids) != sorted(existing):
            raise ValidationError("Die Reihenfolge muss jede Gruppe genau einmal enthalten.",
                                  field="group_ids", code="incomplete_order")
        for order, group_id in enumerate(group_ids, start=1):
            if existing[group_id] != order:
                conn.execute("UPDATE recipe_group SET sort_order = ? WHERE id = ?", (order, group_id))
                _log(conn, "update", group_id, {"sort_order": existing[group_id]}, {"sort_order": order}, source)
    return list_groups(conn)


def delete_group(conn: sqlite3.Connection, group_id: int, source: str = "admin") -> None:
    """Löscht eine Gruppe, die kein Rezept (auch kein archiviertes) nutzt (R05-26)."""
    with transaction(conn):
        row = _fetch(conn, group_id)
        used = conn.execute("SELECT count(*) FROM recipe WHERE group_id = ?", (group_id,)).fetchone()[0]
        if used:
            raise ConflictError(
                f"Die Gruppe enthält noch {used} Rezept{'e' if used != 1 else ''} (auch archivierte zählen) "
                "und kann nicht gelöscht werden.", code="in_use", recipe_count=used)
        conn.execute("DELETE FROM recipe_group WHERE id = ?", (group_id,))
        _log(conn, "delete", group_id, {"name": row["name"], "sort_order": row["sort_order"]}, None, source)
