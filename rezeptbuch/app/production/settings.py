"""Einstellungen des Wiegeablaufs (Modul 09, docs/ablauf.md Abschnitt 10, M09-4, K09-7, K09-12).

Die Werte stehen in der Tabelle ``setting`` (Modul 02). Fehlt ein Schlüssel, gilt der Startwert
aus ``SETTINGS`` – die Tabelle enthält nur geänderte Werte. Lesen ohne PIN, Ändern mit PIN
(Router). Alle Werte sind ganze Zahlen.
"""

from __future__ import annotations

import sqlite3

from ..db import transaction
from ..errors import ValidationError

# Schlüssel → (Startwert, kleinster, größter Wert, Bezeichnung, Einheit)
SETTINGS: dict[str, tuple[int, int, int, str, str]] = {
    "auto_ack_seconds": (2, 1, 10, "Zeit für die automatische Quittung", "s"),
    "auto_ack_span_g": (5, 0, 50, "Erlaubte Wanderung in dieser Zeit", "g"),
    "offline_pause_seconds": (45, 10, 300, "Waage getrennt bis zur Pause", "s"),
    "capacity_warn_g": (1000, 0, 10_000, "Vorwarnung vor der Höchstlast", "g"),
    "tare_confirm_seconds": (3, 1, 10, "Wartezeit auf die Tara-Bestätigung der Waage", "s"),
    "resume_check_g": (5, 0, 100, "Erlaubte Abweichung der Gesamtlast beim „Weiter“", "g"),
    # Michael 19.11.2026, 15:21: Auto-Quittung erst ab dieser Menge (0 = aus), darunter von Hand
    "auto_ack_min_g": (70, 0, 5000, "Mindestlast Autoquittierung", "g"),
}


def load_settings(conn: sqlite3.Connection) -> dict[str, int]:
    """Alle Einstellungen als Zahlen; ungültige gespeicherte Werte fallen auf den Startwert zurück."""
    stored = {r["key"]: r["value"] for r in conn.execute(
        f"SELECT key, value FROM setting WHERE key IN ({', '.join('?' * len(SETTINGS))})", list(SETTINGS))}
    values = {}
    for key, (default, low, high, _label, _unit) in SETTINGS.items():
        try:
            value = int(stored[key])
        except (KeyError, TypeError, ValueError):
            value = default
        values[key] = value if low <= value <= high else default
    return values


def describe_settings(conn: sqlite3.Connection) -> list[dict]:
    """Für die Prüfseite: Wert, Startwert, Bereich, Bezeichnung und Einheit je Schlüssel."""
    values = load_settings(conn)
    return [{"key": key, "value": values[key], "default": default, "min": low, "max": high,
             "label": label, "unit": unit}
            for key, (default, low, high, label, unit) in SETTINGS.items()]


def save_settings(conn: sqlite3.Connection, data) -> dict[str, int]:
    """Ändert einzelne Werte (nur bekannte Schlüssel, ganze Zahlen im Bereich)."""
    if not isinstance(data, dict) or not data:
        raise ValidationError("Bitte mindestens einen Wert angeben.", code="invalid_request")
    clean: dict[str, int] = {}
    for key, raw in data.items():
        if key not in SETTINGS:
            raise ValidationError(f"Unbekannte Einstellung „{key}“.", field=key, code="unknown_setting")
        _default, low, high, label, unit = SETTINGS[key]
        text = str(raw).strip() if raw is not None else ""
        if isinstance(raw, bool) or not text.isdigit():
            raise ValidationError(f"{label}: bitte eine ganze Zahl von {low} bis {high} {unit} eingeben.",
                                  field=key, code="setting_invalid")
        value = int(text)
        if not low <= value <= high:
            raise ValidationError(f"{label}: bitte eine ganze Zahl von {low} bis {high} {unit} eingeben.",
                                  field=key, code="setting_invalid")
        clean[key] = value
    with transaction(conn):
        for key, value in clean.items():
            conn.execute(
                "INSERT INTO setting (key, value, updated_at) VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, str(value)))
    return load_settings(conn)
