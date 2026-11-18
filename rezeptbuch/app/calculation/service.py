"""Rezeptberechnung mit Datenbank (Modul 06, docs/berechnung.md Abschnitt 5 und 7).

Öffentliche Funktionen:

* ``basis_options(conn, recipe_id)`` – was die Vorwahl anbieten darf
* ``calculate(conn, payload)`` – Berechnung für die Schnittstelle und die Prüfseite
* ``validate_basis(conn, recipe_id, order)`` – Prüfung der Auftragsfelder für Modul 09 (Befund B4)
* ``build_batch_items(conn, order_id, version_id)`` – Chargenzeilen nur aus der fixierten Version (Befund B2)
* ``tolerance_g(target_g, unit, value)`` – Toleranzregel, auch für die Wiegeanzeige

Alle Funktionen lesen nur; sie schreiben nichts in die Datenbank.
"""

from __future__ import annotations

import sqlite3

from ..errors import NotFoundError, ValidationError
from . import engine
from .engine import Basis, tolerance_g  # noqa: F401  (tolerance_g für Modul 09 hier mit angeboten)
from .loader import batch_sizes, load_recipe
from .models import CalcRequest, MAX_PIECES, check_unit, validate_request, whole_number

__all__ = ["basis_options", "build_batch_items", "calculate", "tolerance_g", "validate_basis"]


def _recipe_head(recipe: engine.Recipe) -> dict:
    return {"id": recipe.id, "number": recipe.number, "name": recipe.name, "version_no": recipe.version_no,
            "current_version": recipe.current, "locked": recipe.locked, "archived": recipe.archived}


def basis_options(conn: sqlite3.Connection, recipe_id: int, version_no: int | None = None) -> dict:
    """Bezugsgrößen für die Vorwahl (Abschnitt 7.1, M02-1, M06-4, K06-1)."""
    recipe = load_recipe(conn, recipe_id, version_no=version_no)
    engine.check_tree(recipe)
    flour = engine.flour_g(recipe)
    return {
        "recipe": _recipe_head(recipe),
        "total_g": int(engine.total_g(recipe)),
        "flour_g": engine.round_half_up(flour),
        "flour_exact": engine.decimal_text(flour),
        "flour_total_available": flour > 0,      # „Mehl gesamt“ nur, wenn das Rezept Mehl enthält (M06-4)
        "knead": None if recipe.knead_slow_min is None and recipe.knead_fast_min is None
        else f"{recipe.knead_slow_min or 0}+{recipe.knead_fast_min or 0}",
        "piece_weights": [{"id": p.id, "label": p.label, "weight_g": p.weight_g} for p in recipe.piece_weights],
        "batch_sizes": batch_sizes(conn, recipe_id),
        "raw_materials": engine.leading_materials(recipe),
    }


def _batch_size(conn: sqlite3.Connection, recipe_id: int, batch_size_id: int) -> dict:
    for size in batch_sizes(conn, recipe_id):
        if size["id"] == batch_size_id:
            return size
    raise ValidationError("Chargengröße gehört nicht zu diesem Rezept.", field="batch_size_id",
                          code="batch_size_not_in_recipe")


def _piece_weights(recipe: engine.Recipe, pieces) -> list[dict]:
    known = {p.id: p for p in recipe.piece_weights}
    result = []
    for piece_weight_id, count in pieces:
        pw = known.get(piece_weight_id)
        if pw is None:
            raise ValidationError("Stückgewicht gehört nicht zu diesem Rezept.", field="pieces",
                                  code="piece_weight_not_in_recipe")
        result.append({"piece_weight_id": pw.id, "label": pw.label, "weight_g": pw.weight_g, "count": count})
    return result


