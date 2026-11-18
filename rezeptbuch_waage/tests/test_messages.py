import json
from datetime import datetime, timezone

import pytest

from app.messages import (
    AVAILABILITY_TOPIC,
    SCHEMA_VERSION,
    CommandError,
    cmd_topic,
    parse_command,
    state_payload,
    state_topic,
)

TS = datetime(2026, 11, 18, 20, 0, 0, 123456, tzinfo=timezone.utc)


def test_schema_version_2():
    assert SCHEMA_VERSION == 2


def test_topics():
    assert state_topic(1) == "rezeptbuch/v1/station/1/scale/state"
    assert cmd_topic(2) == "rezeptbuch/v1/station/2/scale/cmd"
    assert AVAILABILITY_TOPIC == "rezeptbuch/v1/scale_bridge/availability"


@pytest.mark.parametrize("station", [0, 3])
def test_topic_invalid(station):
    with pytest.raises(ValueError):
        state_topic(station)
    with pytest.raises(ValueError):
        cmd_topic(station)


def test_payload_ok_schema_2():
    data = json.loads(state_payload(1, "ok", 9500, True, True, False, ts=TS))
    assert data == {
        "v": 2, "station": 1, "status": "ok", "weight_g": 9500, "stable": True,
        "scale_stable": True, "net": False, "capacity_g": 30000, "resolution_g": 1,
        "ts": "2026-11-18T20:00:00.123+00:00",
    }


def test_payload_negative_weight():
    data = json.loads(state_payload(1, "ok", -12, False, False, False, ts=TS))
    assert data["weight_g"] == -12


@pytest.mark.parametrize("status", ["invalid", "offline", "error"])
def test_not_ok_has_no_weight_and_never_stable(status):
    data = json.loads(state_payload(2, status, 500, True, True, True, 15000, 2, ts=TS))
    assert data["weight_g"] is None
    assert data["stable"] is False
    assert data["scale_stable"] is None
    assert data["net"] is None
    assert data["capacity_g"] == 15000 and data["resolution_g"] == 2


def test_ok_requires_weight():
    with pytest.raises(ValueError):
        state_payload(1, "ok", None)


def test_invalid_status():
    with pytest.raises(ValueError):
        state_payload(1, "kaputt", 0)


def test_ts_converted_to_utc():
    from datetime import timedelta
    local = datetime(2026, 11, 18, 21, 0, tzinfo=timezone(timedelta(hours=1)))
    assert json.loads(state_payload(1, "offline", ts=local))["ts"] == "2026-11-18T20:00:00.000+00:00"


@pytest.mark.parametrize("payload,cmd", [
    (b'{"v":2,"cmd":"tare"}', "tare"),
    ('{"v": 2, "cmd": "zero"}', "zero"),
])
def test_parse_command(payload, cmd):
    assert parse_command(payload) == cmd


@pytest.mark.parametrize("payload", [
    b"T", b'{"v":1,"cmd":"tare"}', b'{"v":2,"cmd":"print"}', b"[]", b"\xff",
])
def test_parse_command_rejects(payload):
    with pytest.raises(CommandError):
        parse_command(payload)
