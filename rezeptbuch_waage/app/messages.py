"""MQTT-Nachrichten der Waagen-Bridge (Schnittstelle zu Add-on 1, Modul 08).

Schema 2 nach docs/waage.md Abschnitt 6 (K07-1 bis K07-3). Jede Änderung am
Format erhöht SCHEMA_VERSION.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

SCHEMA_VERSION = 2
TOPIC_PREFIX = "rezeptbuch/v1"
AVAILABILITY_TOPIC = f"{TOPIC_PREFIX}/scale_bridge/availability"
ONLINE = "online"
OFFLINE = "offline"

STATUS_OK = "ok"
STATUS_INVALID = "invalid"
STATUS_OFFLINE = "offline"
STATUS_ERROR = "error"
VALID_STATUS = {STATUS_OK, STATUS_INVALID, STATUS_OFFLINE, STATUS_ERROR}

COMMANDS = ("tare", "zero")


def _check_station(station: int) -> None:
    if station not in (1, 2):
        raise ValueError(f"Ungültige Station: {station}")


def state_topic(station: int) -> str:
    _check_station(station)
    return f"{TOPIC_PREFIX}/station/{station}/scale/state"


def cmd_topic(station: int) -> str:
    _check_station(station)
    return f"{TOPIC_PREFIX}/station/{station}/scale/cmd"


def format_ts(ts: datetime) -> str:
    """UTC mit Millisekunden, z. B. 2026-11-18T20:00:00.123+00:00."""
    return ts.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def state_payload(
    station: int,
    status: str,
    weight_g: int | None = None,
    stable: bool = False,
    scale_stable: bool | None = None,
    net: bool | None = None,
    capacity_g: int = 30000,
    resolution_g: int = 1,
    ts: datetime | None = None,
) -> str:
    """Baut die JSON-Nachricht für einen Waagenzustand (Schema 2)."""
    _check_station(station)
    if status not in VALID_STATUS:
        raise ValueError(f"Ungültiger Status: {status}")
    if status == STATUS_OK and weight_g is None:
        raise ValueError("Bei Status 'ok' ist ein Gewicht nötig")
    ok = status == STATUS_OK
    # ST/US und brutto/netto gibt es nur zu einer gültigen Zeile
    has_line = ok
    ts = ts or datetime.now(timezone.utc)
    return json.dumps(
        {
            "v": SCHEMA_VERSION,
            "station": station,
            "status": status,
            "weight_g": int(weight_g) if ok else None,
            # Ohne gültiges Gewicht gilt die Waage nie als stabil
            "stable": bool(stable) and ok,
            "scale_stable": bool(scale_stable) if has_line and scale_stable is not None else None,
            "net": bool(net) if has_line and net is not None else None,
            "capacity_g": int(capacity_g),
            "resolution_g": int(resolution_g),
            "ts": format_ts(ts),
        },
        separators=(",", ":"),
    )


class CommandError(ValueError):
    """Befehl ist kein gültiges JSON nach Schema 2."""


def parse_command(payload: bytes | str) -> str:
    """Liest `{"v":2,"cmd":"tare"|"zero"}` und gibt den Befehl zurück."""
    try:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CommandError("kein gültiges JSON") from exc
    if not isinstance(data, dict):
        raise CommandError("kein JSON-Objekt")
    if data.get("v") != SCHEMA_VERSION:
        raise CommandError(f"falsche Version {data.get('v')!r}")
    cmd = data.get("cmd")
    if cmd not in COMMANDS:
        raise CommandError(f"unbekannter Befehl {cmd!r}")
    return cmd
