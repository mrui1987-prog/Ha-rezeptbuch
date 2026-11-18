import asyncio
import contextlib

from app.config import StationConfig
from app.kern import INVALID, WEIGHT, LineSplitter, parse_line
from app.simulator import CYCLE_S, SimulatedScale, SimulatorTransport
from app.station import StationMonitor


def readings(scale, start=0.0, end=CYCLE_S, step=0.1):
    out = []
    t = start
    while t < end - 1e-9:
        line = scale.line(t)
        out.append((round(t, 1), None if line is None else parse_line(line)))
        t += step
    return out


def test_all_lines_are_valid_kern_lines():
    for t, r in readings(SimulatedScale()):
        assert r is None or r.kind in (WEIGHT, INVALID), t


def test_cycle_contains_all_states():
    data = dict(readings(SimulatedScale()))
    assert data[2.0].weight_g == 0 and data[2.0].scale_stable
    assert data[7.0].weight_g == 1200
    assert 1200 < data[20.0].weight_g < 5000 and not data[20.0].scale_stable
    assert data[35.0].weight_g == 5000 and data[35.0].scale_stable
    assert data[40.0].kind == INVALID
    assert data[55.0] is None                       # Ausfall, keine Zeilen
    assert data[59.0].weight_g == 0


def test_repeats_every_60s():
    scale = SimulatedScale()
    assert scale.line(35.0) == scale.line(95.0)


def test_tare_and_zero():
    scale = SimulatedScale()
    scale.tare(7.0)                                 # Behälter 1 200 g
    r = parse_line(scale.line(7.5))
    assert r.net and r.weight_g == 0
    r = parse_line(scale.line(35.0))
    assert r.net and r.weight_g == 3800
    assert scale.line(45.0) == "-----"              # Behälter ab → negativ
    scale.zero(45.0)
    r = parse_line(scale.line(46.0))
    assert not r.net and r.weight_g == 0


def test_monitor_sees_stable_and_offline():
    scale = SimulatedScale()
    mon = StationMonitor(StationConfig(station=1, enabled=True, driver="simulator"))
    seen = {}
    t = 0.0
    while t < CYCLE_S:
        line = scale.line(t)
        if line is not None:
            mon.feed((line + "\r\n").encode(), t, None)
        st = mon.state(t)
        seen.setdefault((st["status"], st["stable"]), t)
        t = round(t + 0.1, 1)
    assert ("ok", True) in seen and ("ok", False) in seen
    assert ("invalid", False) in seen
    assert ("offline", False) in seen and seen[("offline", False)] > 50


def test_transport_feeds_monitor():
    async def body():
        mon = StationMonitor(StationConfig(station=2, enabled=True, driver="simulator"))
        task = asyncio.create_task(SimulatorTransport(mon, interval_s=0.01).run())
        await asyncio.sleep(0.1)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert mon._last_reading is not None and mon._last_reading.weight_g == 0

    asyncio.run(body())


def test_lines_survive_splitter():
    scale = SimulatedScale()
    stream = b"".join((scale.line(t / 10) or "").encode() + b"\r\n" for t in range(100))
    assert len(LineSplitter().feed(stream)) == 100
