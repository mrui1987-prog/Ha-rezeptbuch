"""Konfiguration des Add-ons lesen und prüfen (docs/waage.md Abschnitt 7).

Die Felder sind flach je Waage (`scale1_…`, `scale2_…`, K07-4). Home Assistant
prüft Wertebereiche schon beim Speichern; hier wird zusätzlich geprüft, damit
das Add-on auch mit einer fehlerhaften /data/options.json klar meldet, was fehlt.
Eine fehlerhafte Station startet nicht, die andere läuft weiter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

OPTIONS_FILE = Path("/data/options.json")

DRIVERS = ("kern", "simulator")
CONNECTIONS = ("tcp", "mqtt")
FORMATS = ("7E1", "7o1", "8n1")
MODES = ("CONT", "STC")
LOG_LEVELS = ("debug", "info", "warning", "error")

# Standardwerte je Waage (docs/waage.md Abschnitt 7). Keine IP-Adressen.
DEFAULTS: dict[str, object] = {
    "enabled": False,
    "driver": "kern",
    "connection": "tcp",
    "host": "",
    "port": 8899,
    "raw_topic": "",
    "cmd_topic": "",
    "baud": 9600,
    "format": "8n1",
    "mode": "CONT",
    "stable_window_ms": 1000,
    "stable_span_g": 2,
    "offline_after_s": 5,
    "capacity_g": 30000,
    "resolution_g": 1,
}

# Wertebereiche (Grenzen eingeschlossen)
RANGES: dict[str, tuple[int, int]] = {
    "port": (1, 65535),
    "baud": (1200, 115200),
    "stable_window_ms": (200, 5000),
    "stable_span_g": (0, 50),
    "offline_after_s": (2, 30),
    "capacity_g": (1, 1_000_000),
    "resolution_g": (1, 1000),
}


@dataclass(frozen=True)
class StationConfig:
    station: int
    enabled: bool = False
    driver: str = "kern"
    connection: str = "tcp"
    host: str = ""
    port: int = 8899
    raw_topic: str = ""
    cmd_topic: str = ""
    baud: int = 9600
    format: str = "8n1"
    mode: str = "CONT"
    stable_window_ms: int = 1000
    stable_span_g: int = 2
    offline_after_s: int = 5
    capacity_g: int = 30000
    resolution_g: int = 1
    errors: tuple[str, ...] = field(default=())

    @property
    def label(self) -> str:
        return f"Waage {self.station}"

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def uses_tcp(self) -> bool:
        return self.driver == "kern" and self.connection == "tcp"

    @property
    def uses_mqtt(self) -> bool:
        return self.driver == "kern" and self.connection == "mqtt"


@dataclass(frozen=True)
class AddonConfig:
    stations: tuple[StationConfig, ...]
    log_level: str = "info"

    @property
    def active(self) -> tuple[StationConfig, ...]:
        return tuple(s for s in self.stations if s.enabled)


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def parse_station(station: int, options: dict) -> StationConfig:
    """Liest die Felder `scale<n>_…` und prüft sie."""
    prefix = f"scale{station}_"
    raw = {key: options.get(prefix + key, default) for key, default in DEFAULTS.items()}
    errors: list[str] = []
    values: dict[str, object] = {}

    values["enabled"] = bool(raw["enabled"])
    for key in ("host", "raw_topic", "cmd_topic"):
        values[key] = str(raw[key] or "").strip()

    for key, choices in (("driver", DRIVERS), ("connection", CONNECTIONS),
                         ("format", FORMATS), ("mode", MODES)):
        value = str(raw[key])
        if value not in choices:
            errors.append(f"{prefix}{key}: „{value}“ ist nicht erlaubt "
                          f"({', '.join(choices)})")
            value = str(DEFAULTS[key])
        values[key] = value

    for key, (low, high) in RANGES.items():
        number = _as_int(raw[key])
        if number is None or not low <= number <= high:
            errors.append(f"{prefix}{key}: {raw[key]!r} liegt nicht zwischen "
                          f"{low} und {high}")
            number = int(DEFAULTS[key])  # type: ignore[arg-type]
        values[key] = number

    if values["enabled"] and values["driver"] == "kern":
        if values["connection"] == "tcp" and not values["host"]:
            errors.append(f"{prefix}host: Adresse des Waveshare fehlt "
                          "(nötig bei Anbindung tcp)")
        if values["connection"] == "mqtt" and not values["raw_topic"]:
            errors.append(f"{prefix}raw_topic: Roh-Topic fehlt "
                          "(nötig bei Anbindung mqtt)")
        if values["connection"] == "mqtt" and not values["cmd_topic"]:
            errors.append(f"{prefix}cmd_topic: Befehls-Topic fehlt "
                          "(nötig bei Anbindung mqtt)")

    return StationConfig(station=station, errors=tuple(errors), **values)  # type: ignore[arg-type]


def parse_options(options: dict) -> AddonConfig:
    level = str(options.get("log_level", "info"))
    if level not in LOG_LEVELS:
        level = "info"
    return AddonConfig(
        stations=(parse_station(1, options), parse_station(2, options)),
        log_level=level,
    )


def load_options(path: Path = OPTIONS_FILE) -> AddonConfig:
    """Liest /data/options.json. Fehlt die Datei, sind beide Waagen aus."""
    if not path.exists():
        return parse_options({})
    return parse_options(json.loads(path.read_text(encoding="utf-8")))


def describe(cfg: StationConfig) -> str:
    """Eine Zeile fürs Protokoll beim Start (Info-Felder als Prüfhilfe)."""
    if cfg.driver == "simulator":
        way = "Simulator"
    elif cfg.connection == "tcp":
        way = f"TCP {cfg.host}:{cfg.port}"
    else:
        way = f"MQTT Roh-Topic {cfg.raw_topic}, Befehle {cfg.cmd_topic}"
    return (f"{cfg.label}: {way}; Waage {cfg.baud} Baud, {cfg.format}, "
            f"Sendemodus {cfg.mode}; stabil {cfg.stable_span_g} g in "
            f"{cfg.stable_window_ms} ms; offline nach {cfg.offline_after_s} s; "
            f"Höchstlast {cfg.capacity_g} g, Auflösung {cfg.resolution_g} g")
