"""Modul 08: REST-Waagenendpunkte, Live-Kanal, Health, Prüfseite (M08-5, M08-6, M08-10, M08-11)."""

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.scales import router as scales_router  # noqa: E402

TOPIC = "rezeptbuch/v1/station/{}/scale/state"


def payload(station=1, **over):
    data = {"v": 2, "station": station, "status": "ok", "weight_g": 1500, "stable": True,
            "scale_stable": True, "net": False, "capacity_g": 30000, "resolution_g": 1,
            "ts": "2026-11-19T08:00:00.000+00:00"}
    data.update(over)
    return json.dumps(data).encode()


async def _stop_connect_task(service):
    task = service._tasks[0]
    task.cancel()
    try:
        await task
    except BaseException:  # noqa: BLE001 – abgebrochen oder schon fertig
        pass


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REZEPTBUCH_DB", str(tmp_path / "rezeptbuch.db"))
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    with TestClient(app) as c:
        c.hub = app.state.scales.hub
        # Der Verbindungsversuch des Dienstes (ohne Supervisor → „unavailable“) darf den
        # nachgestellten MQTT-Stand der Tests nicht überschreiben: Aufgabe vorher beenden.
        c.portal.call(_stop_connect_task, app.state.scales)
        c.sent = []
        yield c


def connect_mqtt(client):
    """Stellt eine MQTT-Verbindung nach (alles in der Schleife des Servers)."""
    client.hub.set_publisher(lambda topic, data: client.sent.append((topic, data)) or True)
    client.portal.call(client.hub.set_mqtt, "connected")
    client.portal.call(client.hub.handle_availability, b"online")


def test_health_reports_mqtt_without_503(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["mqtt"] == "unavailable"


def test_stations_without_mqtt(client):
    r = client.get("/api/v1/stations")
    assert r.status_code == 200
    body = r.json()
    assert body["mqtt"] == "unavailable" and body["bridge"] == "unknown"
    st = {s["station"]: s for s in body["stations"]}
    assert st[1]["configured"] is True and st[2]["configured"] is False
    assert st[1]["status"] == "offline" and st[1]["offline_reason"] == "broker"


def test_station_scale_live_value(client):
    connect_mqtt(client)
    client.portal.call(client.hub.handle_state, TOPIC.format(1), payload(weight_g=2345))
    r = client.get("/api/v1/stations/1/scale")
    assert r.status_code == 200
    s = r.json()
    assert (s["status"], s["weight_g"], s["stable"], s["name"]) == ("ok", 2345, True, "Waage 1")
    assert client.get("/api/v1/health").json()["mqtt"] == "connected"


def test_station_unknown(client):
    assert client.get("/api/v1/stations/7/scale").status_code == 404
    assert client.post("/api/v1/stations/7/scale/tare").status_code == 404


def test_commands(client):
    # ohne MQTT
    r = client.post("/api/v1/stations/1/scale/tare")
    assert r.status_code == 503 and r.json()["code"] == "mqtt_down"
    connect_mqtt(client)
    # verbunden, aber noch kein Zustand → offline
    r = client.post("/api/v1/stations/1/scale/zero")
    assert r.status_code == 409 and r.json()["code"] == "offline"
    client.portal.call(client.hub.handle_state, TOPIC.format(1), payload())
    r = client.post("/api/v1/stations/1/scale/tare")
    assert r.status_code == 202 and r.json()["result"] == "sent"
    assert client.sent[-1][0] == "rezeptbuch/v1/station/1/scale/cmd"
    assert json.loads(client.sent[-1][1]) == {"v": 2, "cmd": "tare"}
    # Station 2 ist im Rezeptbuch nicht eingerichtet (M08-9, K08-5)
    client.portal.call(client.hub.handle_state, TOPIC.format(2), payload(station=2))
    r = client.post("/api/v1/stations/2/scale/zero")
    assert r.status_code == 409 and r.json()["code"] == "not_configured"
    assert client.get("/api/v1/stations/2/scale").json()["status"] == "ok"


def test_commands_need_no_pin(client):
    connect_mqtt(client)
    client.portal.call(client.hub.handle_state, TOPIC.format(1), payload())
    r = client.post("/api/v1/stations/1/scale/zero", headers={})
    assert r.status_code == 202


def test_live_snapshot_and_changes(client):
    with client.websocket_connect("/api/v1/live") as ws:
        first = ws.receive_json()
        assert first == {"type": "link", "mqtt": "unavailable", "bridge": "unknown"}
        snap = [ws.receive_json(), ws.receive_json()]
        assert [s["station"] for s in snap] == [1, 2] and all(s["type"] == "scale" for s in snap)
        connect_mqtt(client)
        seen = []
        while True:
            event = ws.receive_json()
            seen.append(event)
            if event["type"] == "link" and event["bridge"] == "online":
                break
        client.portal.call(client.hub.handle_state, TOPIC.format(1), payload(weight_g=777))
        while True:
            event = ws.receive_json()
            if event["type"] == "scale" and event["station"] == 1 and event["status"] == "ok":
                break
        assert event["weight_g"] == 777 and event["configured"] is True
    assert client.hub._subs == []          # Abo nach dem Schließen entfernt


def test_live_ping(client, monkeypatch):
    monkeypatch.setattr(scales_router, "PING_S", 0.05)
    with client.websocket_connect("/api/v1/live") as ws:
        for _ in range(3):
            ws.receive_json()               # link + 2 Stationen
        assert ws.receive_json() == {"type": "ping"}


def test_scales_page():
    plain = TestClient(app)
    r = plain.get("/admin/waagen")
    assert r.status_code == 200
    assert "Waagen – Verbindung prüfen" in r.text and "api/v1/" in r.text
    assert r.headers["cache-control"] == "no-store"


def test_other_pages_have_scales_tab():
    plain = TestClient(app)
    for path in ("/admin", "/admin/rezepte", "/admin/berechnung"):
        assert "Waagen" in plain.get(path).text
