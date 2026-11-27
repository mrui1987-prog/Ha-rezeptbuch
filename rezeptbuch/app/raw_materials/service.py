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
from ..errors import ConflictError, NotFoundError, ValidationError
from . import sources as sources_mod
from . import stock as stock_mod
from .models import COUNTED_TYPES, TYPES, normalize_text, parse_price, tolerance_display, validate

# Ähnlichkeit ab der ein Name als „ähnlich“ gemeldet wird (R03-3)
SIMILARITY_THRESHOLD = 0.8

_COLUMNS = ("number", "name", "display_name", "type", "tolerance_unit", "tolerance_value",
            "unit_size_g", "unit_label", "delivery_pack_g", "delivery_pack_label")
# Lagerorte (M03-25, Strichcode S1): Ort 1 und optional Ort 2 mit eigener Beschriftung
_LOCATION_COLUMNS = ("location1_id", "location1_label", "location2_id", "location2_label")
# Abgeleitete Tabelle mit der aktiven Bezugsquelle (Modul 04, K04-4); Bedingungen wie „id = ?“
# und „archived = 0“ beziehen sich so weiter eindeutig auf den Rohstoff.
_SELECT = ("SELECT * FROM (SELECT r.id, r.number, r.name, r.display_name, r.type, r.tolerance_unit, "
           "r.tolerance_value, r.unit_size_g, r.unit_label, r.source, r.archived, r.created_at, r.updated_at, "
           "r.price_cents_per_kg, r.price_changed_at, r.stock_g, r.stock_alert_g, r.datenlink_id, "
           "r.delivery_pack_g, r.delivery_pack_label, r.location1_id, r.location1_label, r.location2_id, "
           "r.location2_label, l1.name AS location1_name, l2.name AS location2_name, "
           "r.is_deposit, r.register_no, r.stock_ref_id, r.piece_g, ref.number AS stock_ref_number, "
           "ref.name AS stock_ref_name, (SELECT a.name FROM sales_article a WHERE a.register_no = r.register_no) "
           "AS register_name, "
           "(SELECT count(*) FROM raw_material_barcode c WHERE c.raw_material_id = r.id) AS barcode_count, "
           "s.id AS active_source_id, s.article_no AS active_article_no, d.id AS active_dealer_id, "
           "d.name AS active_dealer_name "
           "FROM raw_material r "
           "LEFT JOIN raw_material_source s ON s.raw_material_id = r.id AND s.is_active = 1 "
           "LEFT JOIN dealer d ON d.id = s.dealer_id "
           "LEFT JOIN storage_location l1 ON l1.id = r.location1_id "
           "LEFT JOIN storage_location l2 ON l2.id = r.location2_id "
           "LEFT JOIN raw_material ref ON ref.id = r.stock_ref_id)")

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
        # Liefergebinde (F-1): leer = Gebinde; der Scanner zählt in Liefergebinden
        "delivery_pack_g": row["delivery_pack_g"],
        "delivery_pack_label": row["delivery_pack_label"],
        "location1_id": row["location1_id"],
        "location1_name": row["location1_name"],
        "location1_label": row["location1_label"],
        "location2_id": row["location2_id"],
        "location2_name": row["location2_name"],
        "location2_label": row["location2_label"],
        "barcode_count": row["barcode_count"],
        "source": row["source"],
        "archived": bool(row["archived"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        # Preis je kg in Cent (VC03-a, R03-16: auch ohne PIN lesbar)
        "price_cents_per_kg": row["price_cents_per_kg"],
        "price_changed_at": row["price_changed_at"],
        # Bestand und Meldewert (VC03-b, docs/bestand.md); leer = keine Bestandsführung
        "stock_g": row["stock_g"],
        "stock_alert_g": row["stock_alert_g"],
        "stock_status": stock_mod.status(row["stock_g"], row["stock_alert_g"]),
        # Modul 04: Herkunft own/datenlink, Pass-Zuordnung, aktive Bezugsquelle (Preis = deren Preis, M04-14)
        "datenlink_id": row["datenlink_id"],
        # Handelsware (H1, docs/handelsware.md 3): Pfand, Kassennummer, Verweis auf den bestandsführenden Rohstoff
        "is_deposit": bool(row["is_deposit"]),
        "register_no": row["register_no"],
        "register_name": row["register_name"],
        "stock_ref": None if row["stock_ref_id"] is None else {
            "id": row["stock_ref_id"], "number": row["stock_ref_number"], "name": row["stock_ref_name"]},
        "piece_g": row["piece_g"],
        "register_hint": "ohne Kassenartikel, nur Inventur" if row["type"] == "goods" and row["register_no"] is None
        else None,
        "active_source": None if row["active_source_id"] is None else {
            "id": row["active_source_id"],
            "dealer_id": row["active_dealer_id"],
            "dealer_name": row["active_dealer_name"],
            "article_no": row["active_article_no"],
        },
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
    return {key: row[key] for key in (*_COLUMNS, "price_cents_per_kg", "stock_alert_g", "source", "archived")}


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
        "delivery_pack_g": row["delivery_pack_g"],
        "delivery_pack_label": row["delivery_pack_label"],
    }


def _name_key(name: str) -> str:
    """Vergleichsschlüssel für Namen: ohne Randleerzeichen, ohne Groß-/Kleinschreibung (auch Ä/Ö/Ü)."""
    return normalize_text(name).casefold()


# öffentlich für den Import (Modul 05): derselbe Namensvergleich wie bei R03-2
name_key = _name_key


def _find_active_with_name(conn: sqlite3.Connection, name: str, exclude_id: int | None = None,
                           type_: str | None = None):
    """Aktiver Eintrag mit gleichem Namen. Handelsware und übrige Arten zählen getrennt (K03-93: H-Milch als
    Rohstoff und als Handelsware); ``type_`` None = alle."""
    key = _name_key(name)
    for row in conn.execute("SELECT id, number, name, type FROM raw_material WHERE archived = 0"):
        if type_ is not None and (row["type"] == "goods") != (type_ == "goods"):
            continue
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


def _in_articles(conn: sqlite3.Connection, raw_material_id: int) -> bool:
    return conn.execute("SELECT 1 FROM sales_article_line WHERE raw_material_id = ? LIMIT 1",
                        (raw_material_id,)).fetchone() is not None


def _used_message(raw_material_id: int, use: dict) -> str:
    if use["recipes"]:
        n = use["recipes"]
        return f"wird in {n} Rezept{'en' if n != 1 else ''} verwendet"
    return "wird in Aufträgen oder Chargen verwendet"


def get_raw_material(conn: sqlite3.Connection, raw_material_id: int) -> dict:
    result = _to_dict(_fetch(conn, raw_material_id))
    result["usage"] = usage(conn, raw_material_id)
    return result


STATUS_FILTERS = ("active", "archived", "all")
STOCK_FILTERS = ("below_alert", "negative", "none", "attention")


def list_raw_materials(conn: sqlite3.Connection, search: str | None = None,
                       include_archived: bool = False, zero_percent: bool = False,
                       below_alert: bool = False, *, status: str | None = None, type_: str | None = None,
                       stock: str | None = None, no_price: bool = False, unused: bool = False,
                       dealer_id: int | None = None, no_source: bool = False,
                       ids: list[int] | None = None) -> list[dict]:
    """Liste nach Nummer sortiert. Die Suche findet Teile von Nummer, Name und Kurzname
    ohne Rücksicht auf Groß-/Kleinschreibung.

    ``zero_percent``: nur Rohstoffe mit Toleranz 0 % (Filter aus M05-13b; diese werden
    bei der Verwiegung auf ±1 g genau gewogen und sollten geprüft werden).
    ``below_alert``: nur aktive Rohstoffe mit Bestandsführung am/unter dem Meldewert (VC03-b, B8).

    Filter der Rohstoffverwaltung (M03-22, docs/rohstoffverwaltung.md 3), alle kombinierbar:
    ``status`` active/archived/all (ersetzt ``include_archived``, wenn angegeben), ``type_`` standard/flour,
    ``stock`` below_alert (am/unter Meldewert) / negative (im Minus) / none (ohne Bestandsführung) /
    attention (am/unter Meldewert oder im Minus, Meldeliste 6.2), ``no_price``, ``unused`` (in keiner
    aktuellen Version eines nicht archivierten Rezepts, K03-34), ``dealer_id`` (aktive Bezugsquelle bei
    diesem Händler), ``no_source`` (ohne Bezugsquelle), ``ids`` (nur diese, Export der Auswahl).
    """
    where: list[str] = []
    params: list = []
    if status is not None:
        if status not in STATUS_FILTERS:
            raise ValidationError("Unbekannter Status-Filter.", field="status")
        if status == "active":
            where.append("archived = 0")
        elif status == "archived":
            where.append("archived = 1")
    elif not include_archived:
        where.append("archived = 0")
    if zero_percent:
        where.append("tolerance_unit = 'percent' AND tolerance_value = 0")
    if below_alert:
        where.append("archived = 0 AND stock_g IS NOT NULL AND stock_alert_g IS NOT NULL "
                     "AND stock_g <= stock_alert_g")
    if type_ is not None:
        if type_ not in TYPES:
            raise ValidationError("Unbekannter Typ-Filter.", field="type")
        where.append("type = ?")
        params.append(type_)
    if stock is not None:
        if stock not in STOCK_FILTERS:
            raise ValidationError("Unbekannter Bestand-Filter.", field="stock")
        where.append({
            "below_alert": "stock_g IS NOT NULL AND stock_alert_g IS NOT NULL AND stock_g <= stock_alert_g",
            "negative": "stock_g IS NOT NULL AND stock_g < 0",
            "none": "stock_g IS NULL",
            "attention": "stock_g IS NOT NULL AND (stock_g < 0 OR (stock_alert_g IS NOT NULL "
                         "AND stock_g <= stock_alert_g))",
        }[stock])
    if no_price:
        where.append("price_cents_per_kg IS NULL")
    if unused:
        where.append("id NOT IN (SELECT i.raw_material_id FROM recipe_item i JOIN recipe r "
                     "ON r.current_version_id = i.recipe_version_id WHERE r.archived = 0 "
                     "AND i.raw_material_id IS NOT NULL)")
    if dealer_id is not None:
        where.append("active_dealer_id = ?")
        params.append(dealer_id)
    if no_source:
        where.append("id NOT IN (SELECT raw_material_id FROM raw_material_source)")
    if ids is not None:
        if not ids:
            return []
        where.append("id IN (" + ",".join("?" * len(ids)) + ")")
        params.extend(ids)
    sql = _SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY number"
    rows = [_to_dict(r) for r in conn.execute(sql, params)]
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

def _goods_fields(conn: sqlite3.Connection, data: dict, type_: str, row=None) -> dict:
    """Felder der Handelsware (H1): ``is_deposit``, ``register_no`` (Kassennummer), ``stock_ref_id`` + ``piece_g``
    (Verweis, K03-93). Nur mitgeschickte Felder; bei anderer Art werden sie geleert (CHECK-Regeln)."""
    if type_ != "goods":
        if row is None:
            return {}
        return {c: v for c, v in (("is_deposit", 0), ("register_no", None), ("stock_ref_id", None),
                                  ("piece_g", None)) if row[c] != v}
    out: dict = {}
    if "is_deposit" in data:
        if not isinstance(data["is_deposit"], bool):
            raise ValidationError("Pfand: ja oder nein.", field="is_deposit")
        out["is_deposit"] = 1 if data["is_deposit"] else 0
    if "register_no" in data:
        value = data["register_no"]
        if isinstance(value, str):
            value = value.strip()
            value = int(value) if value.isdigit() else (None if value == "" else value)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                  or not 0 < value <= 2_000_000_000):
            raise ValidationError("Kassennummer: ganze Zahl größer 0 (leer = ohne Kassenartikel).",
                                  field="register_no")
        if value is not None:
            other = conn.execute("SELECT number, name FROM raw_material WHERE register_no = ? AND archived = 0 "
                                 "AND id IS NOT ?", (value, row["id"] if row is not None else None)).fetchone()
            if other is not None:
                raise ConflictError(f"Die Kassennummer {value} hat schon „{other['name']}“ (Nummer {other['number']}).",
                                    field="register_no", code="register_no_taken")
        out["register_no"] = value
    if "stock_ref_id" in data or "piece_g" in data:
        ref = data.get("stock_ref_id", row["stock_ref_id"] if row is not None else None)
        piece = data.get("piece_g", row["piece_g"] if row is not None else None)
        if ref in (None, ""):
            out.update(stock_ref_id=None, piece_g=None)
        else:
            if isinstance(ref, bool) or not isinstance(ref, int):
                raise ValidationError("Ungültiger Rohstoff.", field="stock_ref_id")
            target = conn.execute("SELECT id, type, archived, name FROM raw_material WHERE id = ?", (ref,)).fetchone()
            if target is None or target["type"] not in ("standard", "flour") or (row is not None and ref == row["id"]):
                raise ValidationError("Bestand führen kann nur ein Rohstoff (Standard oder Mehl).", field="stock_ref_id")
            if isinstance(piece, str) and piece.strip().isdigit():
                piece = int(piece.strip())
            if isinstance(piece, bool) or not isinstance(piece, int) or not 0 < piece <= 1_000_000:
                raise ValidationError("Gewicht je Stück in g angeben (z. B. 1000 für 1 l H-Milch).", field="piece_g",
                                      code="piece_g_missing")
            out.update(stock_ref_id=ref, piece_g=piece)
            if row is not None and row["stock_g"] is not None:
                out["stock_g"] = None             # der Verweis führt keinen eigenen Bestand
    return out


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


