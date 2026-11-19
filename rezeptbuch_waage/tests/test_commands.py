"""Befehle tare/zero: Warteschlange, Annahme, Senden je Anschluss (docs/waage.md 6.3)."""

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timezone

import pytest

from app.commands import MERGED, QUEUED, WIRE, CommandQueue
from app.config import StationConfig
from app.kern import format_line, parse_line
from app.main import StationRun, dispatch_commands, handle_command, listen_commands
from app.simulator import SimulatedScale, SimulatorTransport
from app.station import StationMonitor
from app.transport_mqtt import MqttRawTransport
from app.transport_tcp import TcpTransport

WALL = datetime(2026, 11, 19, 6, 0, tzinfo=timezone.utc)


def live_monitor(grams=0, net=False, **kw):
    """Station, die gerade eine Zeile geliefert hat (Status ok bei t=0)."""
    cfg = StationConfig(station=1, enabled=True, host="h", **kw)
    mon = StationMonitor(cfg)
    mon.feed((format_line(grams, net=net) + "\r\n").encode(), 0.0, WALL)
    return mon


def cmd(name, v=2):
    return json.dumps({"v": v, "cmd": name}).encode()


# --- Warteschlange ----------------------------------------------------------

def test_queue_first_command_immediately():
    q = CommandQueue()
    assert q.add("tare") == QUEUED
    assert q.ready(0.0) and q.pop(0.0) == "tare"
    assert not q.ready(0.1)


def test_queue_min_interval_one_second():
    q = CommandQueue()
    q.add("tare")
    q.pop(10.0)
    q.add("zero")
    assert not q.ready(10.99)
    assert q.ready(11.0)
    assert q.pop(11.0) == "zero"


def test_queue_merges_duplicates_and_keeps_order():
    q = CommandQueue()
    q.add("tare")
    q.pop(0.0)
    assert q.add("zero") == QUEUED
    assert q.add("tare") == QUEUED
    assert q.add("zero") == MERGED
    assert q.add("tare") == MERGED
    assert q.pending == ["zero", "tare"]
    assert q.pop(1.0) == "zero" and q.pop(2.0) == "tare"


def test_queue_rejects_unknown():
    with pytest.raises(ValueError):
        CommandQueue().add("print")


def test_wire_format():
    assert WIRE == {"tare": b"T\r\n", "zero": b"Z\r\n"}


# --- Annahme an der Station -------------------------------------------------

def test_offline_station_rejects(caplog):
    mon = StationMonitor(StationConfig(station=1, enabled=True, host="h"))
    with caplog.at_level(logging.WARNING, logger="rezeptbuch_waage"):
        assert mon.submit_command("tare", 0.0) is False
    assert "verworfen" in caplog.text and "offline" in caplog.text
    assert mon.commands.pending == []


def test_accepted_when_ok_invalid_or_error():
    mon = live_monitor()
    assert mon.submit_command("tare", 0.1)
    mon = StationMonitor(StationConfig(station=1, enabled=True, host="h"))
    mon.feed(b"-----\r\n", 0.0, WALL)                     # invalid
    assert mon.status(0.1) == "invalid"
    assert mon.submit_command("tare", 0.1)
    assert mon.submit_command("zero", 0.1)                 # Z07-2: bei invalid erlaubt
    mon = StationMonitor(StationConfig(station=1, enabled=True, host="h"))
    mon.feed(b"xx\r\n", 0.0, WALL)
    mon.feed(b"xx\r\n", 3.5, WALL)                         # 3 s nur unlesbar → error
    assert mon.status(3.6) == "error"
    assert mon.submit_command("tare", 3.6)
    assert mon.submit_command("zero", 3.6) is False


def test_broken_config_rejects():
    mon = StationMonitor(StationConfig(station=1, enabled=True, errors=("x",)))
    assert mon.submit_command("tare", 0.0) is False


def test_next_command_spacing():
    mon = live_monitor()
    mon.submit_command("tare", 0.0)
    mon.submit_command("zero", 0.0)
    assert mon.next_command(0.1) == "tare"
    assert mon.next_command(0.5) is None
    assert mon.next_command(1.1) == "zero"
    assert mon.next_command(2.5) is None


def test_waiting_commands_dropped_when_offline(caplog):
    mon = live_monitor()
    mon.submit_command("tare", 0.0)
    mon.submit_command("zero", 0.0)
    assert mon.next_command(0.0) == "tare"
    with caplog.at_level(logging.WARNING, logger="rezeptbuch_waage"):
        assert mon.next_command(6.0) is None              # 5 s ohne Zeile → offline
    assert mon.commands.pending == []
    assert "wartender Befehl Nullstellen verworfen" in caplog.text