def _resolve(conn: sqlite3.Connection, recipe: engine.Recipe, req: CalcRequest) -> tuple[Basis, bool, dict]:
    """Eingabe der Vorwahl → Bezugsgröße in Gramm je Teig (Abschnitt 4.2)."""
    extra: dict = {"input_unit": req.input_unit or None, "input_value": req.input_value}
    if req.basis_type in ("total", "flour_total"):
        return Basis(req.basis_type, req.value_g), True, extra
    if req.basis_type == "raw_material":
        return Basis("raw_material", req.value_g, req.raw_material_id, req.item_position), True, extra
    if req.basis_type == "pieces":
        pieces = _piece_weights(recipe, req.pieces)
        extra["pieces"] = pieces
        target = sum(p["weight_g"] * p["count"] for p in pieces)
        return Basis("pieces", target), False, extra
    size = _batch_size(conn, recipe.id, req.batch_size_id)
    if req.input_unit:
        check_unit("batch_size", req.input_unit)
        if (req.input_unit == "pcs") != (size["kind"] == "pieces"):
            raise ValidationError("Die Einheit passt nicht zu dieser Chargengröße.", field="input_unit",
                                  code="unit_invalid")
    extra["batch_size"] = size
    return Basis("batch_size", size["weight_g"]), size["kind"] == "weight", extra


def calculate(conn: sqlite3.Connection, payload) -> dict:
    """Berechnung nach Abschnitt 4 (``POST /api/v1/calculation``, Prüfseite, später Vorwahl)."""
    req = payload if isinstance(payload, CalcRequest) else validate_request(payload)
    recipe = load_recipe(conn, req.recipe_id, version_no=req.version_no)
    basis, hints, extra = _resolve(conn, recipe, req)
    result = engine.calculate(recipe, basis, overrides=req.overrides, piece_hints=hints)
    result["basis"].update(extra)
    return result


# ---------------------------------------------------------------------------
# Für den Wiegeablauf (Modul 09)
# ---------------------------------------------------------------------------

def validate_basis(conn: sqlite3.Connection, recipe_id: int, order: dict) -> None:
    """Prüft die Bezugsgröße eines Auftrags vor dem Speichern (Befund B4, P06-1 bis P06-8).

    ``order`` enthält die Spalten von ``production_order`` (``basis_type``, ``basis_value`` in
    Gramm, ``basis_input_unit``, ``basis_raw_material_id``, ``basis_item_position``,
    ``batch_size_id``), dazu ``pieces`` als Liste ``{piece_weight_id, count}`` (wird zu
    ``order_piece``), optional ``recipe_version_id`` und ``overrides`` ``{position: amount_g}``.
    Wirft ``ValidationError`` mit Feld; gibt nichts zurück.
    """
    basis_type = order.get("basis_type")
    if basis_type not in engine.BASIS_TYPES:
        raise ValidationError("Bitte eine Bezugsgröße wählen.", field="basis_type", code="basis_type")
    value = whole_number(order.get("basis_value"), "basis_value", "Die Menge", minimum=1,
                         maximum=engine.MAX_DOUGH_G)
    unit = order.get("basis_input_unit") or "g"
    check_unit(basis_type, unit)
    raw_material_id = order.get("basis_raw_material_id")
    item_position = order.get("basis_item_position")
    if basis_type != "raw_material" and (raw_material_id is not None or item_position is not None):
        raise ValidationError("Ein Leitrohstoff gibt es nur bei der Bezugsgröße „Leitrohstoff“.",
                              field="basis_raw_material_id", code="basis_fields")
    if basis_type != "batch_size" and order.get("batch_size_id") is not None:
        raise ValidationError("Eine Chargengröße gibt es nur bei der Bezugsgröße „Chargengröße“.",
                              field="batch_size_id", code="basis_fields")
    if basis_type != "pieces" and order.get("pieces"):
        raise ValidationError("Stückzahlen gibt es nur bei der Bezugsgröße „Stückzahlen“.",
                              field="pieces", code="basis_fields")

    recipe = load_recipe(conn, recipe_id, version_id=order.get("recipe_version_id"))
    piece_hints = True
    if basis_type == "pieces":
        entries = order.get("pieces") or []
        pieces = _piece_weights(recipe, [
            (whole_number(p.get("piece_weight_id"), "pieces", "das Stückgewicht", minimum=1),
             whole_number(p.get("count"), "pieces", "Die Stückzahl", minimum=1, maximum=MAX_PIECES))
            for p in entries if isinstance(p, dict)])
        if not pieces or len(pieces) != len(entries):
            raise ValidationError("Bitte mindestens eine Stückzahl eingeben.", field="pieces", code="pieces_missing")
        if sum(p["weight_g"] * p["count"] for p in pieces) != value:
            raise ValidationError("Die Stückzahlen ergeben nicht die gespeicherte Menge.", field="basis_value",
                                  code="pieces_sum")
        piece_hints = False
    if basis_type == "batch_size":
        batch_size_id = whole_number(order.get("batch_size_id"), "batch_size_id", "eine Chargengröße", minimum=1)
        size = _batch_size(conn, recipe_id, batch_size_id)
        if (unit == "pcs") != (size["kind"] == "pieces"):
            raise ValidationError("Die Einheit passt nicht zu dieser Chargengröße.", field="basis_input_unit",
                                  code="unit_invalid")
        if size["weight_g"] != value:
            raise ValidationError("Die Chargengröße ergibt nicht die gespeicherte Menge.", field="basis_value",
                                  code="batch_size_value")
    # Leitrohstoff im Rezept, Mehl vorhanden, Teig nicht zu groß: dieselbe Rechnung wie die Vorwahl
    engine.calculate(recipe, Basis(basis_type, value, raw_material_id, item_position),
                     overrides=order.get("overrides") or None, piece_hints=piece_hints)