def _alert(data: dict) -> tuple[bool, int | None]:
    """Meldewert aus der Eingabe (``stock_alert_kg``, VC03-b): (angegeben?, Gramm); leer = keiner."""
    if "stock_alert_kg" not in data:
        return False, None
    return True, stock_mod.parse_kg(data["stock_alert_kg"], "stock_alert_kg", allow_empty=True,
                                    allow_negative=False)


def _locations(conn: sqlite3.Connection, data: dict, row=None) -> dict:
    """Lagerorte aus der Eingabe (M03-25): nur mitgeschickte Felder; Ort muss in der Liste stehen (H-C)."""
    current = {c: (row[c] if row is not None else None) for c in _LOCATION_COLUMNS}
    merged = dict(current)
    for c in _LOCATION_COLUMNS:
        if c in data:
            value = data[c]
            if c.endswith("_id"):
                if value in (None, ""):
                    value = None
                elif isinstance(value, bool) or not isinstance(value, int):
                    raise ValidationError("Ungültiger Lagerort.", field=c)
                elif not conn.execute("SELECT 1 FROM storage_location WHERE id = ?", (value,)).fetchone():
                    raise ValidationError("Lagerort nicht gefunden.", field=c, code="not_found")
            else:
                if value is not None and not isinstance(value, str):
                    raise ValidationError("Beschriftung muss ein Text sein.", field=c)
                value = normalize_text(value or "") or None
                if value is not None and len(value) > 40:
                    raise ValidationError("Beschriftung höchstens 40 Zeichen.", field=c)
            merged[c] = value
    for n in ("1", "2"):
        if merged[f"location{n}_id"] is None:
            merged[f"location{n}_label"] = None
    if merged["location1_id"] is None and merged["location2_id"] is not None:
        merged["location1_id"], merged["location1_label"] = merged["location2_id"], merged["location2_label"]
        merged["location2_id"] = merged["location2_label"] = None
    if merged["location1_id"] is not None and merged["location1_id"] == merged["location2_id"]:
        raise ValidationError("Lagerort 2 muss ein anderer Ort sein.", field="location2_id")
    return {c: merged[c] for c in _LOCATION_COLUMNS if merged[c] != current[c]}


