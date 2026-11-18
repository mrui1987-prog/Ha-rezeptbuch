"""Rohstoffverwaltung: Regeln, Transaktionen und Änderungsprotokoll (Modul 03).

Die Regeln R03-1 bis R03-12 stehen in docs/rohstoffe.md, Abschnitt 4. Alle
Funktionen arbeiten auf einer übergebenen Datenbankverbindung (eine eigene je
Anfrage, K03-1). Schreibvorgänge laufen in einer Transaktion mit ``BEGIN IMMEDIATE``;
dadurch sind Prüfungen wie „Name eindeutig“ auch bei gleichzeitigen Anfragen
verlässlich. Router und Seiten enthalten keine Fachlogik.
"""

from __future__ import annotations

import difflib
import json
import sqlite3

from ..db import transaction
from ..errors import ConflictError, NotFoundError
from .models import normalize_text, parse_price, tolerance_display, validate

# Ähnlichkeit ab der ein Name als „ähnlich“ gemeldet wird (R03-3)
SIMILARITY_THRESHOLD = 0.8

_COLUMNS = ("number", "name", "display_name", "type", "tolerance_unit", "tolerance_value",
            "unit_size_g", "unit_label")
_SELECT = ("SELECT id, number, name, display_name, type, tolerance_unit, tolerance_value, "
           "unit_size_g, unit_label, source, archived, created_at, updated_at, price_cents_per_kg, price_changed_at "
           "FROM raw_material")

_NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"


# -- Hilfen --------------------------------------------------------------------