def build_batch_items(conn: sqlite3.Connection, order_id: int, version_id: int) -> list[dict]:
    """Werte für ``batch_item`` eines Teigs, nur aus der fixierten Version des Auftrags (Befund B2).

    Jede Zeile enthält die Spalten ``position``, ``recipe_item_id``, ``item_type``,
    ``raw_material_id``, ``raw_material_number``, ``raw_material_name`` (Kopien), ``sub_order_id``
    (leer; Modul 09 legt den Unterrezept-Auftrag mit ``target_g`` als Gesamtteig an, R06-5),
    ``target_g``, ``tolerance_g``, ``unit_size_g``, ``unit_label``, ``units_target``, ``rest_target_g``.
    Zusätzlich (keine Spalten): ``kind`` (raw_material, hand, sub_recipe), ``is_hand_ack``,
    ``sub_recipe_id``, ``station_name``.
    """
    order = conn.execute("SELECT * FROM production_order WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise NotFoundError("Auftrag nicht gefunden.", code="not_found")
    if order["recipe_version_id"] is None:
        raise ValidationError("Die Rezeptversion des Auftrags ist noch nicht fixiert.", field="version_id",
                              code="version_not_fixed")
    if order["recipe_version_id"] != version_id:
        raise ValidationError("Die Version gehört nicht zum Auftrag.", field="version_id", code="version_mismatch")
    overrides = {r["item_position"]: r["amount_g"] for r in conn.execute(
        "SELECT item_position, amount_g FROM order_item_override WHERE order_id = ?", (order_id,))}
    recipe = load_recipe(conn, order["recipe_id"], version_id=version_id)
    basis = Basis(order["basis_type"], order["basis_value"], order["basis_raw_material_id"],
                  order["basis_item_position"])
    result = engine.calculate(recipe, basis, overrides=overrides or None, piece_hints=False)

    rows = []
    for item in result["items"]:
        rm = item["raw_material"]
        tol = item["tolerance"]
        units = item["units"]
        rows.append({
            "position": item["position"],
            "recipe_item_id": item["recipe_item_id"],
            "item_type": "sub_recipe" if item["kind"] == "sub_recipe" else "raw_material",
            "raw_material_id": rm["id"] if rm else None,
            "raw_material_number": rm["number"] if rm else None,
            "raw_material_name": rm["name"] if rm else None,
            "sub_order_id": None,
            "target_g": item["target_g"],
            "tolerance_g": tol["tolerance_g"] if tol else 0,
            "unit_size_g": units["size_g"] if units else None,
            "unit_label": units["label"] if units else None,
            "units_target": units["count"] if units else 0,
            "rest_target_g": units["rest_g"] if units else item["target_g"],
            "kind": item["kind"],
            "is_hand_ack": bool(tol and tol["is_hand_ack"]),
            "sub_recipe_id": item["sub_recipe"]["id"] if item["sub_recipe"] else None,
            "station_name": rm["station_name"] if rm else item["sub_recipe"]["name"],
        })
    return rows
