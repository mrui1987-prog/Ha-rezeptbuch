"""Tests für den Waveshare-Ersatz (tools/waagen_simulator)."""

import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import simulator as tool  # noqa: E402
from app.config import StationConfig  # noqa: E402  (Pfad setzt simulator.py)
from app.kern import parse_line  # noqa: E402
from app.main import StationRun, dispatch_commands, handle_command  # noqa: E402
from app.station import StationMonitor  # noqa: E402
from app.transport_tcp import TcpTransport  # noqa: E402


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 10))


async def start(scale, interval=0.01):
    sim = tool.FakeWaveshare(scale, interval_s=interval)
    server = await sim.serve("127.0.0.1", 0)
    return sim, server, server.sockets[0].getsockname()[1]


async def read_reading(reader):
    line = (await reader.readline()).decode().rstrip("\r\n")
    return parse_line(line)


async def wait_until(cond, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError("Bedingung nicht erreicht")
        await asyncio.sleep(0.01)


def test_args_defaults():
    a = tool.parse_args([])
    assert a.port == 8899 and a.host == "0.0.0.0" and a.fest is None
    assert tool.parse_args(["--fest", "2500", "--port", "9000"]).fest == 2500


def test_fixed_scale_lines():
    scale = tool.FixedScale(2500)
    assert scale.line(0) == "ST,G    2.500kg"
    assert scale.line(55.0) == "ST,G    2.500kg"    # kein Ausfall


def test_sends_lines_and_executes_tare_zero():
    async def body():
        sim, server, port = await start(tool.FixedScale(1000))
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        r = await read_reading(reader)
        assert r.weight_g == 1000 and not r.net
        writer.write(b"T\r\n")
        await writer.drain()
        await wait_until(lambda: sim.commands == ["tare"])
        await reader.readline()                       # evtl. Zeile davor
        r = await read_reading(reader)
        assert r.net and r.weight_g == 0
        writer.write(b"Z")                            # auch ohne CR LF
        await writer.drain()
        await wait_until(lambda: sim.commands == ["tare", "zero"])
        await reader.readline()
        r = await read_reading(reader)
        assert not r.net and r.weight_g == 0
        writer.write(b"X\r\n")                        # unbekannt → ignoriert
        await writer.drain()
        await asyncio.sleep(0.05)
        assert sim.commands == ["tare", "zero"]
        writer.close()
        await sim.close(server)

    run(body())


def test_two_clients_get_same_lines():
    async def body():
        sim, server, port = await start(tool.FixedScale(77))
        r1, w1 = await asyncio.open_connection("127.0.0.1", port)
        r2, w2 = await asyncio.open_connection("127.0.0.1", port)
        assert (await read_reading(r1)).weight_g == 77
        assert (await read_reading(r2)).weight_g == 77
        w1.close()
        await asyncio.sleep(0.05)
        assert (await read_reading(r2)).weight_g == 77
        w2.close()
        await sim.close(server)

    run(body())


def test_addon_tcp_way_end_to_end():
    """Add-on (TCP-Anschluss, Station, Befehle) gegen den Simulator."""
    async def body():
        sim, server, port = await start(tool.FixedScale(30), interval=0.02)
        mon = StationMonitor(StationConfig(station=1, enabled=True,
                                           host="127.0.0.1", port=port))
        tcp = TcpTransport(mon)
        task = asyncio.create_task(tcp.run())
        loop = asyncio.get_running_loop()
        await wait_until(lambda: mon.status(loop.time()) == "ok")
        assert mon.state(loop.time())["weight_g"] == 30

        # zero (leere Waage, ±50 g, Z07-1) und gleich danach tare: tare wartet 1 s
        assert handle_command(mon, b'{"v":2,"cmd":"zero"}', clock=loop.time)
        assert handle_command(mon, b'{"v":2,"cmd":"tare"}', clock=loop.time)
        runs = [StationRun(mon, send=tcp.send_command)]
        dispatch_commands(runs, loop.time())
        await wait_until(lambda: mon.state(loop.time())["weight_g"] == 0)
        assert mon.state(loop.time())["net"] is False
        assert sim.commands == ["zero"]
        dispatch_commands(runs, loop.time())          # zu früh
        await asyncio.sleep(0.1)
        assert sim.commands == ["zero"]
        await asyncio.sleep(1.0)
        dispatch_commands(runs, loop.time())
        await wait_until(lambda: sim.commands == ["zero", "tare"])
        await wait_until(lambda: mon.state(loop.time())["net"] is True)
        # mit Tara aktiv wird zero verworfen (Z07-1)
        assert handle_command(mon, b'{"v":2,"cmd":"zero"}', clock=loop.time) is False

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await sim.close(server)

    run(body())