def _to_dict(row: sqlite3.Row) -> dict:
    """Zeile → Antwortobjekt. ``station_name`` ist der Kurzname, sonst der Name (K03-4)."""
    return {
        "id": row["id"],
        "number": row["number"],
        "name": row["name"],
        "display_name": row["display_name"],
        "station_name": row["display_name"] or row["name"],
        "type": row["type"],
        "tolerance_unit": row["tolerance_unit"],
        "tolerance": tolerance_display(row["tolerance_unit"], row["tolerance_value"]),
        "unit_size_g": row["unit_size_g"],
        "unit_label": row["unit_label"],
        "source": row["source"],
        "archived": bool(row["archived"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        # Preis je kg in Cent (VC03-a, R03-16: auch ohne PIN lesbar)
        "price_cents_per_kg": row["price_cents_per_kg"],
        "price_changed_at": row["price_changed_at"],
    }


def _fetch(conn: sqlite3.Connection, raw_material_id: int) -> sqlite3.Row:
    row = conn.execute(_SELECT + " WHERE id = ?", (raw_material_id,)).fetchone()
    if row is None:
        raise NotFoundError("Rohstoff nicht gefunden.", code="not_found")
    return row


def _log(conn: sqlite3.Connection, action: str, entity_id: int, old: dict | None, new: dict | None,
         source: str) -> None:
    conn.execute(
        "INSERT INTO change_log (source, entity, entity_id, action, old_values, new_values) "
        "VALUES (?, 'raw_material', ?, ?, ?, ?)",
        (source, entity_id, action,
         json.dumps(old, ensure_ascii=False) if old is not None else None,
         json.dumps(new, ensure_ascii=False) if new is not None else None),
    )


def _snapshot(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in (*_COLUMNS, "price_cents_per_kg", "source", "archived")}


def _display_values(row: sqlite3.Row) -> dict:
    """Bisherige Anzeigewerte als Grundlage für das Bearbeiten."""
    return {
        "number": row["number"],
        "name": row["name"],
        "display_name": row["display_name"],
        "type": row["type"],
        "tolerance_unit": row["tolerance_unit"],
        "tolerance": tolerance_display(row["tolerance_unit"], row["tolerance_value"]),
        "unit_size_g": row["unit_size_g"],
        "unit_label": row["unit_label"],
    }


def _name_key(name: str) -> str:
    """Vergleichsschlüssel für Namen: ohne Randleerzeichen, ohne Groß-/Kleinschreibung (auch Ä/Ö/Ü)."""
    return normalize_text(name).casefold()


# öffentlich für den Import (Modul 05): derselbe Namensvergleich wie bei R03-2
name_key = _name_key


def _find_active_with_name(conn: sqlite3.Connection, name: str, exclude_id: int | None = None):
    key = _name_key(name)
    for row in conn.execute("SELECT id, number, name FROM raw_material WHERE archived = 0"):
        if row["id"] != exclude_id and _name_key(row["name"]) == key:
            return row
    return None


# -- Lesen ----------------------------------------------------------------------

def next_number(conn: sqlite3.Connection) -> int:
    """Nummernvorschlag: höchste vorhandene Nummer + 1 (archivierte zählen mit, R03-1)."""
    return conn.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM raw_material").fetchone()[0]


def usage(conn: sqlite3.Connection, raw_material_id: int) -> dict:
    """Wo der Rohstoff verwendet wird: Rezepte, Aufträge (als Leitrohstoff), Chargenzeilen."""
    recipes = conn.execute(
        "SELECT count(DISTINCT v.recipe_id) FROM recipe_item i "
        "JOIN recipe_version v ON v.id = i.recipe_version_id WHERE i.raw_material_id = ?",
        (raw_material_id,)).fetchone()[0]
    orders = conn.execute(
        "SELECT count(*) FROM production_order WHERE basis_raw_material_id = ?",
        (raw_material_id,)).fetchone()[0]
    batch_items = conn.execute(
        "SELECT count(*) FROM batch_item WHERE raw_material_id = ?", (raw_material_id,)).fetchone()[0]
    return {"recipes": recipes, "orders": orders, "batch_items": batch_items,
            "used": bool(recipes or orders or batch_items)}


def _used_message(raw_material_id: int, use: dict) -> str:
    if use["recipes"]:
        n = use["recipes"]
        return f"wird in {n} Rezept{'en' if n != 1 else ''} verwendet"
    return "wird in Aufträgen oder Chargen verwendet"


def get_raw_material(conn: sqlite3.Connection, raw_material_id: int) -> dict:
    result = _to_dict(_fetch(conn, raw_material_id))
    result["usage"] = usage(conn, raw_material_id)
    return result


def list_raw_materials(conn: sqlite3.Connection, search: str | None = None,
                       include_archived: bool = False, zero_percent: bool = False) -> list[dict]:
    """Liste nach Nummer sortiert. Die Suche findet Teile von Nummer, Name und Kurzname
    ohne Rücksicht auf Groß-/Kleinschreibung.

    ``zero_percent``: nur Rohstoffe mit Toleranz 0 % (Filter aus M05-13b; diese werden
    bei der Verwiegung auf ±1 g genau gewogen und sollten geprüft werden).
    """
    where = []
    if not include_archived:
        where.append("archived = 0")
    if zero_percent:
        where.append("tolerance_unit = 'percent' AND tolerance_value = 0")
    sql = _SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY number"
    rows = [_to_dict(r) for r in conn.execute(sql)]
    if search and search.strip():
        needle = normalize_text(search).casefold()
        rows = [
            r for r in rows
            if needle in str(r["number"])
            or needle in r["name"].casefold()
            or (r["display_name"] and needle in r["display_name"].casefold())
        ]
    return rows


def similar_names(conn: sqlite3.Connection, name: str, exclude_id: int | None = None,
                  limit: int = 5) -> list[dict]:
    """Hinweise auf ähnliche Namen unter den aktiven Rohstoffen (R03-3). Sperrt nichts."""
    key = _name_key(name or "")
    if not key:
        return []
    found = []
    for row in conn.execute("SELECT id, number, name, display_name FROM raw_material WHERE archived = 0"):
        if row["id"] == exclude_id:
            continue
        ratio = difflib.SequenceMatcher(None, key, _name_key(row["name"])).ratio()
        if ratio >= SIMILARITY_THRESHOLD:
            found.append((ratio, {"id": row["id"], "number": row["number"], "name": row["name"],
                                  "display_name": row["display_name"]}))
    found.sort(key=lambda item: -item[0])
    return [item for _, item in found[:limit]]


# -- Ändern ---------------------------------------------------------------------

def _integrity(exc: sqlite3.IntegrityError, what: str = "Der Rohstoff konnte nicht gespeichert werden") -> ConflictError:
    return ConflictError(f"{what}: {exc}", code="integrity")


# Die Funktionen mit ``_in_tx`` erwarten eine bereits offene Transaktion. Sie enthalten
# die Regeln und werden von den öffentlichen Funktionen unten sowie vom Import
# (Modul 05, alles in einer Transaktion) benutzt. So gibt es die Regeln nur einmal.

def _price(data: dict, warnings: list | None) -> tuple[bool, int | None]:
    """Preis aus der Eingabe (``price_per_kg``, R03-13): (angegeben?, Cent). Rundungshinweis → ``warnings``."""
    if "price_per_kg" not in data:
        return False, None
    cents, hint = parse_price(data["price_per_kg"])
    if hint and warnings is not None:
        warnings.append({"field": "price_per_kg", "code": "price_rounded", "detail": hint})
    return True, cents


def create_in_tx(conn: sqlite3.Connection, data: dict, source: str = "admin",
                 warnings: list | None = None) -> int:
    """Legt einen eigenen Rohstoff an (R03-1, R03-2, R03-5, R03-6, R03-8, R03-12, R03-13) und liefert die ID.

    Ein Rundungshinweis zum Preis (K03-8) kommt in ``warnings``.
    """
    clean = validate(data)
    _, price = _price(data, warnings)
    if clean["number"] is None:
        clean["number"] = next_number(conn)
    elif conn.execute("SELECT 1 FROM raw_material WHERE number = ?", (clean["number"],)).fetchone():
        raise ConflictError(f"Die Nummer {clean['number']} ist schon vergeben.",
                            field="number", code="number_taken")
    same = _find_active_with_name(conn, clean["name"])
    if same is not None:
        raise ConflictError(
            f"Einen Rohstoff „{same['name']}“ gibt es schon (Nummer {same['number']}).",
            field="name", code="name_taken")
    cur = conn.execute(
        "INSERT INTO raw_material (number, name, display_name, type, tolerance_unit, tolerance_value, "
        "unit_size_g, unit_label, source, price_cents_per_kg, price_changed_at) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'own', ?, CASE WHEN ? IS NULL THEN NULL ELSE {_NOW} END)",
        (*(clean[c] for c in _COLUMNS), price, price))
    new_id = cur.lastrowid
    _log(conn, "create", new_id, None, _snapshot(_fetch(conn, new_id)), source)
    return new_id


def update_in_tx(conn: sqlite3.Connection, raw_material_id: int, data: dict,
                 confirm_type_change: bool = False, source: str = "admin",
                 warnings: list | None = None) -> dict:
    """Ändert einen Rohstoff; nur die mitgeschickten Felder ändern sich.

    Liefert die geänderten Spalten mit ``{"spalte": (alt, neu)}`` (leer = nichts geändert).
    Preis (``price_per_kg``): fehlt = unverändert, ``None``/leer = löschen; „Preis geändert am“
    wird nur gesetzt, wenn sich der gespeicherte Preis ändert (R03-14).
    """
    row = _fetch(conn, raw_material_id)
    clean = validate(data, base=_display_values(row))
    changes = {c: clean[c] for c in _COLUMNS if clean[c] != row[c]}
    given, price = _price(data, warnings)
    price_changed = given and price != row["price_cents_per_kg"]
    if price_changed:
        changes["price_cents_per_kg"] = price
    if not changes:
        return {}

    use = usage(conn, raw_material_id)
    if "number" in changes:
        if use["used"]:
            raise ConflictError(
                "Die Nummer ist in Rezepten verwendet und kann nicht mehr geändert werden.",
                field="number", code="number_locked")
        if conn.execute("SELECT 1 FROM raw_material WHERE number = ?", (changes["number"],)).fetchone():
            raise ConflictError(f"Die Nummer {changes['number']} ist schon vergeben.",
                                field="number", code="number_taken")
    if "name" in changes and not row["archived"]:
        same = _find_active_with_name(conn, changes["name"], exclude_id=raw_material_id)
        if same is not None:
            raise ConflictError(
                f"Einen Rohstoff „{same['name']}“ gibt es schon (Nummer {same['number']}).",
                field="name", code="name_taken")
    if "type" in changes and use["recipes"] and not confirm_type_change:
        n = use["recipes"]
        raise ConflictError(
            f"Der Typwechsel betrifft {n} Rezept{'e' if n != 1 else ''}: "
            "„Mehl gesamt“ ändert sich dort. Bitte bestätigen.",
            field="type", code="type_change_confirmation_required", affected_recipes=n)

    assignments = ", ".join(f"{c} = ?" for c in changes)
    if price_changed:
        assignments += f", price_changed_at = {_NOW}"
    conn.execute(
        f"UPDATE raw_material SET {assignments}, updated_at = {_NOW} "
        "WHERE id = ?", (*changes.values(), raw_material_id))
    _log(conn, "update", raw_material_id, {c: row[c] for c in changes}, changes, source)
    return {c: (row[c], changes[c]) for c in changes}


def archive_in_tx(conn: sqlite3.Connection, raw_material_id: int, source: str = "admin") -> None:
    """Archiviert einen Rohstoff (R03-9). Rezepte, die ihn nutzen, bleiben unverändert."""
    row = _fetch(conn, raw_material_id)
    if row["archived"]:
        raise ConflictError("Der Rohstoff ist bereits archiviert.", code="already_archived")
    conn.execute("UPDATE raw_material SET archived = 1, "
                 "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?", (raw_material_id,))
    _log(conn, "archive", raw_material_id, {"archived": 0}, {"archived": 1}, source)


def restore_in_tx(conn: sqlite3.Connection, raw_material_id: int, source: str = "admin") -> None:
    """Holt einen archivierten Rohstoff zurück, sofern kein aktiver Rohstoff denselben Namen hat (R03-10)."""
    row = _fetch(conn, raw_material_id)
    if not row["archived"]:
        raise ConflictError("Der Rohstoff ist nicht archiviert.", code="not_archived")
    same = _find_active_with_name(conn, row["name"], exclude_id=raw_material_id)
    if same is not None:
        raise ConflictError(
            f"Wiederherstellen nicht möglich: Der aktive Rohstoff „{same['name']}“ "
            f"(Nummer {same['number']}) hat denselben Namen. Bitte zuerst einen der beiden umbenennen.",
            field="name", code="name_taken")
    conn.execute("UPDATE raw_material SET archived = 0, "
                 "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?", (raw_material_id,))
    _log(conn, "restore", raw_material_id, {"archived": 1}, {"archived": 0}, source)


def _with_warnings(result: dict, warnings: list) -> dict:
    if warnings:
        result["warnings"] = warnings
    return result


def create_raw_material(conn: sqlite3.Connection, data: dict, source: str = "admin") -> dict:
    """Legt einen eigenen Rohstoff an (eigene Transaktion)."""
    validate(data)          # Eingabefehler vor dem Sperren der Datenbank melden
    _price(data, None)
    warnings: list = []
    try:
        with transaction(conn):
            new_id = create_in_tx(conn, data, source, warnings)
    except sqlite3.IntegrityError as exc:
        raise _integrity(exc) from exc
    return _with_warnings(get_raw_material(conn, new_id), warnings)


def update_raw_material(conn: sqlite3.Connection, raw_material_id: int, data: dict,
                        confirm_type_change: bool = False, source: str = "admin") -> dict:
    """Ändert einen Rohstoff (eigene Transaktion); nur die mitgeschickten Felder ändern sich.

    Wurde der Preis gerundet (K03-8), enthält die Antwort ``warnings``.
    """
    warnings: list = []
    try:
        with transaction(conn):
            update_in_tx(conn, raw_material_id, data, confirm_type_change, source, warnings)
    except sqlite3.IntegrityError as exc:
        # Auch die Schutz-Trigger der Datenbank (z. B. Nummer gesperrt) landen hier
        raise _integrity(exc) from exc
    return _with_warnings(get_raw_material(conn, raw_material_id), warnings)


def archive_raw_material(conn: sqlite3.Connection, raw_material_id: int, source: str = "admin") -> dict:
    """Archiviert einen Rohstoff (eigene Transaktion)."""
    with transaction(conn):
        archive_in_tx(conn, raw_material_id, source)
    return get_raw_material(conn, raw_material_id)


def restore_raw_material(conn: sqlite3.Connection, raw_material_id: int, source: str = "admin") -> dict:
    """Holt einen archivierten Rohstoff zurück (eigene Transaktion)."""
    with transaction(conn):
        restore_in_tx(conn, raw_material_id, source)
    return get_raw_material(conn, raw_material_id)


def delete_raw_material(conn: sqlite3.Connection, raw_material_id: int, source: str = "admin") -> None:
    """Löscht einen nie verwendeten Rohstoff endgültig (R03-11), sonst bitte archivieren."""
    try:
        with transaction(conn):
            row = _fetch(conn, raw_material_id)
            use = usage(conn, raw_material_id)
            if use["used"]:
                raise ConflictError(f"Der Rohstoff {_used_message(raw_material_id, use)} – bitte archivieren.",
                                    code="in_use", usage=use)
            snapshot = _snapshot(row)
            conn.execute("DELETE FROM raw_material WHERE id = ?", (raw_material_id,))
            _log(conn, "delete", raw_material_id, snapshot, None, source)
    except sqlite3.IntegrityError as exc:
        # Fremdschlüssel als zweite Sperre (z. B. Verwendung, die oben nicht gezählt wurde)
        raise ConflictError("Der Rohstoff wird noch verwendet – bitte archivieren.", code="in_use") from exc
