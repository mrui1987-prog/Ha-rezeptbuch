"""Händlerliste (Modul 04, M04-5, R04-10, R04-11).

Jeder Händler steht einmal in der Liste (Name eindeutig ohne Groß-/Kleinschreibung, auch Ä/Ö/Ü),
damit z. B. „BÄKO“ nicht verschieden geschrieben wird. Verwendete Händler werden archiviert statt
gelöscht; Umbenennen wirkt bei allen Rohstoffen.
"""

from __future__ import annotations

import json
import sqlite3

from ..db import transaction
from ..errors import ConflictError, NotFoundError, ValidationError
from ..raw_materials.models import normalize_text
from ..text_rules import check_no_formula_start

MAX_NAME = 60
_NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"


def _log(conn, action: str, entity_id: int, old, new, source: str) -> None:
    conn.execute(
        "INSERT INTO change_log (source, entity, entity_id, action, old_values, new_values) "
        "VALUES (?, 'dealer', ?, ?, ?, ?)",
        (source, entity_id, action,
         json.dumps(old, ensure_ascii=False) if old is not None else None,
         json.dumps(new, ensure_ascii=False) if new is not None else None))


def _clean_name(value) -> str:
    if not isinstance(value, str) or not normalize_text(value):
        raise ValidationError("Name des Händlers ist ein Pflichtfeld.", field="name")
    name = normalize_text(value)
    if len(name) > MAX_NAME:
        raise ValidationError(f"Name des Händlers darf höchstens {MAX_NAME} Zeichen lang sein.", field="name")
    check_no_formula_start(name, field="name", label="Name des Händlers")
    return name


def _usage(conn, dealer_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM raw_material_source WHERE dealer_id = ?", (dealer_id,)).fetchone()[0]


def _to_dict(conn, row) -> dict:
    return {"id": row["id"], "name": row["name"], "archived": bool(row["archived"]),
            "sources": _usage(conn, row["id"]), "created_at": row["created_at"], "updated_at": row["updated_at"]}


def _fetch(conn, dealer_id: int):
    row = conn.execute("SELECT * FROM dealer WHERE id = ?", (dealer_id,)).fetchone()
    if row is None:
        raise NotFoundError("Händler nicht gefunden.", code="not_found")
    return row


def _same_name(conn, name: str, exclude_id: int | None = None):
    key = name.casefold()
    for row in conn.execute("SELECT id, name FROM dealer"):
        if row["id"] != exclude_id and normalize_text(row["name"]).casefold() == key:
            return row
    return None


def list_dealers(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    sql = "SELECT * FROM dealer" + ("" if include_archived else " WHERE archived = 0") + " ORDER BY name COLLATE NOCASE"
    return [_to_dict(conn, r) for r in conn.execute(sql)]


def get_dealer(conn: sqlite3.Connection, dealer_id: int) -> dict:
    return _to_dict(conn, _fetch(conn, dealer_id))


def find_or_fail_active(conn: sqlite3.Connection, dealer_id) -> sqlite3.Row:
    """Händler für eine neue Bezugsquelle: muss existieren und darf nicht archiviert sein (R04-10)."""
    if isinstance(dealer_id, bool) or not isinstance(dealer_id, int):
        raise ValidationError("Bitte einen Händler wählen.", field="dealer_id")
    row = conn.execute("SELECT * FROM dealer WHERE id = ?", (dealer_id,)).fetchone()
    if row is None:
        raise ValidationError("Händler nicht gefunden.", field="dealer_id", code="not_found")
    if row["archived"]:
        raise ConflictError(f"Der Händler „{row['name']}“ ist archiviert.", field="dealer_id",
                            code="dealer_archived")
    return row


def create_in_tx(conn, data: dict, source: str = "admin") -> int:
    name = _clean_name(data.get("name"))
    same = _same_name(conn, name)
    if same is not None:
        raise ConflictError(f"Den Händler „{same['name']}“ gibt es schon.", field="name", code="name_taken")
    new_id = conn.execute("INSERT INTO dealer (name) VALUES (?)", (name,)).lastrowid
    _log(conn, "create", new_id, None, {"name": name}, source)
    return new_id


def create_dealer(conn: sqlite3.Connection, data: dict, source: str = "admin") -> dict:
    _clean_name(data.get("name"))
    with transaction(conn):
        new_id = create_in_tx(conn, data, source)
    return get_dealer(conn, new_id)


def rename_dealer(conn: sqlite3.Connection, dealer_id: int, data: dict, source: str = "admin") -> dict:
    name = _clean_name(data.get("name"))
    with transaction(conn):
        row = _fetch(conn, dealer_id)
        if name != row["name"]:
            same = _same_name(conn, name, exclude_id=dealer_id)
            if same is not None:
                raise ConflictError(f"Den Händler „{same['name']}“ gibt es schon.", field="name",
                                    code="name_taken")
            conn.execute(f"UPDATE dealer SET name = ?, updated_at = {_NOW} WHERE id = ?", (name, dealer_id))
            _log(conn, "update", dealer_id, {"name": row["name"]}, {"name": name}, source)
    return get_dealer(conn, dealer_id)


def set_archived(conn: sqlite3.Connection, dealer_id: int, archived: bool, source: str = "admin") -> dict:
    with transaction(conn):
        row = _fetch(conn, dealer_id)
        if bool(row["archived"]) == archived:
            raise ConflictError("Der Händler ist bereits archiviert." if archived
                                else "Der Händler ist nicht archiviert.",
                                code="already_archived" if archived else "not_archived")
        # Namen sind über alle Händler eindeutig, Wiederherstellen kann also keinen Doppelten erzeugen
        conn.execute(f"UPDATE dealer SET archived = ?, updated_at = {_NOW} WHERE id = ?",
                     (1 if archived else 0, dealer_id))
        _log(conn, "archive" if archived else "restore", dealer_id,
             {"archived": int(not archived)}, {"archived": int(archived)}, source)
    return get_dealer(conn, dealer_id)


def delete_dealer(conn: sqlite3.Connection, dealer_id: int, source: str = "admin") -> None:
    """Löschen nur, wenn nie verwendet (R04-11), sonst archivieren."""
    with transaction(conn):
        row = _fetch(conn, dealer_id)
        used = _usage(conn, dealer_id)
        if used:
            raise ConflictError(f"Der Händler ist bei {used} Rohstoff{'en' if used != 1 else ''} hinterlegt – "
                                "bitte archivieren.", code="in_use")
        conn.execute("DELETE FROM dealer WHERE id = ?", (dealer_id,))
        _log(conn, "delete", dealer_id, {"name": row["name"]}, None, source)