# --- Eingang über MQTT ------------------------------------------------------

@pytest.mark.parametrize("payload, reason", [
    (b"T\r\n", "kein gültiges JSON"),
    (b"[1]", "kein JSON-Objekt"),
    (cmd("tare", v=1), "falsche Version"),
    (cmd("print"), "unbekannter Befehl"),
])
def test_handle_command_rejects_bad_payload(payload, reason, caplog):
    mon = live_monitor()
    with caplog.at_level(logging.WARNING, logger="rezeptbuch_waage"):
        assert handle_command(mon, payload, clock=lambda: 0.1) is False
    assert reason in caplog.text
    assert mon.commands.pending == []


def test_handle_command_queues():
    mon = live_monitor()
    assert handle_command(mon, cmd("tare"), clock=lambda: 0.1)
    assert mon.commands.pending == ["tare"]


class FakeBridge:
    def __init__(self):
        self.subs = {}
        self.published = []
        self.connected = True

    def subscribe(self, topic, cb):
        self.subs[topic] = cb

    def publish(self, topic, payload, qos=0, retain=False):
        if not self.connected:
            return False
        self.published.append((topic, payload))
        return True


def test_listen_commands_subscribes_station_topic():
    async def body():
        loop = asyncio.get_running_loop()
        bridge = FakeBridge()
        mon = live_monitor()
        listen_commands(StationRun(mon), bridge, loop)
        cb = bridge.subs["rezeptbuch/v1/station/1/scale/cmd"]
        mon.feed((format_line(20) + "\r\n").encode(), loop.time(), WALL)
        # Aufruf wie aus dem paho-Thread
        await asyncio.to_thread(cb, cmd("zero"))
        await asyncio.sleep(0.05)
        assert mon.commands.pending == ["zero"]

    asyncio.run(body())


# --- Senden -----------------------------------------------------------------

def test_dispatch_sends_and_logs(caplog):
    mon = live_monitor()
    sent = []
    run = StationRun(mon, send=lambda c: sent.append(c) or True)
    mon.submit_command("tare", 0.0)
    mon.submit_command("zero", 0.0)
    with caplog.at_level(logging.INFO, logger="rezeptbuch_waage"):
        dispatch_commands([run], 0.1)
        dispatch_commands([run], 0.5)
        dispatch_commands([run], 1.2)
    assert sent == ["tare", "zero"]
    assert "Befehl Tara an die Waage gesendet" in caplog.text


def test_dispatch_without_connection_warns(caplog):
    mon = live_monitor()
    run = StationRun(mon, send=lambda c: False)
    mon.submit_command("tare", 0.0)
    with caplog.at_level(logging.WARNING, logger="rezeptbuch_waage"):
        dispatch_commands([run], 0.1)
    assert "nicht gesendet" in caplog.text
    assert mon.commands.pending == []


def test_dispatch_error_in_one_station_keeps_other():
    good, bad = live_monitor(), live_monitor()
    sent = []

    def boom(c):
        raise RuntimeError("kaputt")

    bad.submit_command("tare", 0.0)
    good.submit_command("zero", 0.0)
    dispatch_commands([StationRun(bad, send=boom),
                       StationRun(good, send=lambda c: sent.append(c) or True)], 0.1)
    assert sent == ["zero"]


def test_mqtt_way_publishes_on_waveshare_topic():
    bridge = FakeBridge()
    mon = live_monitor(connection="mqtt", raw_topic="rezeptbuch/test/waage1/raw",
                       cmd_topic="rezeptbuch/test/waage1/cmd")
    t = MqttRawTransport(mon, bridge, loop=None)
    assert t.send_command("tare")
    assert bridge.published == [("rezeptbuch/test/waage1/cmd", "T\r\n")]
    bridge.connected = False
    assert t.send_command("zero") is False


def test_simulator_executes_commands():
    async def body():
        clock = {"t": 100.0}
        cfg = StationConfig(station=1, enabled=True, driver="simulator")
        mon = StationMonitor(cfg)
        scale = SimulatedScale()
        sim = SimulatorTransport(mon, scale, clock=lambda: clock["t"], interval_s=0.01)
        assert sim.send_command("tare") is False           # noch nicht gestartet
        task = asyncio.create_task(sim.run())
        await asyncio.sleep(0.02)
        clock["t"] = 107.0                                  # Behälter 1 200 g
        assert sim.send_command("tare")
        assert scale.tare_g == 1200
        assert parse_line(scale.line(7.5)).net
        clock["t"] = 145.0                                  # leer → `-----`
        assert scale.line(45.0) == "-----"
        assert sim.send_command("zero")
        assert scale.tare_g is None and scale.line(45.0) == "ST,G    0.000kg"
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(body())


