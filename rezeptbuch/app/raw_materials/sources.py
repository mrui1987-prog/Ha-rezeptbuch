"""Bezugsquellen und Preis je Bezugsquelle (Modul 04 Teil C1, docs/kennzeichnungspass-import.md 3.2, 4, 5).

Regeln:

* Ein Händler einmal je Rohstoff (K04-11), genau eine Bezugsquelle aktiv, solange es welche gibt
  (R04-10); die erste wird automatisch aktiv. Die Datenbank sichert „höchstens eine aktiv“.
* **Gültiger Preis** des Rohstoffs = Preis der aktiven Bezugsquelle (M04-14). Er wird in
  ``raw_material.price_cents_per_kg`` gespiegelt, damit Lese-API, CSV und Berechnungen weiter ein
  Feld lesen (K04-4). „Preis geändert am“ am Rohstoff ändert sich nur, wenn sich der gültige Preis
  ändert (K04-2); jede Bezugsquelle hat ihr eigenes Datum.
* Bekommt ein Rohstoff seine **erste** Bezugsquelle, geht sein bisheriger Preis samt Datum an sie (K04-1).
* Wird die letzte Bezugsquelle entfernt, bleibt der zuletzt gültige Preis am Rohstoff stehen.
* „g je Mengeneinheit“, Einheit und Warengruppe sind für den Beleg-Import (K03-19, K03-24, M04-24)
  und werden hier nur gepflegt.
"""

from __future__ import annotations

import json
import sqlite3

from ..db import transaction
from ..dealers import service as dealers
from ..errors import ConflictError, NotFoundError, ValidationError
from ..text_rules import check_no_formula_start
from .models import _whole_number, euro_text, normalize_text, parse_price

_NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"

MAX_ARTICLE_NO = 40
MAX_NOTE = 200
MAX_UNIT_CODE = 10
MAX_COMMODITY_GROUP = 20
MAX_GRAMS_PER_UNIT = 1_000_000

_SELECT = ("SELECT s.*, d.name AS dealer_name, d.archived AS dealer_archived "
           "FROM raw_material_source s JOIN dealer d ON d.id = s.dealer_id")


# -- Hilfen --------------------------------------------------------------------

def _log(conn, action: str, entity_id: int, old, new, source: str) -> None:
    conn.execute(
        "INSERT INTO change_log (source, entity, entity_id, action, old_values, new_values) "
        "VALUES (?, 'raw_material_source', ?, ?, ?, ?)",
        (source, entity_id, action,
         json.dumps(old, ensure_ascii=False) if old is not None else None,
         json.dumps(new, ensure_ascii=False) if new is not None else None))


