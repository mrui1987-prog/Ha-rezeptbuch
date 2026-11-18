"""Rezeptberechnung mit Datenbank (Modul 06, docs/berechnung.md Abschnitt 5 und 7).

Öffentliche Funktionen:

* ``basis_options(conn, recipe_id)`` – was die Vorwahl anbieten darf
* ``calculate(conn, payload)`` – Berechnung für die Schnittstelle und die Prüfseite
* ``validate_basis(conn, recipe_id, order)`` – Prüfung der Auftragsfelder für Modul 09 (Befund B4)
* ``build_batch_items(conn, order_id, version_id, dough_index)`` – Chargenzeilen je Teig, nur aus der fixierten
  Version (Befund B2, R06-42)
* ``sub_order_targets(conn, order_id, sub_modes)`` – Gesamtteig je Unterrezept-Auftrag (R06-45, R06-46)
* ``plan_doughs(demand_g, limit_g, count, mode)`` – Sollgrößen der Teige (R06-34 bis R06-41)
* ``tolerance_g(target_g, unit, value)`` – Toleranzregel, auch für die Wiegeanzeige

Alle Funktionen lesen nur; sie schreiben nichts in die Datenbank.
"""

from __future__ import annotations

import sqlite3
from fractions import Fraction

from ..errors import NotFoundError, ValidationError
from . import engine
from .engine import Basis, tolerance_g  # noqa: F401  (tolerance_g für Modul 09 hier mit angeboten)
from .loader import active_limit, batch_sizes, load_recipe
from . import models
from .models import CalcRequest, MAX_PIECES, check_unit, validate_request, whole_number

__all__ = ["basis_options", "build_batch_items", "calculate", "plan_doughs", "sub_order_targets", "tolerance_g",
           "validate_basis"]

plan_doughs = engine.plan_doughs


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
        # Teil C3: aktive Obergrenze (R06-27, R06-28) und Faktor (VC06-e)
        "limit": active_limit(conn, recipe_id),
        "factor_allowed": True,
    }