def create_in_tx(conn: sqlite3.Connection, data: dict, source: str = "admin",
                 warnings: list | None = None) -> int:
    """Legt einen eigenen Rohstoff an (R03-1, R03-2, R03-5, R03-6, R03-8, R03-12, R03-13) und liefert die ID.

    Ein Rundungshinweis zum Preis (K03-8) kommt in ``warnings``.
    """
    clean = validate(data)
    _, price = _price(data, warnings)
    _, alert = _alert(data)
    if clean["number"] is None:
        clean["number"] = next_number(conn)
    elif conn.execute("SELECT 1 FROM raw_material WHERE number = ?", (clean["number"],)).fetchone():
        raise ConflictError(f"Die Nummer {clean['number']} ist schon vergeben.",
                            field="number", code="number_taken")
    same = _find_active_with_name(conn, clean["name"], type_=clean["type"])
    if same is not None:
        raise ConflictError(
            f"Einen {'Handelsware-Artikel' if clean['type'] == 'goods' else 'Rohstoff'} „{same['name']}“ gibt es "
            f"schon (Nummer {same['number']}).", field="name", code="name_taken")
    goods = _goods_fields(conn, data, clean["type"])
    cur = conn.execute(
        "INSERT INTO raw_material (number, name, display_name, type, tolerance_unit, tolerance_value, "
        "unit_size_g, unit_label, delivery_pack_g, delivery_pack_label, source, price_cents_per_kg, "
        "price_changed_at, stock_alert_g) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'own', ?, CASE WHEN ? IS NULL THEN NULL ELSE {_NOW} END, ?)",
        (*(clean[c] for c in _COLUMNS), price, price, alert))
    new_id = cur.lastrowid
    locs = _locations(conn, data)
    if locs:
        conn.execute("UPDATE raw_material SET " + ", ".join(f"{c} = ?" for c in locs) + " WHERE id = ?",
                     (*locs.values(), new_id))
    if clean["type"] == "goods" and goods.get("stock_ref_id") is None and data.get("start_stock", True):
        goods["stock_g"] = 0                    # Handelsware führt Bestand ab Anlage (in Stück, K03-85)
    if goods:
        conn.execute("UPDATE raw_material SET " + ", ".join(f"{c} = ?" for c in goods) + " WHERE id = ?",
                     (*goods.values(), new_id))
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
    if price_changed and row["active_source_id"] is not None:
        # Mit aktiver Bezugsquelle gehört der Preis ihr (M04-14); der Rohstoff bekommt ihn gespiegelt
        dealer = sources_mod.set_active_price_in_tx(conn, raw_material_id, price, source)
        if warnings is not None:
            warnings.append({"field": "price_per_kg", "code": "price_on_source",
                             "detail": f"Preis an der aktiven Bezugsquelle „{dealer}“ geändert"})
        price_changed = False
        price_routed = (row["price_cents_per_kg"], price)
    else:
        price_routed = None
    if price_changed:
        changes["price_cents_per_kg"] = price
    alert_given, alert = _alert(data)
    if alert_given and alert != row["stock_alert_g"]:
        changes["stock_alert_g"] = alert
    changes.update(_locations(conn, data, row))
    new_type = changes.get("type", row["type"])
    for c, v in _goods_fields(conn, data, new_type, row).items():
        if v != row[c]:
            changes[c] = v
    if not changes:
        return {"price_cents_per_kg": price_routed} if price_routed else {}

    use = usage(conn, raw_material_id)
    if "number" in changes:
        if use["used"]:
            raise ConflictError(
                "Die Nummer ist in Rezepten verwendet und kann nicht mehr geändert werden.",
                field="number", code="number_locked")
        if conn.execute("SELECT 1 FROM raw_material WHERE number = ?", (changes["number"],)).fetchone():
            raise ConflictError(f"Die Nummer {changes['number']} ist schon vergeben.",
                                field="number", code="number_taken")
    if ("name" in changes or "type" in changes) and not row["archived"]:
        same = _find_active_with_name(conn, changes.get("name", row["name"]), exclude_id=raw_material_id,
                                      type_=new_type)
        if same is not None:
            raise ConflictError(
                f"Einen Rohstoff „{same['name']}“ gibt es schon (Nummer {same['number']}).",
                field="name", code="name_taken")
    if "type" in changes and changes["type"] in COUNTED_TYPES and (use["used"] or _in_articles(conn, raw_material_id)):
        # Hilfs- und Betriebsstoffe und Handelsware stehen nie in Rezepten, an der Waage oder im Planer (S8, W-6, K03-85)
        raise ConflictError("Der Wechsel zu „Hilfs- und Betriebsstoff“ oder „Handelsware“ geht nicht, solange der "
                            "Eintrag in Rezepten, Aufträgen oder Verkaufsartikeln steht – nur kopieren (K03-89).",
                            field="type", code="type_locked_aid")
    if "type" in changes and use["recipes"] and not confirm_type_change:
        n = use["recipes"]
        raise ConflictError(
            f"Der Typwechsel betrifft {n} Rezept{'e' if n != 1 else ''}: "
            "„Mehl gesamt“ ändert sich dort. Bitte bestätigen.",
            field="type", code="type_change_confirmation_required", affected_recipes=n)

    if "type" in changes and "goods" in (row["type"], changes["type"]) and row["stock_g"] is not None \
            and (row["type"] in ("standard", "flour") or changes["type"] in ("standard", "flour")):
        raise ConflictError("Gramm und Stück lassen sich nicht einfach umstellen – bitte „Verschieben nach …“ "
                            "nehmen (rechnet den Bestand über das Gewicht je Stück um).", field="type",
                            code="type_move_required")
    if "stock_g" in changes:                    # Verweis (K03-93): eigenen Bestand sauber beenden
        changes.pop("stock_g")
        stock_mod.inventory_in_tx(conn, raw_material_id, None, note="Verweis auf Rohstoff – Bestand dort",
                                  source=source)
    assignments = ", ".join(f"{c} = ?" for c in changes)
    if price_changed:
        assignments += f", price_changed_at = {_NOW}"
    conn.execute(
        f"UPDATE raw_material SET {assignments}, updated_at = {_NOW} "
        "WHERE id = ?", (*changes.values(), raw_material_id))
    _log(conn, "update", raw_material_id, {c: row[c] for c in changes}, changes, source)
    result = {c: (row[c], changes[c]) for c in changes}
    if price_routed:
        result["price_cents_per_kg"] = price_routed
    return result


