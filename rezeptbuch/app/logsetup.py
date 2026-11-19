"""Protokoll des Rezeptservers: Stufe aus der Add-on-Option ``log_level``, Ortszeit (Befund B1, 0.8.1).

Bis 0.8.0 wurde ``log_level`` nirgends angewendet; Python gab dadurch nur Warnungen
und Fehler aus (Praxisprüfung Modul 08). Jetzt bekommen die eigenen Logger
(``rezeptbuch…`` und ``app…``) einen Ausgabekanal mit Uhrzeit und der eingestellten
Stufe. uvicorn behält sein eigenes Protokoll. Die Logger geben weiter an die Wurzel
weiter (dort hängt im Betrieb kein Ausgabekanal, also keine doppelten Zeilen).

Ortszeit: unter s6 (``init: false``) fehlt ``TZ`` aus dem Dockerfile; sie wird aus der
s6-Umgebungsdatei gelesen, sonst gilt Europe/Berlin (wie Add-on 2, Befund O1).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Callable, MutableMapping

DEFAULT_TZ = "Europe/Berlin"
TZ_FILES = (
    "/run/s6/container_environment/TZ",
    "/var/run/s6/container_environment/TZ",
)
LEVELS = ("debug", "info", "warning", "error")
DEFAULT_LEVEL = "info"
LOGGER_NAMES = ("rezeptbuch", "app")
FORMAT = "%(asctime)s %(levelname)s %(message)s"

_HANDLER_MARK = "_rezeptbuch_handler"


def read_tz(environ: MutableMapping[str, str], files: tuple = TZ_FILES) -> str | None:
    """``TZ`` aus der Umgebung, sonst aus der s6-Umgebungsdatei."""
    value = (environ.get("TZ") or "").strip()
    if value:
        return value
    for path in files:
        try:
            with open(path, encoding="utf-8") as handle:
                value = handle.read().strip()
        except OSError:
            continue
        if value:
            return value
    return None


def setup_timezone(
    environ: MutableMapping[str, str] | None = None,
    files: tuple = TZ_FILES,
    default: str = DEFAULT_TZ,
    tzset: Callable[[], None] | None = None,
) -> str:
    """Setzt ``TZ`` (Umgebung → s6-Datei → Standard) und übernimmt sie; gibt sie zurück."""
    env = os.environ if environ is None else environ
    tz = read_tz(env, files) or default
    env["TZ"] = tz
    (tzset or getattr(time, "tzset", lambda: None))()
    return tz


def log_level(options: dict | None) -> str:
    value = (options or {}).get("log_level", DEFAULT_LEVEL)
    return value if value in LEVELS else DEFAULT_LEVEL


def setup_logging(options: dict | None, stream=None) -> str:
    """Wendet ``log_level`` auf die eigenen Logger an; mehrfacher Aufruf ohne doppelte Ausgabe."""
    level = log_level(options)
    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        logger.setLevel(level.upper())
        if not any(getattr(h, _HANDLER_MARK, False) for h in logger.handlers):
            handler = logging.StreamHandler(stream or sys.stderr)
            handler.setFormatter(logging.Formatter(FORMAT))
            setattr(handler, _HANDLER_MARK, True)
            logger.addHandler(handler)
    return level