def _batch_size(conn: sqlite3.Connection, recipe_id: int, batch_size_id: int, field: str = "batch_size_id") -> dict:
    for size in batch_sizes(conn, recipe_id):
        if size["id"] == batch_size_id:
            return size
    raise ValidationError("Chargengröße gehört nicht zu diesem Rezept.", field=field,
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


def _limit(recipe: engine.Recipe, order_limit_g: int | None) -> tuple[int | None, str | None, str | None]:
    """Wirksame Obergrenze (R06-27 bis R06-31, K06-6): aktive Chargengröße oder Grenze nur für den Auftrag.

    Ohne aktive Chargengröße ist die Auftragsgrenze frei; mit aktiver Chargengröße darf sie nur kleiner sein
    (P06-17). Liefert (Gramm, Herkunft 'recipe'/'order', Bezeichnung).
    """
    if order_limit_g is None:
        if recipe.limit_g is None:
            return None, None, None
        return recipe.limit_g, "recipe", recipe.limit_label
    if recipe.limit_g is not None and order_limit_g > recipe.limit_g:
        raise ValidationError(
            f"Obergrenze darf höchstens {engine.fmt_int(recipe.limit_g)} g sein "
            f"(Chargengröße „{recipe.limit_label}“).", field="order_limit", code="order_limit_too_large")
    return order_limit_g, "order", None


def _resolve(conn: sqlite3.Connection, recipe: engine.Recipe, req: CalcRequest) -> tuple[engine.Order, dict]:
    """Eingabe der Vorwahl → Auftrag für den Rechenkern (Abschnitt 4.2 und 17.2 bis 17.7)."""
    extra: dict = {"input_unit": req.input_unit or None, "input_value": req.input_value}
    parts: list[dict] = []
    pieces_like: list[bool] = []
    factor = None
    basis_type = req.basis_type

    if basis_type in ("total", "flour_total"):
        basis = Basis(basis_type, req.value_g)
        if basis_type == "total":
            parts.append({"kind": "total", "label": "Gesamtteig", "g": req.value_g})
            pieces_like.append(False)
    elif basis_type == "raw_material":
        basis = Basis("raw_material", req.value_g, req.raw_material_id, req.item_position)
    elif basis_type == "factor":
        basis = Basis("factor", 1, factor=Fraction(req.factor_hundredths, 100))
        pieces_like.append(False)
    else:
        target = 0
        if basis_type == "batch_size":
            size = _batch_size(conn, recipe.id, req.batch_size_id)
            if req.input_unit:
                check_unit("batch_size", req.input_unit)
                if (req.input_unit == "pcs") != (size["kind"] == "pieces"):
                    raise ValidationError("Die Einheit passt nicht zu dieser Chargengröße.", field="input_unit",
                                          code="unit_invalid")
            extra["batch_size"] = size
            sizes = [(size, 1)]
        else:
            sizes = [(_batch_size(conn, recipe.id, sid, field="batch_sizes"), count) for sid, count in req.batch_sizes]
            if sizes:
                extra["batch_sizes"] = [{**size, "count": count} for size, count in sizes]
        if basis_type == "combined" and req.total_part_g:
            parts.append({"kind": "total", "label": "Gesamtteig", "g": req.total_part_g})
            pieces_like.append(False)
            target += req.total_part_g
        if req.pieces:
            pieces = _piece_weights(recipe, req.pieces)
            extra["pieces"] = pieces
            for p in pieces:
                g = p["weight_g"] * p["count"]
                parts.append({"kind": "pieces", "label": p["label"], "count": p["count"], "weight_g": p["weight_g"],
                              "g": g})
                pieces_like.append(True)
                target += g
        for size, count in sizes:
            g = size["weight_g"] * count
            parts.append({"kind": "batch_size", "label": size["label"], "count": count, "weight_g": size["weight_g"],
                          "g": g, "batch_size_id": size["id"]})
            pieces_like.append(size["kind"] == "pieces")
            target += g
        if basis_type == "combined" and req.factor_hundredths:
            factor = Fraction(req.factor_hundredths, 100)
            pieces_like.append(False)
        basis = Basis(basis_type, max(target, 1))

    limit_g, limit_source, limit_label = _limit(recipe, req.order_limit_g)
    order = engine.Order(
        basis=basis, parts=tuple(parts), factor=factor,
        pieces_only=bool(pieces_like) and all(pieces_like),
        limit_g=limit_g, limit_source=limit_source, limit_label=limit_label,
        split=req.split, dough_count=req.dough_count, split_mode=req.split_mode, sub_modes=dict(req.sub_modes))
    if basis_type == "factor":
        extra["factor_input"] = req.factor_hundredths
    return order, extra


def calculate(conn: sqlite3.Connection, payload) -> dict:
    """Berechnung nach Abschnitt 4 und 17 (``POST /api/v1/calculation``, Prüfseite, später Vorwahl)."""
    req = payload if isinstance(payload, CalcRequest) else validate_request(payload)
    recipe = load_recipe(conn, req.recipe_id, version_no=req.version_no)
    order, extra = _resolve(conn, recipe, req)
    result = engine.calculate_order(recipe, order, overrides=req.overrides)
    extra.pop("factor_input", None)
    result["basis"].update(extra)
    return result


# ---------------------------------------------------------------------------
# Für den Wiegeablauf (Modul 09)
# ---------------------------------------------------------------------------

def _whole_or_none(value, field_name: str, label: str, minimum: int = 1, maximum: int | None = None):
    return whole_number(value, field_name, label, minimum=minimum, maximum=maximum, required=False)


def validate_basis(conn: sqlite3.Connection, recipe_id: int, order: dict) -> dict:
    """Prüft die Bezugsangaben eines Auftrags vor dem Speichern (Befund B4, P06-1 bis P06-18).

    ``order`` enthält die Spalten von ``production_order`` (``basis_type``, ``basis_value`` in
    Gramm, ``basis_input_unit``, ``basis_raw_material_id``, ``basis_item_position``,
    ``batch_size_id``, ``total_part_g``, ``factor_hundredths``, ``limit_g``, ``limit_source``,
    ``split_mode``, ``dough_count``), dazu ``pieces`` (→ ``order_piece``) als Liste
    ``{piece_weight_id, count}``, ``batch_sizes`` (→ ``order_batch_size``) als Liste
    ``{batch_size_id, count}``, ``doughs`` (→ ``order_dough``) als Liste der Sollgrößen je Teig,
    optional ``recipe_version_id`` und ``overrides`` ``{position: amount_g}``.

    Wirft ``ValidationError`` mit Feld. Gibt das Rechenergebnis zurück (wie ``calculate``), damit
    Modul 09 Teige und Unterrezept-Aufträge daraus anlegen kann.
    """
    basis_type = order.get("basis_type")
    if basis_type not in engine.BASIS_TYPES:
        raise ValidationError("Bitte eine Bezugsgröße wählen.", field="basis_type", code="basis_type")
    sole = basis_type in engine.SOLE_BASIS_TYPES
    # Eingabe höchstens 1 000 kg (P06-2); der Bedarf aus Stückzahlen, Faktor oder Kombination darf darüber liegen,
    # wenn geteilt wird – je Teig prüft dann die Rechnung (17.10)
    value = whole_number(order.get("basis_value"), "basis_value", "Die Menge", minimum=1,
                         maximum=engine.MAX_DOUGH_G if basis_type in ("total", "flour_total", "raw_material")
                         else engine.MAX_DOUGH_G * engine.MAX_DOUGHS)
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
    if basis_type not in ("pieces", "combined") and order.get("pieces"):
        raise ValidationError("Stückzahlen gibt es nur bei der Bezugsgröße „Stückzahlen“ oder „kombiniert“.",
                              field="pieces", code="basis_fields")
    if basis_type != "combined" and order.get("batch_sizes"):
        raise ValidationError("Mehrere Chargengrößen gibt es nur bei der Bezugsart „kombiniert“.",
                              field="batch_sizes", code="basis_fields")
    total_part = _whole_or_none(order.get("total_part_g"), "total_part_g", "Der Gesamtteig-Anteil",
                                maximum=engine.MAX_DOUGH_G)
    if total_part is not None and basis_type not in ("total", "combined"):
        raise ValidationError("Ein Gesamtteig-Anteil gibt es nur bei „Gesamtteig“ oder „kombiniert“.",
                              field="total_part_g", code="basis_fields")
    if basis_type == "total" and total_part is not None and total_part != value:
        raise ValidationError("Der Gesamtteig-Anteil ergibt nicht die gespeicherte Menge.", field="total_part_g",
                              code="demand_value")
    factor_h = _whole_or_none(order.get("factor_hundredths"), "factor_hundredths", "Der Faktor",
                              maximum=models.MAX_FACTOR_HUNDREDTHS)
    if factor_h is not None and basis_type not in ("factor", "combined"):
        raise ValidationError("Einen Faktor gibt es nur bei „Faktor“ oder „kombiniert“.",
                              field="factor_hundredths", code="basis_fields")
    if basis_type == "factor" and factor_h is None:
        raise ValidationError("Bitte einen Faktor zwischen 0,01 und 100 eingeben.", field="factor_hundredths",
                              code="factor_invalid")

    recipe = load_recipe(conn, recipe_id, version_id=order.get("recipe_version_id"))

    # Stückzahlen und Chargengrößen aus den Listen (B4: gehören zum Rezept)
    entries = order.get("pieces") or []
    pieces = tuple(
        (whole_number(p.get("piece_weight_id"), "pieces", "das Stückgewicht", minimum=1),
         whole_number(p.get("count"), "pieces", "Die Stückzahl", minimum=1, maximum=MAX_PIECES))
        for p in entries if isinstance(p, dict))
    if len(pieces) != len(entries) or len({pid for pid, _ in pieces}) != len(pieces):
        raise ValidationError("Ungültige Stückzahlen.", field="pieces", code="pieces_invalid")
    if basis_type == "pieces":
        found = _piece_weights(recipe, pieces)
        if not found:
            raise ValidationError("Bitte mindestens eine Stückzahl eingeben.", field="pieces", code="pieces_missing")
        if sum(p["weight_g"] * p["count"] for p in found) != value:
            raise ValidationError("Die Stückzahlen ergeben nicht die gespeicherte Menge.", field="basis_value",
                                  code="pieces_sum")
    size_entries = order.get("batch_sizes") or []
    sizes = tuple(
        (whole_number(b.get("batch_size_id"), "batch_sizes", "die Chargengröße", minimum=1),
         whole_number(b.get("count"), "batch_sizes", "die Anzahl", minimum=1, maximum=models.MAX_BATCH_COUNT))
        for b in size_entries if isinstance(b, dict))
    if len(sizes) != len(size_entries) or len({sid for sid, _ in sizes}) != len(sizes):
        raise ValidationError("Ungültige Chargengrößen.", field="batch_sizes", code="batch_sizes_invalid")
    batch_size_id = None
    if basis_type == "batch_size":
        batch_size_id = whole_number(order.get("batch_size_id"), "batch_size_id", "eine Chargengröße", minimum=1)
        size = _batch_size(conn, recipe_id, batch_size_id)
        if (unit == "pcs") != (size["kind"] == "pieces"):
            raise ValidationError("Die Einheit passt nicht zu dieser Chargengröße.", field="basis_input_unit",
                                  code="unit_invalid")
        if size["weight_g"] != value:
            raise ValidationError("Die Chargengröße ergibt nicht die gespeicherte Menge.", field="basis_value",
                                  code="batch_size_value")
    if basis_type == "combined" and not (total_part or factor_h or pieces or sizes):
        raise ValidationError("Bitte mindestens eine Angabe machen.", field="basis_type", code="demand_missing")

    # Obergrenze (R06-31, K06-6)
    limit_g = _whole_or_none(order.get("limit_g"), "limit_g", "Die Obergrenze", maximum=engine.MAX_DOUGH_G)
    limit_source = order.get("limit_source")
    if (limit_g is None) != (limit_source is None) or limit_source not in (None, "recipe", "order"):
        raise ValidationError("Obergrenze und Herkunft gehören zusammen.", field="limit_source", code="limit_invalid")
    if limit_source == "recipe" and limit_g != recipe.limit_g:
        raise ValidationError("Die Obergrenze passt nicht zur aktiven Chargengröße des Rezepts.", field="limit_g",
                              code="limit_mismatch")
    dough_count = whole_number(order.get("dough_count", 1), "dough_count", "Die Anzahl Teige", minimum=1,
                               maximum=engine.MAX_DOUGHS)
    split_mode = order.get("split_mode")
    if dough_count > 1 and split_mode not in engine.SPLIT_MODES:
        raise ValidationError("Bitte „voll auffüllen“ oder „gleichmäßig“ wählen.", field="split_mode",
                              code="split_mode_invalid")

    req = CalcRequest(
        recipe_id=recipe_id, basis_type=basis_type, input_unit=unit if basis_type != "combined" else "g",
        value_g=value if basis_type in ("total", "flour_total", "raw_material") else None,
        pieces=pieces, batch_size_id=batch_size_id, raw_material_id=raw_material_id, item_position=item_position,
        overrides=dict(order.get("overrides") or {}), total_part_g=total_part,
        factor_hundredths=factor_h, batch_sizes=sizes,
        order_limit_g=limit_g if limit_source == "order" else None,
        split=(dough_count > 1) if sole else None, dough_count=dough_count, split_mode=split_mode or "fill")
    if limit_source is None and recipe.limit_g is not None:
        raise ValidationError("Das Rezept hat eine aktive Chargengröße als Obergrenze; bitte mit Obergrenze speichern.",
                              field="limit_g", code="limit_missing")
    built, _extra = _resolve(conn, recipe, req)
    result = engine.calculate_order(recipe, built, overrides=req.overrides or None)

    if basis_type in ("combined", "factor") and result["demand"]["target_g"] != value:
        raise ValidationError("Die Angaben ergeben nicht die gespeicherte Menge.", field="basis_value",
                              code="demand_value")
    planned = [d["target_g"] for d in result["doughs"]]
    if len(planned) != dough_count:
        raise ValidationError("Die Anzahl Teige passt nicht zur Aufteilung.", field="dough_count",
                              code="dough_count_mismatch")
    doughs = order.get("doughs")
    if doughs is not None and list(doughs) != planned:
        raise ValidationError("Die Teige passen nicht zur Aufteilung.", field="doughs", code="doughs_mismatch")
    return result


def _single_basis(row) -> Basis:
    """Bezugsgröße eines Auftrags mit einem Teig aus den gespeicherten Spalten."""
    if row["basis_type"] == "factor":
        return Basis("factor", row["basis_value"], factor=Fraction(row["factor_hundredths"], 100))
    return Basis(row["basis_type"], row["basis_value"], row["basis_raw_material_id"], row["basis_item_position"])


def _dough_result(conn: sqlite3.Connection, row, recipe: engine.Recipe, overrides: dict, dough_index: int | None):
    """Rechnung eines Teigs: bei mehreren Teigen mit dessen Sollgröße (order_dough), sonst mit der Bezugsart."""
    count = row["dough_count"]
    if count > 1:
        if dough_index is None:
            raise ValidationError("Der Auftrag hat mehrere Teige – bitte den Teig angeben.", field="dough_index",
                                  code="dough_index_missing")
        dough = conn.execute("SELECT target_g FROM order_dough WHERE order_id = ? AND dough_index = ?",
                             (row["id"], dough_index)).fetchone()
        if dough is None:
            raise ValidationError(f"Teig {dough_index} gibt es im Auftrag nicht.", field="dough_index",
                                  code="dough_index_invalid")
        basis = Basis("total", dough["target_g"])
    else:
        if dough_index not in (None, 1):
            raise ValidationError(f"Teig {dough_index} gibt es im Auftrag nicht.", field="dough_index",
                                  code="dough_index_invalid")
        basis = _single_basis(row)
    return engine.calculate(recipe, basis, overrides=overrides or None, piece_hints=False)


def _order_row(conn: sqlite3.Connection, order_id: int):
    row = conn.execute("SELECT * FROM production_order WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise NotFoundError("Auftrag nicht gefunden.", code="not_found")
    overrides = {r["item_position"]: r["amount_g"] for r in conn.execute(
        "SELECT item_position, amount_g FROM order_item_override WHERE order_id = ?", (order_id,))}
    return row, overrides


def build_batch_items(conn: sqlite3.Connection, order_id: int, version_id: int,
                      dough_index: int | None = None) -> list[dict]:
    """Werte für ``batch_item`` eines Teigs, nur aus der fixierten Version des Auftrags (Befund B2).

    Bei Aufträgen mit mehreren Teigen gilt die Sollgröße des Teigs ``dough_index`` aus ``order_dough``
    (R06-42); bei einem Teig die Bezugsart des Auftrags wie bisher.

    Jede Zeile enthält die Spalten ``position``, ``recipe_item_id``, ``item_type``,
    ``raw_material_id``, ``raw_material_number``, ``raw_material_name`` (Kopien), ``sub_order_id``
    (leer; Modul 09 legt den Unterrezept-Auftrag an, ``sub_order_targets``),
    ``target_g``, ``tolerance_g``, ``unit_size_g``, ``unit_label``, ``units_target``, ``rest_target_g``.
    Zusätzlich (keine Spalten): ``kind`` (raw_material, hand, sub_recipe), ``is_hand_ack``,
    ``sub_recipe_id``, ``station_name``.
    """
    row, overrides = _order_row(conn, order_id)
    if row["recipe_version_id"] is None:
        raise ValidationError("Die Rezeptversion des Auftrags ist noch nicht fixiert.", field="version_id",
                              code="version_not_fixed")
    if row["recipe_version_id"] != version_id:
        raise ValidationError("Die Version gehört nicht zum Auftrag.", field="version_id", code="version_mismatch")
    recipe = load_recipe(conn, row["recipe_id"], version_id=version_id)
    result = _dough_result(conn, row, recipe, overrides, dough_index)

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


def sub_order_targets(conn: sqlite3.Connection, order_id: int, sub_modes: dict[int, str] | None = None) -> list[dict]:
    """Gesamtteig je Unterrezept-Auftrag (R06-44 bis R06-49, docs/berechnung.md 17.6).

    ``sub_modes``: Position der Unterrezeptzeile → ``per_dough`` (Vorgabe) oder ``all``; bei einem
    Teig gibt es immer einen Unterrezept-Auftrag. Liefert je Unterrezept-Auftrag ``position``,
    ``sub_recipe_id``, ``mode``, ``dough_index`` (leer = für alle, Spalte ``parent_dough_index``)
    und ``target_g`` (Gesamtteig, R06-5). Gerechnet wird mit der fixierten Version, sonst der aktuellen.
    """
    row, overrides = _order_row(conn, order_id)
    recipe = load_recipe(conn, row["recipe_id"], version_id=row["recipe_version_id"])
    sub_modes = dict(sub_modes or {})
    lines = [line for line in recipe.lines if line.sub is not None]
    positions = {line.position for line in lines}
    for position, mode in sub_modes.items():
        if position not in positions:
            raise ValidationError(f"Zeile {position} ist kein Unterrezept.", field="sub_modes",
                                  code="sub_mode_position")
        if mode not in engine.SUB_MODES:
            raise ValidationError("Bitte „je Teig“ oder „für alle“ wählen.", field="sub_modes", code="sub_mode_invalid")
    count = row["dough_count"]
    results = [_dough_result(conn, row, recipe, overrides, index if count > 1 else None)
               for index in range(1, count + 1)]
    targets = []
    for line in lines:
        mode = sub_modes.get(line.position, "per_dough") if count > 1 else "all"
        per_dough = [next(i["target_g"] for i in r["items"] if i["position"] == line.position) for r in results]
        base = {"position": line.position, "sub_recipe_id": line.sub.id, "mode": mode}
        if mode == "per_dough":
            targets += [{**base, "dough_index": i, "target_g": t} for i, t in enumerate(per_dough, start=1)]
        else:
            targets.append({**base, "dough_index": None, "target_g": sum(per_dough)})
    return targets