def archive_in_tx(conn: sqlite3.Connection, raw_material_id: int, source: str = "admin",
                  stock_zero: bool = False) -> None:
    """Archiviert einen Rohstoff (R03-9). Rezepte, die ihn nutzen, bleiben unverändert.

    ``stock_zero``: Antwort auf „Bestand auf Null setzen?“ (VC03-b, B9) – Inventur auf 0.
    """
    row = _fetch(conn, raw_material_id)
    if row["archived"]:
        raise ConflictError("Der Rohstoff ist bereits archiviert.", code="already_archived")
    conn.execute("UPDATE raw_material SET archived = 1, "
                 "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?", (raw_material_id,))
    _log(conn, "archive", raw_material_id, {"archived": 0}, {"archived": 1}, source)
    if stock_zero:
        stock_mod.zero_in_tx(conn, raw_material_id, note="beim Archivieren auf 0 gesetzt", source=source)


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
    if row["datenlink_id"] is not None:
        twin = conn.execute("SELECT number, name FROM raw_material WHERE archived = 0 AND datenlink_id = ? "
                            "AND id <> ?", (row["datenlink_id"], raw_material_id)).fetchone()
        if twin is not None:
            raise ConflictError(
                f"Wiederherstellen nicht möglich: Der aktive Rohstoff „{twin['name']}“ (Nummer {twin['number']}) "
                "hat denselben Kennzeichnungspass (datenlink-ID).", code="datenlink_taken")
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
    _alert(data)
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


def archive_raw_material(conn: sqlite3.Connection, raw_material_id: int, source: str = "admin",
                         stock_zero: bool = False) -> dict:
    """Archiviert einen Rohstoff (eigene Transaktion)."""
    with transaction(conn):
        archive_in_tx(conn, raw_material_id, source, stock_zero=stock_zero)
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
