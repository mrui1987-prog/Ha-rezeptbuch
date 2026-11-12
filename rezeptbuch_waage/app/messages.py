"""MQTT-Nachrichten der Waagen-Bridge (Schnittstelle zu Add-on 1).

Format und Topics sind in docs/architektur.md festgelegt. Jede Änderung am
Format erhöht SCHEMA_VERSION.
"""

import json
from datetime import datetime, timezone

SCHEMA_VERSION = 1
TOPIC_PREFIX = "rezeptbuch/v1"
VALID_STATUS = {"ok", "offline", "error"}


def state_topic(station: int) -> str:
    if station not in (1, 2):
        raise ValueError(f"Ungültige Station: {station}")
    return f"{TOPIC_PREFIX}/station/{station}/scale/state"


def state_payload(
    station: int,
    weight_g: int | None,
    stable: bool,
    status: str = "ok",
    ts: datetime | None = None,
) -> str:
    """Baut die JSON-Nachricht für einen Waagenzustand."""
    if status not in VALID_STATUS:
        raise ValueError(f"Ungültiger Status: {status}")
    if status == "ok" and weight_g is None:
        raise ValueError("Bei Status 'ok' ist ein Gewicht nötig")
    ts = ts or datetime.now(timezone.utc)
    return json.dumps(
        {
            "v": SCHEMA_VERSION,
            "station": station,
            "weight_g": None if weight_g is None else int(weight_g),
            # Ohne gültiges Gewicht gilt die Waage nie als stabil
            "stable": bool(stable) and status == "ok",
            "status": status,
            "ts": ts.isoformat(),
        },
        separators=(",", ":"),
    )
