"""Ortszeit für das Protokoll (Befund O1, Praxisprüfung C2, 0.7.5).

Unter s6 (`init: false`) startet das Programm ohne die Umgebungsvariablen des
Containers – `TZ` aus dem Dockerfile bzw. vom Supervisor fehlt dann, wie zuvor
`SUPERVISOR_TOKEN` (Befund 2 aus C1). Darum wird `TZ` beim Start aus der
s6-Umgebungsdatei gelesen, sonst Europe/Berlin gesetzt, und `time.tzset()`
aufgerufen. Die Zeitstempel in den MQTT-Meldungen (`ts`) bleiben UTC.
"""

from __future__ import annotations

import os
import time
from typing import Callable, MutableMapping

DEFAULT_TZ = "Europe/Berlin"

TZ_FILES = (
    "/run/s6/container_environment/TZ",
    "/var/run/s6/container_environment/TZ",
)


def read_tz(environ: MutableMapping[str, str], files: tuple = TZ_FILES) -> str | None:
    """`TZ` aus der Umgebung, sonst aus der s6-Umgebungsdatei."""
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
    """Setzt `TZ` (Umgebung → s6-Datei → Standard) und übernimmt sie; gibt sie zurück."""
    env = os.environ if environ is None else environ
    tz = read_tz(env, files) or default
    env["TZ"] = tz
    (tzset or getattr(time, "tzset", lambda: None))()
    return tz
