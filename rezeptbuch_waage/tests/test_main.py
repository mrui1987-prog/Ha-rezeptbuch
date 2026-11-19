import asyncio
import json
import logging

from app.config import StationConfig, parse_options
from app.main import log_start, publish_loop, start_station, supervise
from app.station import StationMonitor


class FakeBridge:
    def __init__(self):
        self.published = []
        self.subs = {}

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, json.loads(payload)))
        return True

    def subscribe(self, topic, cb):
        self.subs[topic] = cb


def test_log_start_reports_errors(caplog):
    cfg = parse_options({"scale1_enabled": True, "scale2_enabled": True,
                         "scale2_driver": "simulator", "scale2_mode": "STC"})
    with caplog.at_level(logging.INFO, logger="rezeptbuch_waage"):
        log_start(cfg)
    assert "Waage 1 startet nicht" in caplog.text and "host" in caplog.text
    assert "Waage 2: Simulator" in caplog.text


def test_publish_loop_publishes_both_stations():
    async def body():
        bridge = FakeBridge()
        mons = [StationMonitor(StationConfig(station=1, enabled=True, host="h")),
                StationMonitor(StationConfig(station=2, enabled=True, errors=("x",)))]
        task = asyncio.create_task(publish_loop(mons, bridge))
        await asyncio.sleep(0.05)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        topics = {t: p["status"] for t, p in bridge.published}
        assert topics == {"rezeptbuch/v1/station/1/scale/state": "offline",
                          "rezeptbuch/v1/station/2/scale/state": "error"}

    asyncio.run(body())


def test_start_station_variants():
    async def body():
        loop = asyncio.get_running_loop()
        bridge = FakeBridge()
        bad = StationConfig(station=1, enabled=True, errors=("x",))
        r = start_station(bad, StationMonitor(bad), bridge, loop)
        assert r.tasks == [] and r.send is None
        mq = StationConfig(station=1, enabled=True, connection="mqtt", raw_topic="r", cmd_topic="c")
        r = start_station(mq, StationMonitor(mq), bridge, loop)
        assert r.tasks == [] and r.send is not None
        assert "r" in bridge.subs
        sim = StationConfig(station=2, enabled=True, driver="simulator")
        r = start_station(sim, StationMonitor(sim), bridge, loop)
        tasks = r.tasks
        assert len(tasks) == 1 and r.send is not None
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(body())


def test_supervise_restarts_after_error(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "RESTART_DELAY_S", 0)
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("kaputt")

    asyncio.run(supervise("Waage 1", flaky))
    assert len(calls) == 3
