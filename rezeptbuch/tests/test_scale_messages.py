"""Modul 08: Schema 2 lesen und prüfen (M08-8, docs/schnittstellen.md 5)."""

import json

import pytest

from app.scales import messages as m

TOPIC1 = "rezeptbuch/v1/station/1/scale/state"


def state(**over):
    data = {"v": 2, "station": 1, "status": "ok", "weight_g": 9500, "stable": True,
            "scale_stable": True, "net": False, "capacity_g": 30000, "resolution_g": 1,
            "ts": "2026-11-19T08:00:00.123+00:00"}
    data.update(over)
    return json.dumps(data).encode()


def test_ok_state():
    d = m.parse_state(TOPIC1, state())
    assert d == {"station": 1, "status": "ok", "weight_g": 9500, "stable": True, "scale_stable": True,
                 "net": False, "capacity_g": 30000, "resolution_g": 1, "ts": "2026-11-19T08:00:00.123+00:00"}


def test_negative_weight_accepted():
    assert m.parse_state(TOPIC1, state(weight_g=-12))["weight_g"] == -12


@pytest.mark.parametrize("status", ["invalid", "offline", "error"])
def test_non_ok_has_no_weight_and_not_stable(status):
    d = m.parse_state(TOPIC1, state(status=status, weight_g=None, stable=True, scale_stable=None, net=None))
    assert d["weight_g"] is None and d["stable"] is False and d["net"] is None and d["scale_stable"] is None


@pytest.mark.parametrize("payload, kind", [
    (b"kein json", "json"),
    (b"[1,2]", "json"),
    (b"\xff\xfe", "json"),
    (state(v=1), "version"),
    (state(station=2), "station"),
    (state(status="kaputt"), "status"),
    (state(weight_g=None), "field"),
    (state(weight_g="12"), "field"),
    (state(weight_g=True), "field"),
    (state(stable="ja"), "field"),
])
def test_rejected(payload, kind):
    with pytest.raises(m.MessageError) as exc:
        m.parse_state(TOPIC1, payload)
    assert exc.value.kind == kind


@pytest.mark.parametrize("topic", ["rezeptbuch/v1/station/3/scale/state", "rezeptbuch/test/waage1/raw",
                                   "rezeptbuch/v1/station/x/scale/state"])
def test_wrong_topic(topic):
    with pytest.raises(m.MessageError) as exc:
        m.parse_state(topic, state())
    assert exc.value.kind == "topic"


def test_station_from_topic():
    assert m.station_from_topic("rezeptbuch/v1/station/2/scale/state") == 2
    assert m.station_from_topic("rezeptbuch/v1/station/2/scale/cmd") is None


def test_availability():
    assert m.parse_availability(b"online") == "online"
    assert m.parse_availability("offline\n") == "offline"
    with pytest.raises(m.MessageError):
        m.parse_availability(b"vielleicht")


def test_command_payload_and_topic():
    assert json.loads(m.command_payload("tare")) == {"v": 2, "cmd": "tare"}
    assert m.cmd_topic(2) == "rezeptbuch/v1/station/2/scale/cmd"
    with pytest.raises(ValueError):
        m.command_payload("print")
    with pytest.raises(ValueError):
        m.cmd_topic(3)
