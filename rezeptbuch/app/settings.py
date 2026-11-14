"""Einstellungen des Add-ons aus ``/data/options.json`` (Optionen in config.yaml).

Home Assistant schreibt die Optionen des Add-ons in ``/data/options.json``.
Für Tests kann die Datei über die Umgebungsvariable ``REZEPTBUCH_OPTIONS``
umgeleitet werden. Fehlt die Datei oder ist ein Wert ungültig, gelten die
Vorgaben.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_OPTIONS_PATH = Path("/data/options.json")

# Vorgabe und Grenzen von admin_timeout_minutes (siehe config.yaml: int(1,60))
DEFAULT_ADMIN_TIMEOUT_MINUTES = 5
MIN_ADMIN_TIMEOUT_MINUTES = 1
MAX_ADMIN_TIMEOUT_MINUTES = 60


def options_path() -> Path:
    return Path(os.environ.get("REZEPTBUCH_OPTIONS", str(DEFAULT_OPTIONS_PATH)))


def load_options(path: str | Path | None = None) -> dict:
    """Liest die Add-on-Optionen; leer, wenn die Datei fehlt oder nicht lesbar ist."""
    path = Path(path) if path is not None else options_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Optionen in %s nicht lesbar, es gelten die Vorgaben: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def admin_timeout_minutes(options: dict | None = None) -> int:
    """Dauer der Admin-Sitzung in Minuten (K03-2), Vorgabe 5, erlaubt 1–60."""
    if options is None:
        options = load_options()
    value = options.get("admin_timeout_minutes", DEFAULT_ADMIN_TIMEOUT_MINUTES)
    if isinstance(value, bool) or not isinstance(value, int) \
            or not MIN_ADMIN_TIMEOUT_MINUTES <= value <= MAX_ADMIN_TIMEOUT_MINUTES:
        logger.warning("admin_timeout_minutes=%r ist ungültig, es gelten %d Minuten",
                       value, DEFAULT_ADMIN_TIMEOUT_MINUTES)
        return DEFAULT_ADMIN_TIMEOUT_MINUTES
    return value