def test_tcp_way_writes_to_connection():
    async def body():
        received = bytearray()
        got = asyncio.Event()

        async def handler(reader, writer):
            writer.write((format_line(500) + "\r\n").encode())
            await writer.drain()
            while True:
                data = await reader.read(100)
                if not data:
                    break
                received.extend(data)
                if received.count(b"\r\n") >= 2:
                    got.set()

        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        mon = StationMonitor(StationConfig(station=1, enabled=True, host="127.0.0.1", port=port))
        tcp = TcpTransport(mon)
        assert tcp.send_command("tare") is False            # noch keine Verbindung
        task = asyncio.create_task(tcp.run())
        while mon.connected is not True:
            await asyncio.sleep(0.01)
        assert tcp.send_command("tare") and tcp.send_command("zero")
        await asyncio.wait_for(got.wait(), 3)
        assert bytes(received) == b"T\r\nZ\r\n"
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        server.close()

    asyncio.run(asyncio.wait_for(body(), 10))


# --- Z07-1/Z07-2: Nullstellen nur bei leerer Waage (0.7.5/0.7.6) ------------

@pytest.mark.parametrize("grams", [0, 50, -50, 13])
def test_zero_accepted_on_empty_scale(grams):
    mon = live_monitor(grams=grams)
    assert mon.submit_command("zero", 0.1)
    assert mon.next_command(0.1) == "zero"


@pytest.mark.parametrize("grams", [51, -51, 718, 9800])
def test_zero_rejected_with_load(grams, caplog):
    mon = live_monitor(grams=grams)
    with caplog.at_level(logging.WARNING, logger="rezeptbuch_waage"):
        assert mon.submit_command("zero", 0.1) is False
    assert f"Waage zeigt {grams} g" in caplog.text
    assert "bis ±50 g" in caplog.text
    assert mon.commands.pending == []


@pytest.mark.parametrize("grams", [0, 50, -50])
def test_zero_accepted_when_net_and_small(grams):
    mon = live_monitor(grams=grams, net=True)             # Tara an der Waage aktiv (Z07-2)
    assert mon.submit_command("zero", 0.1)
    assert mon.submit_command("tare", 0.1)                # Tara bleibt erlaubt


def test_zero_rejected_when_net_with_load(caplog):
    mon = live_monitor(grams=400, net=True)
    with caplog.at_level(logging.WARNING, logger="rezeptbuch_waage"):
        assert mon.submit_command("zero", 0.1) is False
    assert "Waage zeigt 400 g netto" in caplog.text


def test_zero_accepted_when_invalid_without_limit():
    mon = live_monitor(grams=9800)                        # Last, dann `-----`
    mon.feed(b"-----\r\n", 0.05, WALL)
    assert mon.status(0.1) == "invalid"
    assert mon.submit_command("zero", 0.1)                # Z07-2: ohne Grenze
    assert mon.next_command(0.1) == "zero"


def test_zero_rejected_when_error(caplog):
    mon = live_monitor(grams=0)
    for i in range(40):                                   # 4 s nur unlesbar
        mon.feed(b"xx\r\n", 0.1 + i * 0.1, WALL)
    assert mon.status(4.1) == "error"
    with caplog.at_level(logging.WARNING, logger="rezeptbuch_waage"):
        assert mon.submit_command("zero", 4.1) is False
    assert "kein gültiges Gewicht" in caplog.text


def test_zero_limit_configurable():
    assert live_monitor(grams=80, zero_limit_g=100).submit_command("zero", 0.1)
    assert live_monitor(grams=1, zero_limit_g=0).submit_command("zero", 0.1) is False
    assert live_monitor(grams=0, zero_limit_g=0).submit_command("zero", 0.1)


def test_waiting_zero_dropped_when_load_arrives(caplog):
    mon = live_monitor(grams=0)
    mon.submit_command("tare", 0.0)
    mon.submit_command("zero", 0.0)
    assert mon.next_command(0.0) == "tare"
    mon.feed((format_line(1200) + "\r\n").encode(), 0.5, WALL)   # Behälter aufgelegt
    with caplog.at_level(logging.WARNING, logger="rezeptbuch_waage"):
        assert mon.next_command(1.0) is None
    assert "wartender Befehl Nullstellen verworfen – Waage zeigt 1200 g brutto" in caplog.text
    assert mon.commands.pending == []


def test_tare_not_limited():
    assert live_monitor(grams=9800).submit_command("tare", 0.1)
