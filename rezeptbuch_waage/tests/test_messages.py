import json
from datetime import datetime, timezone

import pytest

from app.messages import SCHEMA_VERSION, state_payload, state_topic

TS = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def test_topic():
    assert state_topic(1) == "rezeptbuch/v1/station/1/scale/state"
    assert state_topic(2) == "rezeptbuch/v1/station/2/scale/state"


@pytest.mark.parametrize("station", [0, 3])
def test_topic_invalid(station):
    with pytest.raises(ValueError):
        state_topic(station)


def test_payload_ok():
    data = json.loads(state_payload(1, 9500, True, ts=TS))
    assert data == {
        "v": SCHEMA_VERSION,
        "station": 1,
        "weight_g": 9500,
        "stable": True,
        "status": "ok",
        "ts": "2026-11-12T12:00:00+00:00",
    }


def test_offline_never_stable():
    data = json.loads(state_payload(2, None, True, "offline", ts=TS))
    assert data["stable"] is False
    assert data["weight_g"] is None


def test_ok_requires_weight():
    with pytest.raises(ValueError):
        state_payload(1, None, True, "ok")


def test_invalid_status():
    with pytest.raises(ValueError):
        state_payload(1, 0, False, "kaputt")
