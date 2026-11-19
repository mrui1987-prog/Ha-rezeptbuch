"""Wetter für die Stationsoberfläche (Modul 10, M10-16): Option, Aufbau der Antwort, Zwischenspeicher, Fehler."""

from datetime import date

import pytest

from app.display import weather as w


# ---------------------------------------------------------------- Option weather_entity

def test_entity_default_when_missing():
    assert w.weather_entity({}) == "weather.forecast_home"


@pytest.mark.parametrize("value", ["", "  ", "-", "aus", "AUS", "off", None, 5])
def test_entity_switched_off(value):
    assert w.weather_entity({"weather_entity": value}) is None


def test_entity_custom_and_invalid():
    assert w.weather_entity({"weather_entity": " weather.backstube "}) == "weather.backstube"
    assert w.weather_entity({"weather_entity": "sensor.temperatur"}) is None


# ---------------------------------------------------------------- Antwort zusammensetzen

STATE = {"state": "rainy", "attributes": {"temperature": 7.4, "temperature_unit": "°C"}}


def forecast(*entries):
    return {"changed_states": [], "service_response": {"weather.forecast_home": {"forecast": list(entries)}}}


def test_build_with_today_forecast():
    data = w.build_weather("weather.forecast_home", STATE, forecast(
        {"datetime": "2026-11-19T11:00:00+00:00", "temperature": 9.2, "templow": 3.6, "condition": "rainy"},
        {"datetime": "2026-11-20T11:00:00+00:00", "temperature": 5, "templow": 1}), date(2026, 11, 19))
    assert data == {"available": True, "entity": "weather.forecast_home", "condition": "rainy", "symbol": "🌧️",
                    "text": "Regen", "temp": 7, "unit": "°C", "max": 9, "min": 4}


def test_build_without_today_entry_has_no_range():
    data = w.build_weather("weather.forecast_home", STATE, forecast(
        {"datetime": "2026-11-20T11:00:00+00:00", "temperature": 5, "templow": 1}), date(2026, 11, 19))
    assert data["available"] is True and data["max"] is None and data["min"] is None


def test_build_without_forecast_and_unknown_condition():
    data = w.build_weather("weather.forecast_home", {"state": "sandstorm", "attributes": {}}, None, date(2026, 11, 19))
    assert data["text"] == "sandstorm" and data["symbol"] == "" and data["temp"] is None and data["unit"] == "°C"


@pytest.mark.parametrize("state", ["unavailable", "unknown", None])
def test_build_unavailable_entity(state):
    assert w.build_weather("weather.forecast_home", {"state": state}, None, date(2026, 11, 19)) == {"available": False}


# ---------------------------------------------------------------- Zwischenspeicher und Fehler

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_cache_holds_15_minutes():
    calls = []
    clock = Clock()

    def fetch(entity, token):
        calls.append((entity, token))
        return {"available": True, "temp": len(calls)}

    cache = w.WeatherCache(fetch, clock, lambda: "weather.forecast_home", lambda: "geheim")
    assert cache.get()["temp"] == 1
    clock.t += 14 * 60
    assert cache.get()["temp"] == 1
    clock.t += 61
    assert cache.get()["temp"] == 2
    assert calls[0] == ("weather.forecast_home", "geheim")
    assert "updated_at" in cache.get()


def test_cache_without_entity_or_token():
    called = []
    off = w.WeatherCache(lambda e, t: called.append(1), Clock(), lambda: None, lambda: "geheim")
    assert off.get() == {"available": False}
    no_token = w.WeatherCache(lambda e, t: called.append(1), Clock(), lambda: "weather.forecast_home", lambda: None)
    assert no_token.get() == {"available": False}
    assert called == []


def test_cache_error_is_quiet_and_logged_once(caplog):
    clock = Clock()

    def broken(entity, token):
        raise OSError("Zeitüberschreitung")

    cache = w.WeatherCache(broken, clock, lambda: "weather.forecast_home", lambda: "geheim")
    with caplog.at_level("WARNING"):
        assert cache.get() == {"available": False}
        clock.t += 15 * 60
        assert cache.get() == {"available": False}
        clock.t += 60
        cache._at = -1e12            # erzwingt neuen Abruf innerhalb der Sperrzeit für die Meldung
        assert cache.get() == {"available": False}
    assert sum("nicht lesbar" in r.message for r in caplog.records) == 2


def test_token_from_environment(monkeypatch):
    monkeypatch.setenv("SUPERVISOR_TOKEN", " abc ")
    assert w.supervisor_token() == "abc"


def test_fetch_uses_supervisor_api(monkeypatch):
    seen = []

    def fake_request(url, token, body=None):
        seen.append((url, body))
        if "states" in url:
            return STATE
        return forecast({"datetime": "2026-11-19T06:00:00+00:00", "temperature": 9, "templow": 4})

    monkeypatch.setattr(w, "_request", fake_request)
    data = w.fetch_weather("weather.forecast_home", "geheim", today=date(2026, 11, 19))
    assert data["max"] == 9 and data["min"] == 4
    assert seen[0] == ("http://supervisor/core/api/states/weather.forecast_home", None)
    assert seen[1] == ("http://supervisor/core/api/services/weather/get_forecasts?return_response",
                       {"entity_id": "weather.forecast_home", "type": "daily"})


def test_fetch_without_forecast_still_shows_weather(monkeypatch):
    def fake_request(url, token, body=None):
        if "states" in url:
            return STATE
        raise OSError("400")

    monkeypatch.setattr(w, "_request", fake_request)
    data = w.fetch_weather("weather.forecast_home", "geheim", today=date(2026, 11, 19))
    assert data["available"] is True and data["max"] is None
