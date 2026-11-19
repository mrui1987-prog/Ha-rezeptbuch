"""Wetter für die Ecke der Stationsoberfläche (Modul 10, M10-16, docs/dashboard.md Abschnitt 7).

Liest eine Wetter-Entität aus Home Assistant über die Supervisor-API (Add-on-Option
``weather_entity``, Vorgabe ``weather.forecast_home``; leer oder ``aus`` = kein Wetter).
Nur Anzeige: Fehler werden nie an die Oberfläche gemeldet, das Wetter fehlt dann einfach.
Abruf höchstens alle 15 Minuten, Zeitlimit 5 s, nur Standardbibliothek.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from datetime import datetime
from typing import Callable

from ..settings import load_options

log = logging.getLogger(__name__)

SUPERVISOR_API = "http://supervisor/core/api"
DEFAULT_ENTITY = "weather.forecast_home"
OFF_VALUES = ("", "-", "aus", "off", "none")
CACHE_SECONDS = 15 * 60
TIMEOUT_SECONDS = 5
TOKEN_FILES = (
    "/run/s6/container_environment/SUPERVISOR_TOKEN",
    "/var/run/s6/container_environment/SUPERVISOR_TOKEN",
)

# Zustände der HA-Wetter-Entität → Symbol und deutscher Text
CONDITIONS = {
    "sunny": ("☀️", "Sonnig"),
    "clear-night": ("🌙", "Klar"),
    "partlycloudy": ("⛅", "Teils bewölkt"),
    "cloudy": ("☁️", "Bewölkt"),
    "rainy": ("🌧️", "Regen"),
    "pouring": ("🌧️", "Starkregen"),
    "snowy": ("❄️", "Schnee"),
    "snowy-rainy": ("🌨️", "Schneeregen"),
    "fog": ("🌫️", "Nebel"),
    "hail": ("🌨️", "Hagel"),
    "lightning": ("⛈️", "Gewitter"),
    "lightning-rainy": ("⛈️", "Gewitter"),
    "windy": ("💨", "Windig"),
    "windy-variant": ("💨", "Windig"),
    "exceptional": ("⚠️", "Unwetter"),
}

UNAVAILABLE = {"available": False}


def weather_entity(options: dict | None = None) -> str | None:
    """Entität aus der Option ``weather_entity``; ``None`` = Wetter ausgeschaltet."""
    if options is None:
        options = load_options()
    value = options.get("weather_entity", DEFAULT_ENTITY)
    if not isinstance(value, str) or value.strip().lower() in OFF_VALUES:
        return None
    value = value.strip()
    if not value.startswith("weather.") or " " in value:
        log.warning("weather_entity=%r ist keine Wetter-Entität – Wetter ausgeblendet", value)
        return None
    return value


def supervisor_token() -> str | None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token:
        return token.strip()
    for path in TOKEN_FILES:
        try:
            with open(path, encoding="utf-8") as handle:
                token = handle.read().strip()
        except OSError:
            continue
        if token:
            return token
    return None


def _request(url: str, token: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="GET" if body is None else "POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:  # noqa: S310 – feste Supervisor-Adresse
        return json.loads(res.read().decode("utf-8"))


def _number(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(round(value))


def _today_entry(forecast: list, today) -> dict | None:
    """Eintrag der Tagesvorhersage für heute (Ortszeit); fehlt er, keine Höchst-/Tiefstwerte."""
    for entry in forecast or []:
        try:
            when = datetime.fromisoformat(str(entry.get("datetime")).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if when.tzinfo is not None:
            when = when.astimezone()
        if when.date() == today:
            return entry
    return None


def build_weather(entity: str, state: dict, forecast_response: dict | None, today) -> dict:
    """Antwort aus Zustand und Tagesvorhersage zusammensetzen (rein, ohne Netz)."""
    condition = state.get("state")
    if condition in (None, "unavailable", "unknown"):
        return dict(UNAVAILABLE)
    attrs = state.get("attributes") or {}
    symbol, text = CONDITIONS.get(condition, ("", str(condition)))
    result = {"available": True, "entity": entity, "condition": condition, "symbol": symbol, "text": text,
              "temp": _number(attrs.get("temperature")), "unit": attrs.get("temperature_unit") or "°C",
              "max": None, "min": None}
    forecast = None
    if isinstance(forecast_response, dict):
        service = forecast_response.get("service_response", forecast_response)
        forecast = ((service or {}).get(entity) or {}).get("forecast")
    entry = _today_entry(forecast, today)
    if entry is not None:
        result["max"] = _number(entry.get("temperature"))
        result["min"] = _number(entry.get("templow"))
    return result


def fetch_weather(entity: str, token: str, today=None) -> dict:
    """Zustand und Tagesvorhersage über die Supervisor-API holen."""
    today = today or datetime.now().date()
    state = _request(f"{SUPERVISOR_API}/states/{entity}", token)
    forecast = None
    try:
        forecast = _request(f"{SUPERVISOR_API}/services/weather/get_forecasts?return_response",
                            token, {"entity_id": entity, "type": "daily"})
    except Exception as exc:  # noqa: BLE001 – ohne Vorhersage nur ohne Höchst-/Tiefstwert
        log.info("Wettervorhersage für %s nicht lesbar: %s", entity, exc)
    return build_weather(entity, state, forecast, today)


class WeatherCache:
    """Hält das Wetter 15 Minuten; Fehler werden höchstens einmal je 15 Minuten protokolliert."""

    def __init__(self, fetcher: Callable[[str, str], dict] = fetch_weather,
                 clock: Callable[[], float] = time.monotonic,
                 entity_source: Callable[[], str | None] = weather_entity,
                 token_source: Callable[[], str | None] = supervisor_token) -> None:
        self.fetcher = fetcher
        self.clock = clock
        self.entity_source = entity_source
        self.token_source = token_source
        self._lock = threading.Lock()
        self._value: dict | None = None
        self._at = -1e12
        self._warned_at = -1e12

    def get(self) -> dict:
        with self._lock:
            now = self.clock()
            if self._value is not None and now - self._at < CACHE_SECONDS:
                return self._value
            self._value = self._load(now)
            self._at = now
            return self._value

    def _load(self, now: float) -> dict:
        entity = self.entity_source()
        if entity is None:
            return dict(UNAVAILABLE)
        token = self.token_source()
        if not token:
            self._warn(now, "Wetter: kein Zugang zu Home Assistant (SUPERVISOR_TOKEN fehlt)")
            return dict(UNAVAILABLE)
        try:
            data = self.fetcher(entity, token)
        except Exception as exc:  # noqa: BLE001 – Wetter ist nur Anzeige
            self._warn(now, f"Wetter aus {entity} nicht lesbar: {exc}")
            return dict(UNAVAILABLE)
        if isinstance(data, dict):
            data["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            return data
        return dict(UNAVAILABLE)

    def _warn(self, now: float, text: str) -> None:
        if now - self._warned_at >= CACHE_SECONDS:
            log.warning(text)
            self._warned_at = now
