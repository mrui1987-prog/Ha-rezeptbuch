"""Eingabeprüfung für Rohstoffe (Modul 03, Regeln R03-2 bis R03-6; Sperre B2 aus Modul 05).

Reine Python-Prüfung ohne Webserver-Bibliothek, damit Modul 05 (Rezeptimport)
und Modul 04 (BÄKO-Import) dieselben Regeln nutzen können.

Die Eingabe kommt mit Anzeigewerten (``tolerance`` in Gramm oder Prozent);
das Ergebnis enthält die Spaltenwerte der Tabelle ``raw_material``
(``tolerance_value`` in Gramm bzw. Zehntelprozent, K2).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from ..errors import ValidationError
from ..text_rules import check_no_formula_start

TYPES = ("standard", "flour", "aid")       # aid = Hilfs- und Betriebsstoff (M03-26)
AID_UNIT = 1000                            # intern 1 Verpackungseinheit = 1000 (wie 1 kg, Strichcode S1)
TOLERANCE_UNITS = ("g", "percent")

MAX_NAME = 100
MAX_DISPLAY_NAME = 60
MAX_UNIT_LABEL = 30
MAX_GRAMS = 1_000_000          # Obergrenze für Toleranz und Gebindegröße in Gramm
MAX_PERCENT_TENTHS = 1000      # 100,0 %


def normalize_text(value: str) -> str:
    """Entfernt Leerzeichen am Rand und zieht doppelte Leerzeichen zusammen."""
    return " ".join(value.split())


def _plain(value) -> str | None:
    """Vergleichswert eines bisherigen Textfelds (normalisiert, leer = None)."""
    if not isinstance(value, str):
        return None
    return normalize_text(value) or None


def _text(value, field: str, label: str, *, required: bool, max_len: int) -> str | None:
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = normalize_text(value)
    else:
        raise ValidationError(f"{label} muss ein Text sein.", field=field)
    if not text:
        if required:
            raise ValidationError(f"{label} ist ein Pflichtfeld.", field=field)
        return None
    if len(text) > max_len:
        raise ValidationError(f"{label} darf höchstens {max_len} Zeichen lang sein.", field=field)
    return text


def _whole_number(value, field: str, label: str) -> int | None:
    """Ganze Zahl aus Zahl oder Ziffern-Text; leer ergibt None."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValidationError(f"{label} muss eine ganze Zahl sein.", field=field)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        # nur ASCII-Ziffern 0-9 (isdigit() lässt z. B. „²“ durch -> ValueError/500)
        if text.isascii() and text.isdigit():
            return int(text)
    raise ValidationError(f"{label} muss eine ganze Zahl sein.", field=field)


