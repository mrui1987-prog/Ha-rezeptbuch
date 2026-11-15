"""Gemeinsame Textregeln (Modul 05, Sperre B2 aus dem Freigabebericht Modul 03).

Namen, die mit ``=``, ``+``, ``-`` oder ``@`` beginnen, werden beim Anlegen,
Umbenennen und Import abgelehnt. Excel würde solche Zellen in einer exportierten
Datei als Formel ausführen (CSV-Injection). Vorhandene Namen bleiben unberührt;
die aufrufende Stelle prüft deshalb nur neue oder geänderte Namen.

Gilt für Rohstoffname und Kurzname (Modul 03, M05-14) sowie in Modul 05 für
Rezeptname, Gruppenname, Schrittname und die Bezeichnungen von Stückgewichten
und Chargengrößen (R05-3). Hinweistexte sind frei.
"""

from __future__ import annotations

from .errors import ValidationError

FORMULA_START = ("=", "+", "-", "@")


def starts_like_formula(text: str | None) -> bool:
    """True, wenn der Text (ohne Leerzeichen am Rand) mit =, +, - oder @ beginnt."""
    if not text:
        return False
    stripped = text.strip()
    return bool(stripped) and stripped[0] in FORMULA_START


def check_no_formula_start(text: str | None, *, field: str, label: str = "Name") -> None:
    """Löst einen Eingabefehler aus, wenn der Text wie eine Excel-Formel beginnt (B2)."""
    if starts_like_formula(text):
        raise ValidationError(f"{label} darf nicht mit =, +, - oder @ beginnen.",
                              field=field, code="formula_start")
