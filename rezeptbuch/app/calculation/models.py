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
from .engine import BASIS_TYPES, MAX_DOUGH_G, MAX_DOUGHS, SOLE_BASIS_TYPES, SPLIT_MODES, SUB_MODES

MAX_PIECES = 100_000
MAX_BATCH_COUNT = 100           # Anzahl je Chargengröße (P06-13)
MAX_FACTOR_HUNDREDTHS = 10_000  # Faktor höchstens 100 (R06-26)
INPUT_UNITS = ("g", "kg", "l", "pcs")

# Erlaubte Eingabeeinheiten je Bezugsgröße (P06-8). Chargengröße: je nach Art, siehe Service.
UNITS_FOR_BASIS = {
    "total": ("g", "kg"),
    "flour_total": ("g", "kg"),
    "raw_material": ("g", "kg", "l"),
    "pieces": ("pcs",),
    "batch_size": ("g", "kg", "pcs"),
    "factor": ("g",),
    "combined": ("g", "kg"),
}
FACTOR_TO_G = {"g": 1, "kg": 1000, "l": 1000}          # 1 l = 1 000 g (M02-1e)

_NUMBER = re.compile(r"^[0-9]+([.,][0-9]+)?$")
_FACTOR = re.compile(r"^[0-9]+([.,][0-9]{1,2})?$")
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
    # Teil C3 (docs/berechnung.md 17.11)
    total_part_g: int | None = None            # Gesamtteig-Anteil bei 'combined'
    factor_hundredths: int | None = None       # Faktor bei 'factor'/'combined' (150 = 1,5)
    batch_sizes: tuple[tuple[int, int], ...] = ()   # (Chargengröße-ID, Anzahl)
    order_limit_g: int | None = None           # Obergrenze nur für den Auftrag
    split: bool | None = None                  # Antwort auf „teilen?“ (Mehl gesamt/Leitrohstoff)
    dough_count: int | None = None
    split_mode: str = "fill"
    sub_modes: dict[int, str] = field(default_factory=dict)


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


def parse_factor(value, field_name: str = "factor") -> int:
    """Faktor × Grundrezept → Hundertstel (R06-24, R06-26, P06-12): 0,01 bis 100, höchstens 2 Nachkommastellen."""
    message = "Bitte einen Faktor zwischen 0,01 und 100 eingeben (höchstens 2 Nachkommastellen)."
    if value is None or isinstance(value, bool):
        raise ValidationError(message, field=field_name, code="factor_invalid")
    if isinstance(value, (int, float)):
        text = repr(value) if isinstance(value, float) else str(value)
    elif isinstance(value, str):
        text = value.strip().replace(" ", "")
    else:
        raise ValidationError(message, field=field_name, code="factor_invalid")
    if not _FACTOR.match(text):
        raise ValidationError(message, field=field_name, code="factor_invalid")
    hundredths = int(Decimal(text.replace(",", ".")) * 100)
    if not 1 <= hundredths <= MAX_FACTOR_HUNDREDTHS:
        raise ValidationError(message, field=field_name, code="factor_invalid")
    return hundredths


def _batch_sizes(data) -> tuple[tuple[int, int], ...]:
    if data is None:
        return ()
    if not isinstance(data, list):
        raise ValidationError("Ungültige Chargengröße.", field="batch_sizes", code="batch_sizes_invalid")
    result: dict[int, int] = {}
    for entry in data:
        if not isinstance(entry, dict):
            raise ValidationError("Ungültige Chargengröße.", field="batch_sizes", code="batch_sizes_invalid")
        sid = whole_number(entry.get("batch_size_id"), "batch_sizes", "die Chargengröße", minimum=1)
        count = whole_number(entry.get("count"), "batch_sizes", "die Anzahl", minimum=0)
        if count > MAX_BATCH_COUNT:
            raise ValidationError(f"Höchstens {MAX_BATCH_COUNT} je Chargengröße.", field="batch_sizes",
                                  code="batch_count_invalid")
        if sid in result:
            raise ValidationError("Eine Chargengröße ist doppelt angegeben.", field="batch_sizes",
                                  code="batch_sizes_duplicate")
        result[sid] = count
    return tuple((sid, count) for sid, count in result.items() if count > 0)


