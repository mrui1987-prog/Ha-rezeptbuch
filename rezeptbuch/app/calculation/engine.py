"""Rechenkern der Rezeptberechnung (Modul 06, docs/berechnung.md Abschnitt 4 bis 6).

Dieses Modul kennt **keine Datenbank**. Es bekommt ein Rezept als Baum aus Datenobjekten
(``Recipe`` → ``Line`` → ``Material`` bzw. Unterrezept) und eine Bezugsgröße (``Basis``)
und liefert das Arbeitsrezept als Wörterbuch (``CalcResult``, Abschnitt 6).

Grundsätze:

* Gerechnet wird mit exakten Brüchen (``fractions.Fraction``), gerundet nur einmal je Zeile.
* Jede Zeile wird auf das nächste ganze Gramm **aufgerundet** (R06-1), 0 g bleibt 0 g (R06-2).
* Unterrezepte werden mit ihrer gerundeten Zeilenmenge als Gesamtteig gerechnet (R06-5).
* Prozent-Toleranz: abgerundet auf ganze Gramm, mindestens 1 g (R06-8).
* Anteil und Bäckerprozent aus dem Grundrezept, bezogen auf den Hauptteig (R06-13 bis R06-16).
* Zusammenfassung: jeder Rohstoff einmal über alle Ebenen, dazu die Mehlmischung (R06-53 bis R06-58).

Die Funktionen ``tolerance_g`` und ``split_units`` sind auch für den Wiegeablauf (Modul 09) gedacht.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from fractions import Fraction

from ..errors import ValidationError

# Höchstens 1 000 kg je Teig (wie die Rezeptzeilen in Modul 05, P06-2)
MAX_DOUGH_G = 1_000_000
# Höchstens 10 Ebenen Unterrezepte (P06-9)
MAX_DEPTH = 10
# Hinweis H06-4 ab dieser Erhöhung durch das Aufrunden (Prozent)
ROUNDING_WARN_PERCENT = 5

BASIS_TYPES = ("total", "pieces", "batch_size", "raw_material", "flour_total")


# ---------------------------------------------------------------------------
# Datenobjekte (Eingabe)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Material:
    """Rohstoff, wie ihn die Rechnung braucht."""

    id: int
    number: int
    name: str
    type: str = "standard"               # 'standard' oder 'flour'
    tolerance_unit: str = "g"            # 'g' oder 'percent'
    tolerance_value: int = 0             # Gramm bzw. Zehntelprozent (25 = 2,5 %)
    display_name: str | None = None      # Kurzname für die Station (M03-3b)
    unit_size_g: int | None = None       # Gebinde-/Stückgröße (M02-2c)
    unit_label: str | None = None
    archived: bool = False

    @property
    def station_name(self) -> str:
        return self.display_name or self.name


@dataclass(frozen=True)
class Line:
    """Rezeptzeile: entweder Rohstoff (``material``) oder Unterrezept (``sub``)."""

    position: int
    amount_g: int
    material: Material | None = None
    sub: "Recipe | None" = None
    tolerance_unit: str | None = None    # Überschreibung der Rohstoff-Toleranz (R1, R05-11)
    tolerance_value: int | None = None
    step_no: int | None = None
    step_name: str | None = None
    needs_review: bool = False
    item_id: int | None = None           # recipe_item.id (für die Chargenzeilen, B2)


@dataclass(frozen=True)
class PieceWeight:
    id: int | None
    label: str
    weight_g: int


@dataclass(frozen=True)
class Recipe:
    """Eine Rezeptversion mit ihren Zeilen (Unterrezepte als eigene ``Recipe``)."""

    id: int
    number: int
    name: str
    version_no: int = 1
    lines: tuple[Line, ...] = ()
    version_id: int | None = None
    knead_slow_min: int | None = None
    knead_fast_min: int | None = None
    piece_weights: tuple[PieceWeight, ...] = ()
    locked: bool = False
    archived: bool = False
    current: bool = True                 # aktuelle Version des Rezepts?


@dataclass(frozen=True)
class Basis:
    """Bezugsgröße je Teig, bereits in ganzen Gramm (Umrechnung kg/l/Stück im Service)."""

    type: str
    target_g: int
    raw_material_id: int | None = None   # nur bei 'raw_material'
    item_position: int | None = None     # Leitrohstoff je Zeile (K06-1); leer = „gesamt“


# ---------------------------------------------------------------------------
# Kleine Rechenhilfen
# ---------------------------------------------------------------------------

def round_up_g(value: Fraction) -> int:
    """R06-1/R06-2: auf das nächste ganze Gramm aufrunden; 0 bleibt 0."""
    return math.ceil(value) if value > 0 else 0


def round_half_up(value: Fraction) -> int:
    """Kaufmännisch runden (nur für Anzeigewerte, nie für Sollmengen)."""
    return math.floor(value + Fraction(1, 2))


def tenths(value: Fraction) -> int:
    """Prozentwert als ganze Zahl in Zehnteln, kaufmännisch gerundet (176 = 17,6 %)."""
    return round_half_up(value * 10)


def decimal_text(value: Fraction, places: int = 3) -> str:
    """Bruch als Dezimaltext mit Punkt, kaufmännisch gerundet, ohne Nullen am Ende („312.125“)."""
    scale = 10 ** places
    scaled = round_half_up(abs(value) * scale)
    whole, rest = divmod(scaled, scale)
    sign = "-" if value < 0 and scaled else ""
    if rest == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{rest:0{places}d}".rstrip("0")


def fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def tolerance_g(target_g: int, unit: str, value: int) -> int:
    """Toleranz ± in Gramm (R06-7, R06-8, M03-4, M06-5).

    * Gramm: Wert unverändert, 0 g = Sollhandzugabe (nur quittieren).
    * Prozent (``value`` in Zehntelprozent): Sollmenge × Prozent, auf ganze Gramm
      abgerundet, **mindestens 1 g**; 0 % wird also mit ±1 g gewogen.
    * Sollmenge 0 g (Handzugabe nach Bedarf): keine Toleranz (R06-10).
    """
    if target_g <= 0:
        return 0
    if unit == "g":
        return int(value)
    if unit == "percent":
        return max(1, (target_g * int(value)) // 1000)
    raise ValueError(f"Unbekannte Toleranzeinheit: {unit!r}")


def split_units(target_g: int, unit_size_g: int | None) -> tuple[int, int]:
    """R06-11: ganze Gebinde/Stück (abgerundet) und Rest in Gramm.

    580 g, Ei 55 g → (10, 30); 30 000 g, Sack 25 000 g → (1, 5 000); ohne Größe → (0, Sollmenge).
    """
    if not unit_size_g or target_g <= 0:
        return 0, target_g
    count = target_g // unit_size_g
    return count, target_g - count * unit_size_g


def effective_tolerance(line: Line) -> tuple[str, int] | None:
    """Toleranz der Zeile, sonst des Rohstoffs (R06-6); Unterrezepte haben keine (R06-10)."""
    if line.material is None:
        return None
    if line.tolerance_unit is not None:
        return line.tolerance_unit, int(line.tolerance_value or 0)
    return line.material.tolerance_unit, int(line.material.tolerance_value)


# ---------------------------------------------------------------------------
# Grundgrößen (Abschnitt 4.1)
# ---------------------------------------------------------------------------

def total_g(recipe: Recipe) -> Fraction:
    """Gesamtgewicht G: Summe aller Zeilen (Unterrezepte mit ihrer Menge, R05-27)."""
    return Fraction(sum(line.amount_g for line in recipe.lines))


def _sub_ratio(line: Line, part) -> Fraction:
    sub_total = total_g(line.sub)
    if sub_total == 0:
        raise ValidationError(f"Unterrezept „{line.sub.name}“ enthält keine Mengen.",
                              field="recipe_id", code="sub_recipe_empty")
    return Fraction(line.amount_g) * part(line.sub) / sub_total


def flour_g(recipe: Recipe) -> Fraction:
    """Mehl M inklusive Unterrezepten über alle Ebenen (M06-2)."""
    result = Fraction(0)
    for line in recipe.lines:
        if line.sub is not None:
            result += _sub_ratio(line, flour_g)
        elif line.material is not None and line.material.type == "flour":
            result += line.amount_g
    return result


def material_g(recipe: Recipe, material_id: int) -> Fraction:
    """Menge eines Rohstoffs R(x) inklusive Unterrezepten (Leitrohstoff „gesamt“, K06-1)."""
    result = Fraction(0)
    for line in recipe.lines:
        if line.sub is not None:
            result += _sub_ratio(line, lambda sub: material_g(sub, material_id))
        elif line.material is not None and line.material.id == material_id:
            result += line.amount_g
    return result


def check_tree(recipe: Recipe, _path: tuple = ()) -> None:
    """Kreis, Tiefe (P06-9) und leere Unterrezepte prüfen, bevor gerechnet wird."""
    path = _path + ((recipe.id, recipe.name),)
    if len(path) > MAX_DEPTH + 1:
        raise ValidationError("Unterrezepte sind zu tief verschachtelt (höchstens 10 Ebenen).",
                              field="recipe_id", code="sub_recipe_too_deep")
    for line in recipe.lines:
        if line.sub is None:
            continue
        if any(rid == line.sub.id for rid, _ in path):
            names = " → ".join(name for _, name in path + ((line.sub.id, line.sub.name),))
            raise ValidationError(f"Unterrezepte bilden einen Kreis: {names}.",
                                  field="recipe_id", code="sub_recipe_cycle")
        if total_g(line.sub) == 0:
            raise ValidationError(f"Unterrezept „{line.sub.name}“ enthält keine Mengen.",
                                  field="recipe_id", code="sub_recipe_empty")
        check_tree(line.sub, path)


# ---------------------------------------------------------------------------
# Mengenänderungen im Auftrag (order_item_override)
# ---------------------------------------------------------------------------

def apply_overrides(recipe: Recipe, overrides: dict[int, int] | None) -> tuple[Recipe, set[int]]:
    """Ersetzt die Grundrezept-Menge einzelner Zeilen des Hauptrezepts vor der Rechnung (Abschnitt 4.1)."""
    if not overrides:
        return recipe, set()
    index = {line.position: i for i, line in enumerate(recipe.lines)}
    lines = list(recipe.lines)
    for position, amount in overrides.items():
        if position not in index:
            raise ValidationError(f"Zeile {position} gibt es im Rezept nicht.",
                                  field="overrides", code="override_position")
        line = lines[index[position]]
        if line.sub is not None and amount <= 0:
            raise ValidationError(f"Zeile {position} ist ein Unterrezept und braucht eine Menge größer als 0.",
                                  field="overrides", code="override_amount")
        lines[index[position]] = replace(line, amount_g=amount)
    return replace(recipe, lines=tuple(lines)), set(overrides)


# ---------------------------------------------------------------------------
# Faktor je Bezugsgröße (Abschnitt 4.2)
# ---------------------------------------------------------------------------

def _line_name(line: Line) -> str:
    if line.sub is not None:
        return line.sub.name
    return line.material.station_name if line.material else f"Zeile {line.position}"


def factor_for(recipe: Recipe, basis: Basis) -> Fraction:
    """Faktor f, mit dem jede Grundrezept-Menge malgenommen wird (P06-3 bis P06-5)."""
    if basis.type not in BASIS_TYPES:
        raise ValidationError("Unbekannte Bezugsgröße.", field="basis_type", code="basis_type")
    if basis.target_g <= 0:
        raise ValidationError("Bitte eine Menge größer als 0 eingeben.", field="value", code="value_invalid")
    total = total_g(recipe)
    if total == 0:
        raise ValidationError("Rezept enthält keine Mengen.", field="recipe_id", code="recipe_empty")
    target = Fraction(basis.target_g)

    if basis.type in ("total", "pieces", "batch_size"):
        return target / total

    if basis.type == "flour_total":
        flour = flour_g(recipe)
        if flour == 0:
            raise ValidationError("Rezept enthält kein Mehl.", field="basis_type", code="no_flour")
        return target / flour

    # Leitrohstoff (K06-1)
    if basis.raw_material_id is None:
        raise ValidationError("Bitte einen Leitrohstoff wählen.", field="raw_material_id",
                              code="raw_material_missing")
    if basis.item_position is not None:
        line = next((l for l in recipe.lines if l.position == basis.item_position), None)
        if line is None or line.material is None or line.material.id != basis.raw_material_id:
            raise ValidationError("Diese Zeile gehört nicht zum gewählten Rohstoff.",
                                  field="item_position", code="basis_line_invalid")
        if line.amount_g == 0:
            raise ValidationError("Diese Zeile hat keine Menge (Handzugabe) und kann nicht Leitrohstoff sein.",
                                  field="item_position", code="basis_line_invalid")
        return target / line.amount_g
    amount = material_g(recipe, basis.raw_material_id)
    if amount == 0:
        raise ValidationError("Rohstoff kommt im Rezept nicht vor.", field="raw_material_id",
                              code="raw_material_not_in_recipe")
    return target / amount


# ---------------------------------------------------------------------------
# Berechnung (Abschnitt 4.3 bis 4.8)
# ---------------------------------------------------------------------------

@dataclass
class _Context:
    main_total: Fraction
    main_flour: Fraction
    warnings: list[dict] = field(default_factory=list)
    material_sums: dict[int, int] = field(default_factory=dict)
    # Zusammenfassung (R06-53 bis R06-57): Rohstoff-ID → Summen über alle Ebenen, in Reihenfolge des ersten Vorkommens
    summary: dict[int, dict] = field(default_factory=dict)
    _seen: set = field(default_factory=set)

    def warn(self, code: str, text: str, position: int | None = None, key=None) -> None:
        marker = (code, key if key is not None else text)
        if marker in self._seen:
            return
        self._seen.add(marker)
        entry = {"code": code, "text": text}
        if position is not None:
            entry["position"] = position
        self.warnings.append(entry)


def _knead(recipe: Recipe) -> str | None:
    if recipe.knead_slow_min is None and recipe.knead_fast_min is None:
        return None
    return f"{recipe.knead_slow_min or 0}+{recipe.knead_fast_min or 0}"


def _recipe_info(recipe: Recipe) -> dict:
    return {
        "id": recipe.id,
        "number": recipe.number,
        "name": recipe.name,
        "version_no": recipe.version_no,
        "current_version": recipe.current,
        "locked": recipe.locked,
        "archived": recipe.archived,
    }


def _fmt_g(value: Fraction) -> str:
    """Gramm für Hinweistexte mit Komma („1,3 g“)."""
    return decimal_text(value, 1).replace(".", ",") + " g"


def _lines(recipe: Recipe, f: Fraction, scale: Fraction, ctx: _Context, top_position: int | None,
           path: str, overridden: set[int]) -> list[dict]:
    items = []
    for line in recipe.lines:
        position = top_position if top_position is not None else line.position
        name = _line_name(line)
        label = f"{path}{name}"
        exact = line.amount_g * f
        target = round_up_g(exact)
        effective = line.amount_g * scale          # Anteil am Grundrezept des Hauptteigs (R06-15, R06-16)
        item = {
            "position": line.position,
            "step_no": line.step_no,
            "step_name": line.step_name,
            "recipe_item_id": line.item_id,
            "base_g": line.amount_g,
            "overridden": top_position is None and line.position in overridden,
            "exact_g": decimal_text(exact),
            "target_g": target,
            "share_tenths": tenths(effective / ctx.main_total * 100),
            "baker_tenths": tenths(effective / ctx.main_flour * 100) if ctx.main_flour > 0 else None,
            "needs_review": line.needs_review,
            "raw_material": None,
            "sub_recipe": None,
            "tolerance": None,
            "units": None,
            "sub": None,
        }
        if line.needs_review:
            ctx.warn("needs_review", f"Zeile mit „*“ prüfen: {label}", position, key=(path, line.position))
        if exact > 0 and (target - exact) * 100 > exact * ROUNDING_WARN_PERCENT:
            ctx.warn("rounding_large",
                     f"{label}: Aufrunden auf {target} g statt {_fmt_g(exact)} "
                     f"(+{round_half_up((target - exact) / exact * 100)} %)", position, key=(path, line.position))

        if line.sub is not None:
            sub = line.sub
            sub_total = total_g(sub)
            sub_f = Fraction(target) / sub_total     # R06-5: mit der gerundeten Zeilenmenge als Gesamtteig
            sub_scale = scale * line.amount_g / sub_total
            sub_items = _lines(sub, sub_f, sub_scale, ctx, position, f"{label} › ", set())
            item["kind"] = "sub_recipe"
            item["sub_recipe"] = {"id": sub.id, "number": sub.number, "name": sub.name,
                                  "version_no": sub.version_no, "locked": sub.locked, "archived": sub.archived}
            sub_flour = flour_g(sub) * sub_f
            item["sub"] = {
                "recipe": _recipe_info(sub),
                "totals": {
                    "target_g": target,
                    "rounded_sum_g": sum(i["target_g"] for i in sub_items),
                    "flour_g": round_half_up(sub_flour),
                    "flour_exact": decimal_text(sub_flour),
                    "knead_slow_min": sub.knead_slow_min,
                    "knead_fast_min": sub.knead_fast_min,
                    "knead": _knead(sub),
                },
                "items": sub_items,
            }
            if sub.archived:
                ctx.warn("archived", f"Unterrezept „{sub.name}“ ist archiviert.", position, key=("sub", sub.id))
        else:
            material = line.material
            item["kind"] = "hand" if line.amount_g == 0 else "raw_material"
            item["raw_material"] = {
                "id": material.id, "number": material.number, "name": material.name,
                "display_name": material.display_name, "station_name": material.station_name,
                "type": material.type, "archived": material.archived,
            }
            ctx.material_sums[material.id] = ctx.material_sums.get(material.id, 0) + target
            entry = ctx.summary.setdefault(material.id, {
                "material": material, "target_g": 0, "exact": Fraction(0), "base": Fraction(0),
                "weighed": False, "hand": False})
            entry["target_g"] += target
            entry["exact"] += exact
            entry["base"] += effective
            if line.amount_g > 0:
                entry["weighed"] = True
            else:
                entry["hand"] = True
            if material.archived:
                ctx.warn("archived", f"Rohstoff „{material.name}“ ist archiviert.", position,
                         key=("rm", material.id))
            if line.amount_g > 0:
                unit, value = effective_tolerance(line)
                tol = tolerance_g(target, unit, value)
                item["tolerance"] = {
                    "unit": unit,
                    "value": value if unit == "g" else value / 10,
                    "tolerance_g": tol,
                    # 0 g Toleranz = Sollhandzugabe: nur quittieren, nicht wiegen (M05-13b)
                    "is_hand_ack": unit == "g" and value == 0,
                }
                if unit == "percent" and value == 0:
                    ctx.warn("tolerance_zero_percent",
                             f"„{material.name}“ hat Toleranz 0 % und wird mit ±1 g gewogen.", position,
                             key=("tol0", material.id))
                if material.unit_size_g:
                    count, rest = split_units(target, material.unit_size_g)
                    item["units"] = {"size_g": material.unit_size_g, "label": material.unit_label,
                                     "count": count, "rest_g": rest}
        items.append(item)
    return items


def _summary(ctx: _Context) -> tuple[list[dict], list[dict]]:
    """Zusammenfassung und Mehlmischung (VC06-f, docs/berechnung.md 17.8).

    * Jeder Rohstoff einmal, Menge = Summe der **gerundeten** Zeilenmengen aller Ebenen, also das,
      was tatsächlich gewogen wird (R06-53, R06-54, K06-10); dazu der genaue Wert.
    * Anteil und Bäckerprozent aus dem Grundrezept, bezogen auf den Hauptteig (R06-55).
    * Reihenfolge nach dem ersten Vorkommen; Rohstoffe nur als Handzugabe: „nach Bedarf“ (R06-57).
    * Mehlmischung: Anteil jeder Mehlsorte am Mehl gesamt in Zehntelprozent (R06-56).
    """
    rows, mix = [], []
    for entry in ctx.summary.values():
        material = entry["material"]
        rows.append({
            "raw_material": {
                "id": material.id, "number": material.number, "name": material.name,
                "display_name": material.display_name, "station_name": material.station_name,
                "type": material.type, "archived": material.archived,
            },
            "target_g": entry["target_g"],
            "exact_g": decimal_text(entry["exact"]),
            "hand_only": not entry["weighed"],
            "has_hand": entry["hand"],
            "share_tenths": tenths(entry["base"] / ctx.main_total * 100),
            "baker_tenths": tenths(entry["base"] / ctx.main_flour * 100) if ctx.main_flour > 0 else None,
        })
        if material.type == "flour" and ctx.main_flour > 0 and entry["base"] > 0:
            mix.append({"raw_material_id": material.id, "name": material.name,
                        "station_name": material.station_name,
                        "flour_tenths": tenths(entry["base"] / ctx.main_flour * 100)})
    return rows, mix


def calculate(recipe: Recipe, basis: Basis, *, overrides: dict[int, int] | None = None,
              piece_hints: bool = True) -> dict:
    """Arbeitsrezept für eine Bezugsgröße (je Teig).

    ``piece_hints``: Hinweis „ergibt n Stück“ je Stückgewicht anzeigen (R06-18; nicht bei
    Stückzahlen und Chargengröße „Stück“, dort ist die Anzahl schon bekannt).
    """
    check_tree(recipe)
    recipe, overridden = apply_overrides(recipe, overrides)
    f = factor_for(recipe, basis)
    total = total_g(recipe)
    flour = flour_g(recipe)
    exact_total = total * f
    if exact_total > MAX_DOUGH_G:
        raise ValidationError("Menge zu groß (höchstens 1 000 kg je Teig).", field="value", code="value_too_large")

    ctx = _Context(main_total=total, main_flour=flour)
    items = _lines(recipe, f, Fraction(1), ctx, None, "", overridden)

    # H06-6: Leitrohstoff „gesamt“ – Summe nach dem Aufrunden über der Eingabe
    if basis.type == "raw_material" and basis.item_position is None:
        weighed = ctx.material_sums.get(basis.raw_material_id, 0)
        if weighed > basis.target_g:
            name = next((i["raw_material"]["station_name"] for i in _walk(items)
                         if i["raw_material"] and i["raw_material"]["id"] == basis.raw_material_id), "Leitrohstoff")
            ctx.warn("basis_rounded", f"{name}: {weighed} g statt {basis.target_g} g (Aufrunden mehrerer Zeilen).")
    if recipe.locked:
        ctx.warn("recipe_locked", "Rezept ist gesperrt und erscheint nicht in der Vorwahl.")
    if recipe.archived:
        ctx.warn("recipe_archived", "Rezept ist archiviert und erscheint nicht in der Vorwahl.")

    hints = []
    if piece_hints:
        for pw in recipe.piece_weights:
            # R06-17: auf eine Nachkommastelle abgerundet, nie mehr Stück versprechen als möglich
            hints.append({"id": pw.id, "label": pw.label, "weight_g": pw.weight_g,
                          "count_tenths": math.floor(exact_total * 10 / pw.weight_g)})

    flour_scaled = flour * f
    summary, flour_mix = _summary(ctx)
    return {
        "recipe": _recipe_info(recipe),
        "basis": {
            "type": basis.type,
            "target_g": basis.target_g,
            "raw_material_id": basis.raw_material_id,
            "item_position": basis.item_position,
            "factor": fraction_text(f),
            "factor_text": decimal_text(f, 4),
        },
        "totals": {
            "base_total_g": int(total),
            "base_flour_g": round_half_up(flour),
            "target_g": round_half_up(exact_total),
            "target_exact": decimal_text(exact_total),
            "target_is_exact": exact_total.denominator == 1,
            "rounded_sum_g": sum(i["target_g"] for i in items),
            "flour_g": round_half_up(flour_scaled),
            "flour_exact": decimal_text(flour_scaled),
            "has_flour": flour > 0,
            "knead_slow_min": recipe.knead_slow_min,
            "knead_fast_min": recipe.knead_fast_min,
            "knead": _knead(recipe),
        },
        "piece_hints": hints,
        "items": items,
        "summary": summary,
        "flour_mix": flour_mix,
        "warnings": ctx.warnings,
    }


def _walk(items: list[dict]):
    """Alle Zeilen eines Ergebnisses, Unterrezepte eingeschlossen (Tiefensuche)."""
    for item in items:
        yield item
        if item.get("sub"):
            yield from _walk(item["sub"]["items"])


walk_items = _walk


# ---------------------------------------------------------------------------
# Auswahl für die Vorwahl (Abschnitt 7.1, basis-options)
# ---------------------------------------------------------------------------

def leading_materials(recipe: Recipe) -> list[dict]:
    """Mögliche Leitrohstoffe (K06-1): je Rohstoff „gesamt“ und darunter die Zeilen des Hauptrezepts.

    Reihenfolge nach dem ersten Vorkommen. Die Zeilen werden nur aufgeführt, wenn der Rohstoff
    an mehr als einer Stelle vorkommt (sonst ist „gesamt“ dasselbe wie die eine Zeile).
    """
    order: list[Material] = []
    places: dict[int, int] = {}

    def collect(r: Recipe) -> None:
        for line in r.lines:
            if line.sub is not None:
                collect(line.sub)
            elif line.material is not None and line.amount_g > 0:
                if line.material.id not in places:
                    order.append(line.material)
                    places[line.material.id] = 0
                places[line.material.id] += 1

    collect(recipe)
    result = []
    for material in order:
        amount = material_g(recipe, material.id)
        lines = [{"position": l.position, "step_name": l.step_name, "amount_g": l.amount_g}
                 for l in recipe.lines
                 if l.material is not None and l.material.id == material.id and l.amount_g > 0]
        result.append({
            "raw_material_id": material.id,
            "number": material.number,
            "name": material.name,
            "station_name": material.station_name,
            "amount_g": round_half_up(amount),
            "amount_exact": decimal_text(amount),
            "lines": lines if places[material.id] > 1 else [],
        })
    return result