def _to_dict(row) -> dict:
    return {
        "id": row["id"],
        "raw_material_id": row["raw_material_id"],
        "dealer_id": row["dealer_id"],
        "dealer_name": row["dealer_name"],
        "dealer_archived": bool(row["dealer_archived"]),
        "article_no": row["article_no"],
        "note": row["note"],
        "price_cents_per_kg": row["price_cents_per_kg"],
        "price_changed_at": row["price_changed_at"],
        "grams_per_unit": row["grams_per_unit"],
        "unit_code": row["unit_code"],
        "commodity_group": row["commodity_group"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _raw_material(conn, raw_material_id: int):
    row = conn.execute("SELECT id, number, name, archived, price_cents_per_kg, price_changed_at "
                       "FROM raw_material WHERE id = ?", (raw_material_id,)).fetchone()
    if row is None:
        raise NotFoundError("Rohstoff nicht gefunden.", code="not_found")
    return row


def _fetch(conn, source_id: int, raw_material_id: int | None = None):
    row = conn.execute(_SELECT + " WHERE s.id = ?", (source_id,)).fetchone()
    if row is None or (raw_material_id is not None and row["raw_material_id"] != raw_material_id):
        raise NotFoundError("Bezugsquelle nicht gefunden.", code="not_found")
    return row


def active_source(conn, raw_material_id: int):
    return conn.execute(_SELECT + " WHERE s.raw_material_id = ? AND s.is_active = 1",
                        (raw_material_id,)).fetchone()


def has_sources(conn, raw_material_id: int) -> bool:
    return conn.execute("SELECT 1 FROM raw_material_source WHERE raw_material_id = ? LIMIT 1",
                        (raw_material_id,)).fetchone() is not None


def _opt_text(data: dict, key: str, label: str, max_len: int, *, upper: bool = False) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        raise ValidationError(f"{label} muss ein Text sein.", field=key)
    text = normalize_text(value)
    if not text:
        return None
    if len(text) > max_len:
        raise ValidationError(f"{label} darf höchstens {max_len} Zeichen lang sein.", field=key)
    check_no_formula_start(text, field=key, label=label)
    return text.upper() if upper else text


def _clean(data: dict, warnings: list | None) -> dict:
    """Eingaben einer Bezugsquelle → Spaltenwerte (nur mitgeschickte Felder)."""
    clean: dict = {}
    if "article_no" in data:
        clean["article_no"] = _opt_text(data, "article_no", "Artikelnummer", MAX_ARTICLE_NO)
    if "note" in data:
        clean["note"] = _opt_text(data, "note", "Bemerkung", MAX_NOTE)
    if "unit_code" in data:
        clean["unit_code"] = _opt_text(data, "unit_code", "Mengeneinheit", MAX_UNIT_CODE, upper=True)
    if "commodity_group" in data:
        clean["commodity_group"] = _opt_text(data, "commodity_group", "Warengruppe", MAX_COMMODITY_GROUP)
    if "grams_per_unit" in data:
        grams = _whole_number(data["grams_per_unit"], "grams_per_unit", "g je Mengeneinheit")
        if grams is not None and not 0 < grams <= MAX_GRAMS_PER_UNIT:
            raise ValidationError("g je Mengeneinheit muss zwischen 1 und 1 000 000 liegen.",
                                  field="grams_per_unit")
        clean["grams_per_unit"] = grams
    if "price_per_kg" in data:
        cents, hint = parse_price(data["price_per_kg"])
        if hint and warnings is not None:
            warnings.append({"field": "price_per_kg", "code": "price_rounded", "detail": hint})
        clean["price_cents_per_kg"] = cents
    return clean


def sync_price_in_tx(conn, raw_material_id: int, source: str = "admin") -> tuple[int | None, int | None]:
    """Spiegelt den Preis der aktiven Bezugsquelle an den Rohstoff (M04-14, K04-2).

    Ohne aktive Bezugsquelle bleibt der Preis am Rohstoff. Liefert (alt, neu) des gültigen Preises.
    """
    rm = _raw_material(conn, raw_material_id)
    active = active_source(conn, raw_material_id)
    if active is None or active["price_cents_per_kg"] == rm["price_cents_per_kg"]:
        return rm["price_cents_per_kg"], rm["price_cents_per_kg"]
    new = active["price_cents_per_kg"]
    conn.execute(f"UPDATE raw_material SET price_cents_per_kg = ?, price_changed_at = {_NOW}, updated_at = {_NOW} "
                 "WHERE id = ?", (new, raw_material_id))
    conn.execute(
        "INSERT INTO change_log (source, entity, entity_id, action, old_values, new_values) "
        "VALUES (?, 'raw_material', ?, 'update', ?, ?)",
        (source, raw_material_id, json.dumps({"price_cents_per_kg": rm["price_cents_per_kg"]}),
         json.dumps({"price_cents_per_kg": new, "via": "active_source"})))
    return rm["price_cents_per_kg"], new


# -- Lesen ----------------------------------------------------------------------

def list_sources(conn: sqlite3.Connection, raw_material_id: int) -> list[dict]:
    _raw_material(conn, raw_material_id)
    rows = conn.execute(_SELECT + " WHERE s.raw_material_id = ? ORDER BY s.is_active DESC, d.name COLLATE NOCASE",
                        (raw_material_id,))
    return [_to_dict(r) for r in rows]


def find_by_article(conn: sqlite3.Connection, dealer_id: int, article_no: str) -> list[dict]:
    """Bezugsquellen eines Händlers mit dieser Artikelnummer (Zuordnung für den Beleg-Import, K03-18)."""
    rows = conn.execute(_SELECT + " WHERE s.dealer_id = ? AND s.article_no = ?", (dealer_id, article_no))
    return [_to_dict(r) for r in rows]


# -- Ändern (in offener Transaktion) ---------------------------------------------

def add_in_tx(conn, raw_material_id: int, data: dict, source: str = "admin",
              warnings: list | None = None) -> int:
    """Neue Bezugsquelle. Die erste wird aktiv und übernimmt den bisherigen Preis (K04-1)."""
    rm = _raw_material(conn, raw_material_id)
    dealer = dealers.find_or_fail_active(conn, data.get("dealer_id"))
    if conn.execute("SELECT 1 FROM raw_material_source WHERE raw_material_id = ? AND dealer_id = ?",
                    (raw_material_id, dealer["id"])).fetchone():
        raise ConflictError(f"Der Händler „{dealer['name']}“ ist bei diesem Rohstoff schon eingetragen.",
                            field="dealer_id", code="dealer_taken")
    clean = _clean(data, warnings)
    first = not has_sources(conn, raw_material_id)
    price_given = "price_cents_per_kg" in clean
    price = clean.pop("price_cents_per_kg", None)
    price_at_sql = f"CASE WHEN ? IS NULL THEN NULL ELSE {_NOW} END"
    price_at_args: tuple = (price,)
    if first and not price_given and rm["price_cents_per_kg"] is not None:
        price = rm["price_cents_per_kg"]
        price_at_sql = "?"
        price_at_args = (rm["price_changed_at"],)
    make_active = first or data.get("is_active") is True
    if make_active and not first:
        conn.execute("UPDATE raw_material_source SET is_active = 0 WHERE raw_material_id = ? AND is_active = 1",
                     (raw_material_id,))
    cols = ", ".join(clean)
    new_id = conn.execute(
        "INSERT INTO raw_material_source (raw_material_id, dealer_id, price_cents_per_kg, price_changed_at, "
        f"is_active{', ' + cols if cols else ''}) VALUES (?, ?, ?, {price_at_sql}, ?"
        f"{', ?' * len(clean)})",
        (raw_material_id, dealer["id"], price, *price_at_args, 1 if make_active else 0, *clean.values()),
    ).lastrowid
    _log(conn, "create", new_id, None,
         {"raw_material_id": raw_material_id, "dealer": dealer["name"], "price_cents_per_kg": price,
          "is_active": make_active, **clean}, source)
    if make_active:
        sync_price_in_tx(conn, raw_material_id, source)
    return new_id


def update_in_tx(conn, raw_material_id: int, source_id: int, data: dict, source: str = "admin",
                 warnings: list | None = None) -> dict:
    """Ändert die mitgeschickten Felder einer Bezugsquelle; Preis der aktiven wird gespiegelt."""
    row = _fetch(conn, source_id, raw_material_id)
    if "dealer_id" in data and data["dealer_id"] != row["dealer_id"]:
        raise ValidationError("Der Händler einer Bezugsquelle lässt sich nicht ändern – "
                              "bitte neue Bezugsquelle anlegen.", field="dealer_id", code="dealer_fixed")
    clean = _clean(data, warnings)
    changes = {k: v for k, v in clean.items() if v != row[k]}
    if not changes:
        return {}
    assignments = ", ".join(f"{k} = ?" for k in changes)
    if "price_cents_per_kg" in changes:
        assignments += f", price_changed_at = {_NOW}"
    conn.execute(f"UPDATE raw_material_source SET {assignments}, updated_at = {_NOW} WHERE id = ?",
                 (*changes.values(), source_id))
    _log(conn, "update", source_id, {k: row[k] for k in changes}, changes, source)
    if row["is_active"] and "price_cents_per_kg" in changes:
        sync_price_in_tx(conn, raw_material_id, source)
    return {k: (row[k], v) for k, v in changes.items()}


def activate_in_tx(conn, raw_material_id: int, source_id: int, source: str = "admin") -> bool:
    """Setzt die Bezugsquelle aktiv (die bisherige wird Alternative). True = etwas geändert."""
    row = _fetch(conn, source_id, raw_material_id)
    if row["is_active"]:
        return False
    old = active_source(conn, raw_material_id)
    conn.execute("UPDATE raw_material_source SET is_active = 0 WHERE raw_material_id = ? AND is_active = 1",
                 (raw_material_id,))
    conn.execute(f"UPDATE raw_material_source SET is_active = 1, updated_at = {_NOW} WHERE id = ?", (source_id,))
    _log(conn, "update", source_id, {"active_dealer": old["dealer_name"] if old else None},
         {"active_dealer": row["dealer_name"]}, source)
    sync_price_in_tx(conn, raw_material_id, source)
    return True


def delete_in_tx(conn, raw_material_id: int, source_id: int, source: str = "admin") -> None:
    """Entfernt eine Bezugsquelle. Die aktive nur, wenn sie die letzte ist (R04-10)."""
    row = _fetch(conn, source_id, raw_material_id)
    others = conn.execute("SELECT COUNT(*) FROM raw_material_source WHERE raw_material_id = ? AND id <> ?",
                          (raw_material_id, source_id)).fetchone()[0]
    if row["is_active"] and others:
        raise ConflictError("Die aktive Bezugsquelle kann erst entfernt werden, wenn eine andere aktiv gesetzt ist.",
                            code="active_source")
    conn.execute("DELETE FROM raw_material_source WHERE id = ?", (source_id,))
    _log(conn, "delete", source_id, _to_dict(row), None, source)


def set_active_price_in_tx(conn, raw_material_id: int, cents: int | None, source: str = "admin") -> str | None:
    """Preis über den Rohstoff ändern (Formular, CSV-Import, M04-14): geht an die aktive Bezugsquelle.

    Liefert den Händlernamen, wenn eine aktive Bezugsquelle geändert wurde, sonst None
    (dann ändert der Aufrufer den Preis am Rohstoff selbst).
    """
    active = active_source(conn, raw_material_id)
    if active is None:
        return None
    if active["price_cents_per_kg"] != cents:
        conn.execute(f"UPDATE raw_material_source SET price_cents_per_kg = ?, price_changed_at = {_NOW}, "
                     f"updated_at = {_NOW} WHERE id = ?", (cents, active["id"]))
        _log(conn, "update", active["id"], {"price_cents_per_kg": active["price_cents_per_kg"]},
             {"price_cents_per_kg": cents}, source)
        sync_price_in_tx(conn, raw_material_id, source)
    return active["dealer_name"]


# -- Massenpflege (M04-6) ----------------------------------------------------------

def bulk_active_source_in_tx(conn, raw_material_ids: list[int], dealer_id, source: str = "admin") -> list[dict]:
    """Setzt den Händler bei allen Rohstoffen als aktive Bezugsquelle; fehlt er, wird er angelegt.

    Liefert je Rohstoff, was sich ändert (für Vorschau und Ergebnis).
    """
    dealer = dealers.find_or_fail_active(conn, dealer_id)
    result = []
    for rm_id in raw_material_ids:
        rm = _raw_material(conn, rm_id)
        old_active = active_source(conn, rm_id)
        existing = conn.execute("SELECT id, is_active FROM raw_material_source WHERE raw_material_id = ? "
                                "AND dealer_id = ?", (rm_id, dealer["id"])).fetchone()
        if existing is not None and existing["is_active"]:
            action = "unchanged"
        elif existing is not None:
            activate_in_tx(conn, rm_id, existing["id"], source)
            action = "activated"
        else:
            add_in_tx(conn, rm_id, {"dealer_id": dealer["id"], "is_active": True}, source)
            action = "created"
        new_price = conn.execute("SELECT price_cents_per_kg FROM raw_material WHERE id = ?", (rm_id,)).fetchone()[0]
        result.append({
            "raw_material_id": rm_id, "number": rm["number"], "name": rm["name"], "archived": bool(rm["archived"]),
            "action": action,
            "old_dealer": old_active["dealer_name"] if old_active else None,
            "new_dealer": dealer["name"],
            "old_price_cents_per_kg": rm["price_cents_per_kg"],
            "new_price_cents_per_kg": new_price,
            "price_changes": rm["price_cents_per_kg"] != new_price,
        })
    return result


# -- Öffentliche Funktionen (eigene Transaktion) ----------------------------------

def _integrity(exc: sqlite3.IntegrityError) -> ConflictError:
    return ConflictError(f"Die Bezugsquelle konnte nicht gespeichert werden: {exc}", code="integrity")


def _with_warnings(result: list[dict], warnings: list) -> dict:
    answer: dict = {"sources": result}
    if warnings:
        answer["warnings"] = warnings
    return answer


def add_source(conn, raw_material_id: int, data: dict, source: str = "admin") -> dict:
    warnings: list = []
    _clean(data, None)
    try:
        with transaction(conn):
            add_in_tx(conn, raw_material_id, data, source, warnings)
    except sqlite3.IntegrityError as exc:
        raise _integrity(exc) from exc
    return _with_warnings(list_sources(conn, raw_material_id), warnings)


def update_source(conn, raw_material_id: int, source_id: int, data: dict, source: str = "admin") -> dict:
    warnings: list = []
    _clean(data, None)
    try:
        with transaction(conn):
            update_in_tx(conn, raw_material_id, source_id, data, source, warnings)
    except sqlite3.IntegrityError as exc:
        raise _integrity(exc) from exc
    return _with_warnings(list_sources(conn, raw_material_id), warnings)


def activate_source(conn, raw_material_id: int, source_id: int, source: str = "admin") -> dict:
    with transaction(conn):
        activate_in_tx(conn, raw_material_id, source_id, source)
    return _with_warnings(list_sources(conn, raw_material_id), [])


def delete_source(conn, raw_material_id: int, source_id: int, source: str = "admin") -> dict:
    with transaction(conn):
        delete_in_tx(conn, raw_material_id, source_id, source)
    return _with_warnings(list_sources(conn, raw_material_id), [])


MAX_BULK = 500


def bulk_active_source(conn, data: dict, source: str = "admin") -> dict:
    """Massenpflege mit Vorschau: ``dry_run`` = true rechnet alles in der Transaktion und rollt zurück."""
    ids = data.get("raw_material_ids")
    if (not isinstance(ids, list) or not ids
            or any(isinstance(i, bool) or not isinstance(i, int) for i in ids)):
        raise ValidationError("Bitte mindestens einen Rohstoff markieren.", field="raw_material_ids")
    ids = list(dict.fromkeys(ids))
    if len(ids) > MAX_BULK:
        raise ValidationError(f"Höchstens {MAX_BULK} Rohstoffe auf einmal.", field="raw_material_ids")
    dry_run = data.get("dry_run") is True

    class _Rollback(Exception):
        pass

    result: list[dict] = []
    try:
        with transaction(conn):
            result = bulk_active_source_in_tx(conn, ids, data.get("dealer_id"), source)
            if dry_run:
                raise _Rollback
    except _Rollback:
        pass
    except sqlite3.IntegrityError as exc:
        raise _integrity(exc) from exc
    return {"dry_run": dry_run, "items": result,
            "changed": sum(1 for r in result if r["action"] != "unchanged"),
            "price_changes": sum(1 for r in result if r["price_changes"])}


def price_text(cents: int | None) -> str:
    return "(leer)" if cents is None else euro_text(cents) + " €"
