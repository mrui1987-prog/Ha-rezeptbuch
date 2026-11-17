"""Rezeptbaum aus der Datenbank lesen (Modul 06, docs/berechnung.md Abschnitt 2).

Liefert die Datenobjekte des Rechenkerns (``engine.Recipe``). Das Hauptrezept kommt in der
gewünschten Version (Vorgabe: aktuelle Version), jedes Unterrezept in seiner aktuellen
Version; im Wiegeablauf (Modul 09) bekommen Unterrezept-Aufträge ihre eigene fixierte Version.
Nur lesend, keine Schreibvorgänge.
"""

from __future__ import annotations

import sqlite3

from ..errors import NotFoundError, ValidationError
from .engine import MAX_DEPTH, Line, Material, PieceWeight, Recipe

_LINES_SQL = (
    "SELECT i.id, i.position, i.item_type, i.raw_material_id, i.sub_recipe_id, i.amount_g, "
    "       i.tolerance_unit, i.tolerance_value, i.step_no, i.needs_review, s.name AS step_name "
    "FROM recipe_item i "
    "LEFT JOIN recipe_version_step s ON s.recipe_version_id = i.recipe_version_id AND s.step_no = i.step_no "
    "WHERE i.recipe_version_id = ? ORDER BY i.position")


def _material(conn: sqlite3.Connection, material_id: int, cache: dict) -> Material:
    if material_id not in cache:
        r = conn.execute(
            "SELECT id, number, name, display_name, type, tolerance_unit, tolerance_value, unit_size_g, "
            "       unit_label, archived FROM raw_material WHERE id = ?", (material_id,)).fetchone()
        cache[material_id] = Material(
            id=r["id"], number=r["number"], name=r["name"], type=r["type"],
            tolerance_unit=r["tolerance_unit"], tolerance_value=r["tolerance_value"],
            display_name=r["display_name"], unit_size_g=r["unit_size_g"], unit_label=r["unit_label"],
            archived=bool(r["archived"]))
    return cache[material_id]


def _version_row(conn: sqlite3.Connection, recipe_row, version_no: int | None, version_id: int | None):
    if version_id is not None:
        row = conn.execute("SELECT * FROM recipe_version WHERE id = ? AND recipe_id = ?",
                           (version_id, recipe_row["id"])).fetchone()
    elif version_no is not None:
        row = conn.execute("SELECT * FROM recipe_version WHERE recipe_id = ? AND version_no = ?",
                           (recipe_row["id"], version_no)).fetchone()
    else:
        row = conn.execute("SELECT * FROM recipe_version WHERE id = ?",
                           (recipe_row["current_version_id"],)).fetchone()
    if row is None:
        raise NotFoundError("Version nicht gefunden.", code="not_found")
    return row


def _load(conn: sqlite3.Connection, recipe_id: int, version_no: int | None, version_id: int | None,
          path: tuple, cache: dict, with_pieces: bool) -> Recipe:
    recipe_row = conn.execute("SELECT id, number, current_version_id, locked, archived FROM recipe WHERE id = ?",
                              (recipe_id,)).fetchone()
    if recipe_row is None:
        raise NotFoundError("Rezept nicht gefunden.", code="not_found")
    version = _version_row(conn, recipe_row, version_no, version_id)
    path = path + ((recipe_id, version["name"]),)
    if len(path) > MAX_DEPTH + 1:
        raise ValidationError("Unterrezepte sind zu tief verschachtelt (höchstens 10 Ebenen).",
                              field="recipe_id", code="sub_recipe_too_deep")

    lines = []
    for r in conn.execute(_LINES_SQL, (version["id"],)).fetchall():
        common = dict(position=r["position"], amount_g=r["amount_g"], step_no=r["step_no"],
                      step_name=r["step_name"], needs_review=bool(r["needs_review"]), item_id=r["id"])
        if r["item_type"] == "sub_recipe":
            sub_id = r["sub_recipe_id"]
            if any(rid == sub_id for rid, _ in path):
                sub_name = conn.execute(
                    "SELECT v.name FROM recipe s JOIN recipe_version v ON v.id = s.current_version_id "
                    "WHERE s.id = ?", (sub_id,)).fetchone()
                names = " → ".join([name for _, name in path] + [sub_name["name"] if sub_name else str(sub_id)])
                raise ValidationError(f"Unterrezepte bilden einen Kreis: {names}.", field="recipe_id",
                                      code="sub_recipe_cycle")
            sub = _load(conn, sub_id, None, None, path, cache, False)
            lines.append(Line(sub=sub, **common))
        else:
            lines.append(Line(material=_material(conn, r["raw_material_id"], cache),
                              tolerance_unit=r["tolerance_unit"], tolerance_value=r["tolerance_value"], **common))

    pieces = ()
    if with_pieces:
        pieces = tuple(PieceWeight(r["id"], r["label"], r["weight_g"]) for r in conn.execute(
            "SELECT id, label, weight_g FROM recipe_piece_weight WHERE recipe_id = ? ORDER BY sort_order, id",
            (recipe_id,)))
    return Recipe(
        id=recipe_id, number=recipe_row["number"], name=version["name"], version_no=version["version_no"],
        version_id=version["id"], lines=tuple(lines), knead_slow_min=version["knead_slow_min"],
        knead_fast_min=version["knead_fast_min"], piece_weights=pieces, locked=bool(recipe_row["locked"]),
        archived=bool(recipe_row["archived"]), current=version["id"] == recipe_row["current_version_id"])


def load_recipe(conn: sqlite3.Connection, recipe_id: int, *, version_no: int | None = None,
                version_id: int | None = None) -> Recipe:
    """Rezept mit Zeilen, Unterrezepten (alle Ebenen) und Stückgewichten des Hauptrezepts."""
    return _load(conn, recipe_id, version_no, version_id, (), {}, True)


def batch_sizes(conn: sqlite3.Connection, recipe_id: int) -> list[dict]:
    """Chargengrößen des Rezepts mit Gewicht in Gramm (bei „Stück“: Anzahl × Stückgewicht)."""
    rows = conn.execute(
        "SELECT b.id, b.label, b.kind, b.value, b.piece_weight_id, p.label AS piece_label, p.weight_g AS piece_g "
        "FROM recipe_batch_size b LEFT JOIN recipe_piece_weight p ON p.id = b.piece_weight_id "
        "WHERE b.recipe_id = ? ORDER BY b.sort_order, b.id", (recipe_id,))
    return [{
        "id": r["id"], "label": r["label"], "kind": r["kind"], "value": r["value"],
        "piece_weight_id": r["piece_weight_id"], "piece_weight_label": r["piece_label"],
        "piece_weight_g": r["piece_g"],
        "weight_g": r["value"] if r["kind"] == "weight" else r["value"] * r["piece_g"],
    } for r in rows]
