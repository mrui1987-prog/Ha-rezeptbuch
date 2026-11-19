"""Modul 08: Mittelsmann – Zustand, Offline-Regel, Abo, Befehle (M08-4, M08-7, M08-9)."""

import asyncio
import json
import logging

import pytest

from app.scales import hub as h
from app.scales.hub import ScaleHub

TOPIC = "rezeptbuch/v1/station/{}/scale/state"


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.n = 0

    def __call__(self):
        return self.t

    def iso(self):
        self.n += 1
        return f"2026-11-19T08:00:{self.n:02d}.000Z"


def payload(station=1, **over):
    data = {"v": 2, "station": station, "status": "ok", "weight_g": 500, "stable": True,
            "scale_stable": True, "net": False, "capacity_g": 30000, "resolution_g": 1,
            "ts": "2026-11-19T07:00:00.000+00:00"}
    data.update(over)
    return json.dumps(data).encode()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def hub(clock):
    sent = []
    hub = ScaleHub(clock=clock, now_iso=clock.iso)
    hub.sent = sent
    hub.set_publisher(lambda topic, data: sent.append((topic, data)) or True)
    hub.set_stations({1: ("Waage 1", True), 2: ("Waage 2", False)})
    hub.set_mqtt(h.MQTT_CONNECTED)
    hub.handle_availability(b"online")
    return hub


def drain(queue):
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


def test_start_offline_until_first_state(clock):
    hub = ScaleHub(clock=clock, now_iso=clock.iso)
    hub.set_stations({1: ("Waage 1", True), 2: ("Waage 2", False)})
    s = hub.current_state(1)
    assert s.status == "offline" and s.offline_reason == "broker" and s.offline_since
    assert [x.station for x in hub.snapshot()] == [1, 2]


def test_state_received(hub):
    hub.handle_state(TOPIC.format(1), payload(weight_g=1234))
    s = hub.current_state(1)
    assert (s.status, s.weight_g, s.stable, s.offline_reason, s.offline_since) == ("ok", 1234, True, None, None)
    assert s.configured and s.name == "Waage 1" and s.received_at


def test_silent_after_3s_and_back(hub, clock):
    hub.handle_state(TOPIC.format(1), payload())
    clock.t += 3.0
    hub.check_silence()
    assert hub.current_state(1).status == "ok"
    clock.t += 0.1
    hub.check_silence()
    s = hub.current_state(1)
    assert s.status == "offline" and s.offline_reason == "silent" and s.weight_g is None
    since = s.offline_since
    hub.handle_state(TOPIC.format(1), payload())
    assert hub.current_state(1).status == "ok" and hub.current_state(1).offline_since is None
    assert since


def test_scale_offline_reason(hub):
    hub.handle_state(TOPIC.format(1), payload(status="offline", weight_g=None))
    assert hub.current_state(1).offline_reason == "scale"


def test_invalid_and_error_are_not_offline(hub):
    hub.handle_state(TOPIC.format(1), payload(status="invalid", weight_g=None))
    assert hub.current_state(1).status == "invalid"
    hub.handle_state(TOPIC.format(1), payload(status="error", weight_g=None))
    assert hub.current_state(1).status == "error"


def test_bridge_offline_all_stations(hub):
    hub.handle_state(TOPIC.format(1), payload())
    hub.handle_state(TOPIC.format(2), payload(station=2))
    hub.handle_availability(b"offline")
    assert {s.offline_reason for s in hub.snapshot()} == {"bridge"}
    assert hub.link() == {"mqtt": "connected", "bridge": "offline"}
    hub.handle_availability(b"online")
    hub.handle_state(TOPIC.format(1), payload())
    assert hub.current_state(1).status == "ok"


def test_broker_down_all_stations_and_bridge_unknown(hub):
    hub.handle_state(TOPIC.format(1), payload())
    hub.set_mqtt(h.MQTT_DISCONNECTED)
    assert hub.current_state(1).offline_reason == "broker"
    assert hub.link() == {"mqtt": "disconnected", "bridge": "unknown"}


def test_offline_since_kept_when_reason_changes(hub, clock):
    hub.handle_state(TOPIC.format(1), payload(status="offline", weight_g=None))
    since = hub.current_state(1).offline_since
    hub.handle_availability(b"offline")
    s = hub.current_state(1)
    assert s.offline_reason == "bridge" and s.offline_since == since


