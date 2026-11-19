"""Stationsoberfläche (Modul 10 Teil C1): Seiten, gemeinsame Dateien, Wetter-Endpunkt, sichere Ausgabe."""

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.display.router import get_weather_cache  # noqa: E402,F401
from app.main import app  # noqa: E402

client = TestClient(app)
STATIC = Path(__file__).resolve().parents[1] / "app" / "web" / "static"


def test_start_page_offers_station_choice():
    res = client.get("/")
    assert res.status_code == 200
    assert "rezeptbuch_station" in res.text and 'href="ui/common.css"' in res.text


@pytest.mark.parametrize("station", [1, 2])
def test_station_pages(station):
    res = client.get(f"/station/{station}")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    # relative Pfade (HA-Ingress, K10-2)
    assert 'href="../ui/common.css"' in res.text and 'src="../ui/common.js"' in res.text


@pytest.mark.parametrize("path", ["/station/0", "/station/3"])
def test_unknown_station(path):
    assert client.get(path).status_code == 404


def test_ui_files():
    css = client.get("/ui/common.css")
    js = client.get("/ui/common.js")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript")
    assert client.get("/ui/../main.py").status_code == 404
    assert client.get("/ui/fremd.js").status_code == 404


def test_weather_endpoint_without_home_assistant(monkeypatch):
    class Fake:
        def get(self):
            return {"available": False}

    monkeypatch.setattr(app.state, "weather", Fake(), raising=False)
    res = client.get("/api/v1/display/weather")
    assert res.status_code == 200 and res.json() == {"available": False}


@pytest.mark.parametrize("name", ["station.html", "start.html", "ui/common.js"])
def test_no_browser_dialogs_and_no_html_injection(name):
    text = (STATIC / name).read_text(encoding="utf-8")
    assert not re.search(r"\b(alert|confirm|prompt)\s*\(", text), "keine Browser-Dialoge (iOS-App)"
    assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "eval(" not in text


def test_corner_keeps_clock_below():
    # M10-15 (geändert 15:31): oben Datum und Wetter (Bild-im-Bild darf überdecken), Uhrzeit darunter frei
    text = (STATIC / "station.html").read_text(encoding="utf-8")
    corner = text[text.index('<div id="corner">'):text.index("</div>\n<header")]
    assert corner.index('id="date"') < corner.index('id="weather"') < corner.index('id="clock"')


def test_layout_0_10_6():
    # Zutat oben groß, Infotafel rechts, ausblendbare untere Leiste, Kompaktansicht (Michael 17:27–18:01)
    text = (STATIC / "station.html").read_text(encoding="utf-8")
    for needle in ('id="n-title"', 'id="head"', 'id="s-more"', 'id="b-compact"', 'id="compact"', "bar-hidden"):
        assert needle in text, needle


def test_compact_buttons_0_10_9():
    # Kompaktansicht: Tara, Behälter, Behälter wechseln, Zutat überspringen oben (Michael 21:43)
    text = (STATIC / "station.html").read_text(encoding="utf-8")
    for needle in ('id="c-tara"', 'id="c-cont"', 'id="c-change"', 'id="c-skip"', 'id="c-ack"', 'id="c-exit"', "function skipCurrent"):
        assert needle in text, needle
