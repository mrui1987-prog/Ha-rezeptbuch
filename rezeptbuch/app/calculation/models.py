"""Eingabeprüfung der Berechnungsanfrage (Modul 06, docs/berechnung.md Abschnitt 5 und 7.1).

Wie in Modul 03 und 05 ohne Pydantic: Fehler kommen als ``ValidationError`` mit deutschem
Text und Feldname zurück (Status 400), damit die Seite das Feld markieren kann.
Prüfungen, die die Datenbank brauchen (Stückgewicht/Chargengröße gehört zum Rezept,
Leitrohstoff kommt im Rezept vor), stehen im Service bzw. im Rechenkern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from ..errors import ValidationError
from .engine import BASIS_TYPES, MAX_DOUGH_G

MAX_PIECES = 100_000
INPUT_UNITS = ("g", "kg", "l", "pcs")

# Erlaubte Eingabeeinheiten je Bezugsgröße (P06-8). Chargengröße: je nach Art, siehe Service.
UNITS_FOR_BASIS = {
    "total": ("g", "kg"),
    "flour_total": ("g", "kg"),
    "raw_material": ("g", "kg", "l"),
    "pieces": ("pcs",),
    "batch_size": ("g", "kg", "pcs"),
}
FACTOR_TO_G = {"g": 1, "kg": 1000, "l": 1000}          # 1 l = 1 000 g (M02-1e)

_NUMBER = re.compile(r"^[0-9]+([.,][0-9]+)?$")
_DIGITS = re.compile(r"^[0-9]+$")


@dataclass(frozen=True)
class CalcRequest:
    recipe_id: int
    basis_type: str
    input_unit: str
    version_no: int | None = None
    value_g: int | None = None                 # Gesamtteig, Mehl gesamt, Leitrohstoff (in Gramm)
    input_value: str | None = None             # Eingabe wie getippt, für die Anzeige
    pieces: tuple[tuple[int, int], ...] = ()   # (Stückgewicht-ID, Anzahl)
    batch_size_id: int | None = None
    raw_material_id: int | None = None
    item_position: int | None = None
    overrides: dict[int, int] = field(default_factory=dict)


def whole_number(value, field_name: str, label: str, *, minimum: int = 0, maximum: int | None = None,
                 required: bool = True) -> int | None:
    """Ganze Zahl aus Zahl oder Text (nur Ziffern 0–9, wie B1 in Modul 03)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValidationError(f"Bitte {label} angeben.", field=field_name, code="missing")
        return None
    title = label[:1].upper() + label[1:]
    if isinstance(value, bool):
        raise ValidationError(f"{title} muss eine ganze Zahl sein.", field=field_name, code="not_a_number")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str):
        text = value.strip()
        if not _DIGITS.match(text):
            raise ValidationError(f"{title} muss eine ganze Zahl sein.", field=field_name, code="not_a_number")
        value = int(text)
    if not isinstance(value, int):
        raise ValidationError(f"{title} muss eine ganze Zahl sein.", field=field_name, code="not_a_number")
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" und höchstens {maximum:,}".replace(",", " ") if maximum is not None else ""
        raise ValidationError(f"{title} muss mindestens {minimum}{upper} sein.", field=field_name,
                              code="out_of_range")
    return value


def amount_to_grams(value, unit: str, field_name: str = "value") -> int:
    """Menge in Gramm umrechnen (P06-1, P06-2). Komma oder Punkt als Dezimalzeichen.

    Das Ergebnis muss ganze Gramm ergeben (z. B. 7,5 kg = 7 500 g; 7,5 g ist ungültig).
    """
    if unit not in FACTOR_TO_G:
        raise ValidationError("Für diese Bezugsgröße wird keine Menge eingegeben.", field="input_unit",
                              code="unit_invalid")
    if value is None or isinstance(value, bool):
        raise ValidationError("Bitte eine Menge größer als 0 eingeben.", field=field_name, code="value_invalid")
    if isinstance(value, (int, float)):
        text = repr(value) if isinstance(value, float) else str(value)
    elif isinstance(value, str):
        text = value.strip().replace(" ", "")
    else:
        raise ValidationError("Bitte eine Menge größer als 0 eingeben.", field=field_name, code="value_invalid")
    if not _NUMBER.match(text):
        raise ValidationError("Bitte eine Menge größer als 0 eingeben (nur Ziffern und Komma).",
                              field=field_name, code="value_invalid")
    grams = Decimal(text.replace(",", ".")) * FACTOR_TO_G[unit]
    if grams <= 0:
        raise ValidationError("Bitte eine Menge größer als 0 eingeben.", field=field_name, code="value_invalid")
    if grams != grams.to_integral_value():
        raise ValidationError("Die Menge muss ganze Gramm ergeben.", field=field_name, code="value_not_whole")
    if grams > MAX_DOUGH_G:
        raise ValidationError("Menge zu groß (höchstens 1 000 kg je Teig).", field=field_name,
                              code="value_too_large")
    return int(grams)


