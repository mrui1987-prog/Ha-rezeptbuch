"""Nachrichten von und zu Add-on 2 (Schema 2, docs/waage.md Abschnitt 6).

Nur lesen und prüfen; kein MQTT, kein FastAPI. Die Prüfregeln folgen M08-8:
gültiges JSON, ``v`` = 2, Station 1/2 passend zum Topic, bekannter Status.
"""

from __future__ import annotations

import json
import re

SCHEMA_VERSION = 2
TOPIC_PREFIX = "rezeptbuch/v1"
STATE_TOPIC_FILTER = f"{TOPIC_PREFIX}/station/+/scale/state"
AVAILABILITY_TOPIC = f"{TOPIC_PREFIX}/scale_bridge/availability"
STATIONS = (1, 2)
COMMANDS = ("tare", "zero")

STATUS_OK = "ok"
STATUS_INVALID = "invalid"
STATUS_OFFLINE = "offline"
STATUS_ERROR = "error"
VALID_STATUS = (STATUS_OK, STATUS_INVALID, STATUS_OFFLINE, STATUS_ERROR)

_STATE_TOPIC_RE = re.compile(r"^rezeptbuch/v1/station/(\d+)/scale/state$")


class MessageError(ValueError):
    """Nachricht verworfen. ``kind`` dient der Drosselung im Protokoll."""

    def __init__(self, kind: str, text: str):
        super().__init__(text)
        self.kind = kind


def cmd_topic(station: int) -> str:
    if station not in STATIONS:
        raise ValueError(f"Ungültige Station: {station}")
    return f"{TOPIC_PREFIX}/station/{station}/scale/cmd"


def command_payload(cmd: str) -> str:
    if cmd not in COMMANDS:
        raise ValueError(f"Unbekannter Befehl: {cmd}")
    return json.dumps({"v": SCHEMA_VERSION, "cmd": cmd}, separators=(",", ":"))


def station_from_topic(topic: str) -> int | None:
    match = _STATE_TOPIC_RE.match(topic)
    if not match:
        return None
    number = int(match.group(1))
    return number if number in STATIONS else None


def _opt_bool(data: dict, key: str) -> bool | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise MessageError("field", f"Feld {key} ist kein Ja/Nein-Wert")
    return value


def _int(data: dict, key: str, default: int | None = None) -> int | None:
    value = data.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise MessageError("field", f"Feld {key} ist keine ganze Zahl")
    return value


def parse_state(topic: str, payload: bytes | str) -> dict:
    """Liest einen Waagenzustand (Schema 2) und gibt die geprüften Felder zurück."""
    station = station_from_topic(topic)
    if station is None:
        raise MessageError("topic", f"unbekanntes Topic {topic!r}")
    try:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MessageError("json", "kein gültiges JSON") from exc
    if not isinstance(data, dict):
        raise MessageError("json", "kein JSON-Objekt")
    if data.get("v") != SCHEMA_VERSION:
        raise MessageError("version", f"falsche Version {data.get('v')!r}")
    if data.get("station") != station:
        raise MessageError("station", f"Station {data.get('station')!r} passt nicht zum Topic (Station {station})")
    status = data.get("status")
    if status not in VALID_STATUS:
        raise MessageError("status", f"unbekannter Status {status!r}")
    weight = _int(data, "weight_g")
    if status == STATUS_OK and weight is None:
        raise MessageError("field", "Status ok ohne Gewicht")
    ok = status == STATUS_OK
    stable = data.get("stable", False)
    if not isinstance(stable, bool):
        raise MessageError("field", "Feld stable ist kein Ja/Nein-Wert")
    ts = data.get("ts")
    return {
        "station": station,
        "status": status,
        "weight_g": weight if ok else None,
        "stable": bool(stable) and ok,
        "scale_stable": _opt_bool(data, "scale_stable") if ok else None,
        "net": _opt_bool(data, "net") if ok else None,
        "capacity_g": _int(data, "capacity_g", 30000),
        "resolution_g": _int(data, "resolution_g", 1),
        "ts": ts if isinstance(ts, str) else None,
    }


def parse_availability(payload: bytes | str) -> str:
    """``online`` oder ``offline``; alles andere wird verworfen."""
    try:
        text = (payload.decode("utf-8") if isinstance(payload, bytes) else payload).strip()
    except UnicodeDecodeError as exc:
        raise MessageError("availability", "Verfügbarkeit nicht lesbar") from exc
    if text not in ("online", "offline"):
        raise MessageError("availability", f"unbekannte Verfügbarkeit {text!r}")
    return text
