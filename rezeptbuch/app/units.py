"""Gewichtseinheiten.

Intern werden alle Gewichte als ganze Gramm gespeichert, damit keine
Rundungsfehler entstehen (siehe docs/architektur.md, Namenskonventionen).
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def kg_to_grams(value: str | int | float | Decimal) -> int:
    """Wandelt eine kg-Angabe in ganze Gramm um.

    Akzeptiert auch deutsche Schreibweise mit Komma, z. B. "9,500".
    """
    if isinstance(value, str):
        value = value.strip().replace(" ", "").replace(",", ".")
        if not value:
            raise ValueError("Leere Gewichtsangabe")
    try:
        kg = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Ungültige Gewichtsangabe: {value!r}") from exc
    grams = (kg * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(grams)


def grams_to_kg_text(grams: int) -> str:
    """Formatiert Gramm als kg-Text mit drei Nachkommastellen und Komma.

    Beispiel: 9500 -> "9,500"
    """
    sign = "-" if grams < 0 else ""
    grams = abs(int(grams))
    return f"{sign}{grams // 1000},{grams % 1000:03d}"
