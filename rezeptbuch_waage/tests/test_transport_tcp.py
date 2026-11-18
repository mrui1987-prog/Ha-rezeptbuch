"""TCP-Anschluss gegen einen lokalen Testserver (Waveshare-Ersatz)."""

import asyncio
import contextlib

from app.config import StationConfig
from app.kern import format_line
from app.station import StationMonitor
from app.transport_tcp import TcpTransport


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 10))


async def wait_until(cond, timeout=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError("Bedingung nicht erreicht")
        await asyncio.sleep(0.01)


def make_monitor(port):
    return StationMonitor(StationConfig(station=1, enabled=True, host="127.0.0.1", port=port))


def test_reads_lines_split_over_packets():
    async def body():
        async def handler(reader, writer):
            for chunk in (b"ST,G   ", b" 0.077kg\r\nUS,G    0.0", b"91kg\r\n"):
                writer.write(chunk)
                await writer.drain()
                await asyncio.sleep(0.02)
            await asyncio.sleep(5)

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        mon = make_monitor(port)
        task = asyncio.create_task(TcpTransport(mon).run())
        await wait_until(lambda: mon._last_reading is not None and mon._last_reading.weight_g == 91)
        assert mon.connected is True
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        server.close()

    run(body())


def test_reconnects_after_disconnect():
    async def body():
        count = 0

        async def handler(reader, writer):
            nonlocal count
            count += 1
            writer.write((format_line(count) + "\r\n").encode())
            await writer.drain()
            writer.close()  # Waveshare trennt

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        mon = make_monitor(port)
        transport = TcpTransport(mon, backoff=(0.01,))
        task = asyncio.create_task(transport.run())
        await wait_until(lambda: transport.connects >= 3)
        assert mon._last_reading.weight_g >= 2
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        server.close()

    run(body())


def test_retries_until_server_appears(caplog):
    async def body():
        probe = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = probe.sockets[0].getsockname()[1]
        probe.close()
        await probe.wait_closed()

        mon = make_monitor(port)
        transport = TcpTransport(mon, backoff=(0.02,))
        task = asyncio.create_task(transport.run())
        await asyncio.sleep(0.2)                   # mehrere Fehlversuche
        assert transport.connects == 0 and not mon.connected

        async def handler(reader, writer):
            writer.write(b"-----\r\n")
            await writer.drain()
            await asyncio.sleep(5)

        server = await asyncio.start_server(handler, "127.0.0.1", port)
        await wait_until(lambda: mon._last_reading is not None)
        assert mon._last_reading.kind == "invalid"
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        server.close()

    import logging
    with caplog.at_level(logging.WARNING, logger="rezeptbuch_waage"):
        run(body())
    # „keine Verbindung“ nur einmal je Ausfall, nicht bei jedem Versuch
    assert caplog.text.count("keine Verbindung") == 1


def test_idle_connection_is_rebuilt():
    async def body():
        count = 0

        async def handler(reader, writer):
            nonlocal count
            count += 1
            await asyncio.sleep(5)                 # Verbindung hängt, keine Daten

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        mon = make_monitor(port)
        transport = TcpTransport(mon, backoff=(0.01,), idle_timeout_s=0.1)
        task = asyncio.create_task(transport.run())
        await wait_until(lambda: transport.connects >= 2)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        server.close()

    run(body())


def test_default_idle_timeout_is_twice_offline():
    mon = StationMonitor(StationConfig(station=1, enabled=True, host="h", offline_after_s=5))
    assert TcpTransport(mon).idle_timeout_s == 10
