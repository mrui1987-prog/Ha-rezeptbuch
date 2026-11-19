"""Anzeige-Daten für die Stationsoberfläche (Modul 10): Wetter für die Ecke oben links.

Ohne PIN (nur Anzeige). Antwort immer 200; ohne Wetter ``{"available": false}``.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from .weather import WeatherCache

router = APIRouter(prefix="/api/v1/display", tags=["Anzeige"])


def get_weather_cache(request: Request) -> WeatherCache:
    cache = getattr(request.app.state, "weather", None)
    if cache is None:
        cache = WeatherCache()
        request.app.state.weather = cache
    return cache


@router.get("/weather")
def weather(request: Request) -> dict:
    return get_weather_cache(request).get()