def parse_tolerance(value, unit: str) -> int:
    """Wandelt die eingegebene Toleranz in den Spaltenwert um (g oder Zehntelprozent).

    Gramm: ganze Zahl ≥ 0. Prozent: auf Zehntel genau (Komma oder Punkt), 0 bis 100,0.
    Nur **0 g** bedeutet „Sollhandzugabe“ (nur quittieren, nicht wiegen). **0 %** wird
    gewogen; bei der Verwiegung gilt nie weniger als ±1 g (M03-4, M05-13b).
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError("Toleranz ist ein Pflichtfeld.", field="tolerance")
    if isinstance(value, bool):
        raise ValidationError("Toleranz muss eine Zahl sein.", field="tolerance")
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        raise ValidationError("Toleranz muss eine Zahl sein.", field="tolerance") from None
    if not number.is_finite():
        raise ValidationError("Toleranz muss eine Zahl sein.", field="tolerance")
    if number < 0:
        raise ValidationError("Toleranz darf nicht negativ sein.", field="tolerance")

    if unit == "g":
        if number != number.to_integral_value():
            raise ValidationError("Toleranz in Gramm muss eine ganze Zahl sein.", field="tolerance")
        grams = int(number)
        if grams > MAX_GRAMS:
            raise ValidationError(f"Toleranz darf höchstens {MAX_GRAMS} g betragen.", field="tolerance")
        return grams

    tenths = number * 10
    if tenths != tenths.to_integral_value():
        raise ValidationError("Toleranz in Prozent muss auf Zehntelprozent genau sein (z. B. 2,5).", field="tolerance")
    tenths_int = int(tenths)
    if tenths_int > MAX_PERCENT_TENTHS:
        raise ValidationError("Toleranz in Prozent darf höchstens 100 betragen.", field="tolerance")
    return tenths_int


# -- Preis je kg (VC03-a, docs/rohstoffe.md 15.3, R03-13; K03-6, K03-8) -------------

MAX_PRICE_CENTS = 999_999       # 9 999,99 €/kg (Tippfehlerschutz, K03-6)

_PRICE_PLAIN = re.compile(r"^\d+([.,]\d+)?$")
_PRICE_THOUSANDS = re.compile(r"^\d{1,3}(\.\d{3})+,\d+$")   # Tausenderpunkt nur mit Komma (1.234,50)


def euro_text(cents: int) -> str:
    """Cent → „2,35“ (Komma, genau 2 Nachkommastellen, ohne Tausenderpunkt und €-Zeichen)."""
    return f"{cents // 100},{cents % 100:02d}"


def parse_price(value, field: str = "price_per_kg") -> tuple[int | None, str | None]:
    """Preis je kg in Euro netto → (Cent oder None, Rundungshinweis oder None).

    Leer oder ``None`` = kein Preis. Erlaubt sind „2,35“, „2.35“, „1.234,50“, „2,35 €“ und Zahlen.
    Mehr als 2 Nachkommastellen werden kaufmännisch gerundet (K03-8); die Obergrenze
    9 999,99 € gilt nach dem Runden. Negative Werte und Text sind Fehler (``invalid_price``).
    """
    if value is None:
        return None, None
    if isinstance(value, bool):
        raise ValidationError("Preis je kg muss eine Zahl sein (z. B. 2,35).", field=field, code="invalid_price")
    if isinstance(value, (int, float)):
        text = repr(value) if isinstance(value, float) else str(value)
    elif isinstance(value, str):
        text = value
    else:
        raise ValidationError("Preis je kg muss eine Zahl sein (z. B. 2,35).", field=field, code="invalid_price")
    text = text.replace(" ", " ").strip()
    if text.endswith("€"):
        text = text[:-1]
    text = text.replace(" ", "")
    if not text:
        return None, None
    if text.startswith("-") and _PRICE_PLAIN.match(text[1:]):
        raise ValidationError("Preis je kg darf nicht negativ sein.", field=field, code="invalid_price")
    if _PRICE_THOUSANDS.match(text):
        number = Decimal(text.replace(".", "").replace(",", "."))
    elif _PRICE_PLAIN.match(text) and text.isascii():
        number = Decimal(text.replace(",", "."))
    else:
        raise ValidationError("Preis je kg muss eine Zahl sein (z. B. 2,35).", field=field, code="invalid_price")
    rounded = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cents = int(rounded * 100)
    if cents > MAX_PRICE_CENTS:
        raise ValidationError("Preis je kg darf höchstens 9 999,99 € betragen.", field=field, code="invalid_price")
    hint = None
    if rounded != number:
        shown = format(number.normalize(), "f").replace(".", ",")
        hint = f"Preis auf 2 Nachkommastellen gerundet: {shown} → {euro_text(cents)} €"
    return cents, hint


def tolerance_display(unit: str, value: int) -> int | float:
    """Spaltenwert → Anzeigewert (Gramm ganz, Prozent mit einer Nachkommastelle)."""
    return value if unit == "g" else value / 10


def validate(data: dict, *, base: dict | None = None) -> dict:
    """Prüft Eingabe und liefert die Spaltenwerte.

    ``base`` sind die bisherigen Anzeigewerte beim Bearbeiten; die Eingabe überschreibt sie.
    Ohne ``base`` (Anlegen) sind Name und Toleranz Pflicht; die Nummer darf fehlen
    (dann vergibt der Dienst die nächste freie).

    Sperre B2 (M05-14): Name und Kurzname dürfen nicht mit =, +, - oder @ beginnen.
    Geprüft wird nur ein neuer oder geänderter Wert; ein vorhandener Name bleibt
    beim Speichern anderer Felder unbeanstandet.
    """
    if not isinstance(data, dict):
        raise ValidationError("Ungültige Eingabe.")
    merged = dict(base) if base else {}
    for key in ("number", "name", "display_name", "type", "tolerance_unit", "tolerance",
                "unit_size_g", "unit_label", "delivery_pack_g", "delivery_pack_label"):
        if key in data:
            merged[key] = data[key]

    if base is not None and "tolerance_unit" in data and "tolerance" not in data \
            and data["tolerance_unit"] != base.get("tolerance_unit"):
        raise ValidationError(
            "Bei geänderter Toleranzeinheit bitte auch den Toleranzwert angeben.", field="tolerance")

    number = _whole_number(merged.get("number"), "number", "Nummer")
    if number is not None and number <= 0:
        raise ValidationError("Nummer muss eine ganze Zahl größer 0 sein.", field="number")
    if number is not None and number > 2_000_000_000:
        raise ValidationError("Nummer ist zu groß.", field="number")

    name = _text(merged.get("name"), "name", "Name", required=True, max_len=MAX_NAME)
    display_name = _text(merged.get("display_name"), "display_name", "Kurzname", required=False,
                         max_len=MAX_DISPLAY_NAME)
    if base is None or name != _plain(base.get("name")):
        check_no_formula_start(name, field="name", label="Name")
    if display_name is not None and (base is None or display_name != _plain(base.get("display_name"))):
        check_no_formula_start(display_name, field="display_name", label="Kurzname")

    type_ = merged.get("type") or "standard"
    if type_ not in TYPES:
        raise ValidationError("Typ muss „standard“, „flour“ (Mehl) oder „aid“ (Hilfs- und Betriebsstoff) sein.",
                              field="type")

    if type_ == "aid":
        # Hilfs- und Betriebsstoff (M03-26, S8): keine Toleranz, gezählt in Verpackungseinheiten
        unit_label = _text(merged.get("unit_label"), "unit_label", "Verpackungseinheit", required=True,
                           max_len=MAX_UNIT_LABEL)
        if merged.get("delivery_pack_g") not in (None, "") or merged.get("delivery_pack_label") not in (None, ""):
            if base is None or "delivery_pack_g" in data or "delivery_pack_label" in data:
                raise ValidationError("Hilfs- und Betriebsstoffe haben kein Liefergebinde; gezählt wird je "
                                      "Verpackungseinheit.", field="delivery_pack_g")
        return {
            "number": number, "name": name, "display_name": display_name, "type": type_,
            "tolerance_unit": "g", "tolerance_value": 0, "unit_size_g": AID_UNIT, "unit_label": unit_label,
            "delivery_pack_g": None, "delivery_pack_label": None,
        }

    unit = merged.get("tolerance_unit") or "g"
    if unit not in TOLERANCE_UNITS:
        raise ValidationError("Toleranzeinheit muss „g“ oder „percent“ sein.", field="tolerance_unit")
    tolerance_value = parse_tolerance(merged.get("tolerance"), unit)

    unit_size = _whole_number(merged.get("unit_size_g"), "unit_size_g", "Gebindegröße")
    unit_label = _text(merged.get("unit_label"), "unit_label", "Gebindebezeichnung", required=False,
                       max_len=MAX_UNIT_LABEL)
    pack_size = _whole_number(merged.get("delivery_pack_g"), "delivery_pack_g", "Liefergebinde")
    pack_label = _text(merged.get("delivery_pack_label"), "delivery_pack_label", "Liefergebinde-Bezeichnung",
                       required=False, max_len=MAX_UNIT_LABEL)
    if pack_size is not None and not 0 < pack_size <= MAX_GRAMS:
        raise ValidationError(f"Liefergebinde muss zwischen 1 und {MAX_GRAMS} g liegen.", field="delivery_pack_g")
    if (pack_size is None) != (pack_label is None):
        raise ValidationError("Liefergebinde und Bezeichnung gehören zusammen (z. B. 9900 g „Karton“).",
                              field="delivery_pack_label" if pack_size is not None else "delivery_pack_g")
    if unit_size is not None and not 0 < unit_size <= MAX_GRAMS:
        raise ValidationError(f"Gebindegröße muss zwischen 1 und {MAX_GRAMS} g liegen.", field="unit_size_g")
    if (unit_size is None) != (unit_label is None):
        raise ValidationError("Gebindegröße und Gebindebezeichnung gehören zusammen (z. B. 55 g „Ei“).",
                              field="unit_label" if unit_size is not None else "unit_size_g")

    return {
        "number": number,
        "name": name,
        "display_name": display_name,
        "type": type_,
        "tolerance_unit": unit,
        "tolerance_value": tolerance_value,
        "unit_size_g": unit_size,
        "unit_label": unit_label,
        "delivery_pack_g": pack_size,
        "delivery_pack_label": pack_label,
    }