def test_subscribe_gets_changes_only(hub, clock):
    async def run():
        q = hub.subscribe()
        hub.handle_state(TOPIC.format(1), payload(weight_g=100))
        hub.handle_state(TOPIC.format(1), payload(weight_g=100, ts="2026-11-19T07:00:00.500+00:00"))  # nur Zeit neu
        hub.handle_state(TOPIC.format(1), payload(weight_g=101))
        events = drain(q)
        hub.unsubscribe(q)
        hub.handle_state(TOPIC.format(1), payload(weight_g=102))
        return events, drain(q)
    events, after = asyncio.run(run())
    assert [e["weight_g"] for e in events] == [100, 101]
    assert all(e["type"] == "scale" for e in events)
    assert after == []


def test_link_event(hub):
    async def run():
        q = hub.subscribe()
        hub.handle_availability(b"offline")
        return drain(q)
    events = asyncio.run(run())
    assert events[0] == {"type": "link", "mqtt": "connected", "bridge": "offline"}
    assert any(e["type"] == "scale" and e["offline_reason"] == "bridge" for e in events)


def test_queue_overflow_drops_oldest(hub, monkeypatch):
    monkeypatch.setattr(h, "QUEUE_SIZE", 3)
    async def run():
        q = hub.subscribe()
        for w in range(10):
            hub.handle_state(TOPIC.format(1), payload(weight_g=w))
        return drain(q)
    assert [e["weight_g"] for e in asyncio.run(run())] == [7, 8, 9]


def test_bad_messages_logged_throttled(hub, clock, caplog):
    with caplog.at_level(logging.WARNING, logger="rezeptbuch.scales"):
        hub.handle_state(TOPIC.format(1), b"kaputt")
        hub.handle_state(TOPIC.format(1), b"kaputt")
        clock.t += 61
        hub.handle_state(TOPIC.format(1), b"kaputt")
        hub.handle_state(TOPIC.format(1), payload(v=1))
    texts = [r.getMessage() for r in caplog.records if "verworfen" in r.getMessage()]
    assert len(texts) == 3
    assert hub.current_state(1).offline_reason == "silent"   # nichts Gültiges angekommen


def test_handle_message_dispatch(hub):
    hub.handle_message("rezeptbuch/v1/scale_bridge/availability", b"offline")
    assert hub.link()["bridge"] == "offline"
    hub.handle_message("rezeptbuch/v1/scale_bridge/availability", b"online")
    hub.handle_message(TOPIC.format(1), payload(weight_g=7))
    assert hub.current_state(1).weight_g == 7


# ------------------------------------------------------------ Befehle


def test_command_sent(hub):
    hub.handle_state(TOPIC.format(1), payload())
    assert hub.send_command(1, "tare") == "sent"
    topic, data = hub.sent[-1]
    assert topic == "rezeptbuch/v1/station/1/scale/cmd" and json.loads(data) == {"v": 2, "cmd": "tare"}


def test_command_offline(hub):
    assert hub.send_command(1, "zero") == "offline"      # noch kein Zustand
    assert hub.sent == []


def test_command_invalid_state_allowed(hub):
    hub.handle_state(TOPIC.format(1), payload(status="invalid", weight_g=None))
    assert hub.send_command(1, "zero") == "sent"         # Z07-2: entscheidet Add-on 2


def test_command_not_configured(hub):
    hub.handle_state(TOPIC.format(2), payload(station=2))
    assert hub.current_state(2).status == "ok"           # wird angezeigt (M08-9)
    assert hub.send_command(2, "tare") == "not_configured"


def test_command_mqtt_down(hub):
    hub.handle_state(TOPIC.format(1), payload())
    hub.set_mqtt(h.MQTT_DISCONNECTED)
    assert hub.send_command(1, "tare") == "mqtt_down"
    hub.set_mqtt(h.MQTT_CONNECTED)
    hub.handle_state(TOPIC.format(1), payload())
    hub.set_publisher(lambda t, p: False)
    assert hub.send_command(1, "tare") == "mqtt_down"


def test_command_unknown_station(clock):
    hub = ScaleHub(clock=clock, now_iso=clock.iso)
    assert hub.send_command(1, "tare") == "unknown_station"
    with pytest.raises(ValueError):
        hub.send_command(1, "print")


def test_station_list_changes(hub):
    hub.set_stations({1: ("Waage 1", True), 2: ("Waage 2", True)})
    assert hub.current_state(2).configured
    hub.set_stations({1: ("Waage 1", True)})
    assert [s.station for s in hub.snapshot()] == [1]
    hub.set_stations({1: ("Waage 1", True), 7: ("x", True)})
    assert [s.station for s in hub.snapshot()] == [1]


def test_state_is_immutable(hub):
    s = hub.current_state(1)
    with pytest.raises(Exception):
        s.weight_g = 5  # type: ignore[misc]