def _amount_part(data, field_name: str) -> int | None:
    """Menge als Zahl/Text (Gramm) oder als {value, input_unit} mit g/kg; leer = None."""
    if data is None or (isinstance(data, str) and not data.strip()):
        return None
    if isinstance(data, dict):
        value, unit = data.get("value"), data.get("input_unit") or "g"
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
    else:
        value, unit = data, "g"
    if unit not in ("g", "kg"):
        raise ValidationError("Bitte g oder kg angeben.", field=field_name, code="unit_invalid")
    return amount_to_grams(value, unit, field_name)


def _order_limit(data) -> int | None:
    try:
        return _amount_part(data, "order_limit")
    except ValidationError as exc:
        # P06-17 mit eigener Meldung
        raise ValidationError("Obergrenze: bitte ganze Gramm größer als 0 und höchstens 1 000 kg eingeben.",
                              field="order_limit", code="order_limit_invalid") from exc


def _sub_modes(data) -> dict[int, str]:
    if data is None:
        return {}
    if not isinstance(data, list):
        raise ValidationError("Ungültige Auswahl „je Teig/für alle“.", field="sub_modes", code="sub_mode_invalid")
    result: dict[int, str] = {}
    for entry in data:
        if not isinstance(entry, dict) or entry.get("mode") not in SUB_MODES:
            raise ValidationError("Bitte „je Teig“ oder „für alle“ wählen.", field="sub_modes",
                                  code="sub_mode_invalid")
        position = whole_number(entry.get("position"), "sub_modes", "die Zeile", minimum=1)
        result[position] = entry["mode"]
    return result


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

    # Teil C3: Kombinieren, Faktor (17.2, 17.3)
    combo = {
        "total_part": payload.get("total_part"),
        "factor": payload.get("factor"),
        "batch_sizes": payload.get("batch_sizes"),
        "pieces": payload.get("pieces") if basis_type != "pieces" else None,
    }
    given = {key for key, value in combo.items() if value not in (None, "", [])}
    if basis_type == "factor":
        req["factor_hundredths"] = parse_factor(payload.get("factor"))
        given.discard("factor")
    if basis_type == "combined":
        req["total_part_g"] = _amount_part(payload.get("total_part"), "total_part")
        if payload.get("factor") not in (None, ""):
            req["factor_hundredths"] = parse_factor(payload.get("factor"))
        req["batch_sizes"] = _batch_sizes(payload.get("batch_sizes"))
        if payload.get("pieces") not in (None, []):
            # Stückzahlen 0 werden in der Kombination einfach weggelassen
            try:
                req["pieces"] = _pieces(payload.get("pieces"))
            except ValidationError as exc:
                if exc.code != "pieces_missing":
                    raise
        if not (req.get("total_part_g") or req.get("factor_hundredths") or req.get("batch_sizes")
                or req.get("pieces")):
            raise ValidationError("Bitte mindestens eine Angabe machen.", field="basis_type", code="demand_missing")
    elif given:
        if basis_type in SOLE_BASIS_TYPES:
            raise ValidationError("Mehl gesamt und Leitrohstoff nur allein möglich.", field="basis_type",
                                  code="sole_basis")
        raise ValidationError("Mehrere Angaben bitte mit der Bezugsart „kombiniert“.", field="basis_type",
                              code="combine_required")

    # Obergrenze und Teige (17.4 bis 17.6)
    req["order_limit_g"] = _order_limit(payload.get("order_limit"))
    split = payload.get("split")
    if split is not None and not isinstance(split, bool):
        raise ValidationError("„Teilen?“ bitte mit Ja oder Nein beantworten.", field="split", code="split_invalid")
    req["split"] = split
    req["dough_count"] = whole_number(payload.get("dough_count"), "dough_count", "Die Anzahl Teige", minimum=1,
                                      required=False)
    if req["dough_count"] is not None and req["dough_count"] > MAX_DOUGHS:
        raise ValidationError(f"Höchstens {MAX_DOUGHS} Teige je Auftrag.", field="dough_count", code="too_many_doughs")
    mode = payload.get("split_mode") or "fill"
    if mode not in SPLIT_MODES:
        raise ValidationError("Bitte „voll auffüllen“ oder „gleichmäßig“ wählen.", field="split_mode",
                              code="split_mode_invalid")
    req["split_mode"] = mode
    req["sub_modes"] = _sub_modes(payload.get("sub_modes"))
    return CalcRequest(**req)