def check_unit(basis_type: str, unit: str) -> None:
    """P06-8: Eingabeeinheit passt zur Bezugsgröße (Liter nur beim Leitrohstoff)."""
    if unit not in INPUT_UNITS:
        raise ValidationError("Unbekannte Einheit.", field="input_unit", code="unit_invalid")
    if unit in UNITS_FOR_BASIS[basis_type]:
        return
    if unit == "l":
        text = "Liter nur beim Leitrohstoff möglich."
    elif unit == "pcs":
        text = "Stück nur bei Stückzahlen oder einer Chargengröße „Stück“ möglich."
    else:
        text = "Bei Stückzahlen wird keine Menge in Gramm eingegeben."
    raise ValidationError(text, field="input_unit", code="unit_invalid")


def _pieces(data) -> tuple[tuple[int, int], ...]:
    if not isinstance(data, list):
        raise ValidationError("Bitte mindestens eine Stückzahl eingeben.", field="pieces", code="pieces_missing")
    result: dict[int, int] = {}
    for entry in data:
        if not isinstance(entry, dict):
            raise ValidationError("Ungültige Stückzahl.", field="pieces", code="pieces_invalid")
        pid = whole_number(entry.get("piece_weight_id"), "pieces", "das Stückgewicht", minimum=1)
        count = whole_number(entry.get("count"), "pieces", "Die Stückzahl", minimum=0, maximum=MAX_PIECES)
        if pid in result:
            raise ValidationError("Ein Stückgewicht ist doppelt angegeben.", field="pieces", code="pieces_duplicate")
        result[pid] = count
    pieces = tuple((pid, count) for pid, count in result.items() if count > 0)
    if not pieces:
        raise ValidationError("Bitte mindestens eine Stückzahl eingeben.", field="pieces", code="pieces_missing")
    return pieces


def _overrides(data) -> dict[int, int]:
    if data is None:
        return {}
    if not isinstance(data, list):
        raise ValidationError("Ungültige Mengenänderung.", field="overrides", code="override_invalid")
    result: dict[int, int] = {}
    for entry in data:
        if not isinstance(entry, dict):
            raise ValidationError("Ungültige Mengenänderung.", field="overrides", code="override_invalid")
        position = whole_number(entry.get("position"), "overrides", "die Zeile", minimum=1)
        amount = whole_number(entry.get("amount_g"), "overrides", "Die geänderte Menge", minimum=0,
                              maximum=MAX_DOUGH_G)
        if position in result:
            raise ValidationError(f"Zeile {position} ist doppelt geändert.", field="overrides",
                                  code="override_duplicate")
        result[position] = amount
    return result


def validate_request(payload) -> CalcRequest:
    """Prüft die Anfrage an ``POST /api/v1/calculation`` (Abschnitt 7.1)."""
    if not isinstance(payload, dict):
        raise ValidationError("Ungültige Anfrage.", code="invalid_request")
    recipe_id = whole_number(payload.get("recipe_id"), "recipe_id", "ein Rezept", minimum=1)
    version_no = whole_number(payload.get("version_no"), "version_no", "Die Version", minimum=1, required=False)
    basis_type = payload.get("basis_type")
    if basis_type not in BASIS_TYPES:
        raise ValidationError("Bitte eine Bezugsgröße wählen.", field="basis_type", code="basis_type")

    unit = payload.get("input_unit")
    if unit in (None, ""):
        unit = "pcs" if basis_type == "pieces" else ("" if basis_type == "batch_size" else "g")
    if unit:
        check_unit(basis_type, unit)

    req = {"recipe_id": recipe_id, "version_no": version_no, "basis_type": basis_type, "input_unit": unit,
           "overrides": _overrides(payload.get("overrides"))}

    if basis_type in ("total", "flour_total", "raw_material"):
        req["value_g"] = amount_to_grams(payload.get("value"), unit)
        req["input_value"] = str(payload.get("value")).strip()
    if basis_type == "raw_material":
        req["raw_material_id"] = whole_number(payload.get("raw_material_id"), "raw_material_id",
                                              "einen Leitrohstoff", minimum=1)
        req["item_position"] = whole_number(payload.get("item_position"), "item_position", "die Zeile",
                                            minimum=1, required=False)
    if basis_type == "pieces":
        req["pieces"] = _pieces(payload.get("pieces"))
    if basis_type == "batch_size":
        req["batch_size_id"] = whole_number(payload.get("batch_size_id"), "batch_size_id",
                                            "eine Chargengröße", minimum=1)
    return CalcRequest(**req)
