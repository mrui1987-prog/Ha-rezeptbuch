"""Einstiegspunkt der Waagen-Bridge (Add-on 2, docs/waage.md Abschnitt 2).

Liest die Konfiguration, verbindet sich mit dem MQTT-Broker (Letzter Wille),
startet je aktiver Waage den Anschluss (TCP, MQTT-Roh-Topic oder Simulator) und
meldet den Zustand nach Schema 2. Befehle `tare`/`zero` kommen über
`…/scale/cmd` und gehen mit Mindestabstand 1 s an die Waage. Ein Fehler an einer Waage berührt die andere
nicht; ein unerwarteter Fehler im Anschluss startet nur diesen neu.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from . import __version__
from .config import OPTIONS_FILE, AddonConfig, StationConfig, describe, load_options
from .commands import NAMES
from .messages import CommandError, cmd_topic, parse_command, state_topic
from .mqtt_client import CredentialsError, MqttBridge, fetch_credentials
from .simulator import SimulatorTransport
from .station import StationMonitor
from .transport_mqtt import MqttRawTransport
from .transport_tcp import TcpTransport

POLL_INTERVAL_S = 0.1
CREDENTIALS_RETRY_S = 30
RESTART_DELAY_S = 5

log = logging.getLogger("rezeptbuch_waage")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.getLogger("rezeptbuch_waage").setLevel(level.upper())


def log_start(cfg: AddonConfig) -> None:
    log.info("HA-Rezeptbuch Waage %s startet", __version__)
    for st in cfg.stations:
        if not st.enabled:
            log.info("%s: nicht aktiv", st.label)
            continue
        log.info(describe(st))
        for error in st.errors:
            log.error("%s startet nicht – %s", st.label, error)
        if st.ok and st.driver == "kern" and st.mode == "STC":
            log.info("%s: Sendemodus STC – die Waage sendet nur stabile Werte, "
                     "„instabil“ ist dann nicht sichtbar", st.label)


async def supervise(name: str, factory: Callable[[], Awaitable[None]]) -> None:
    """Startet einen Anschluss bei unerwartetem Fehler nach 5 s neu."""
    while True:
        try:
            await factory()
            return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("%s: unerwarteter Fehler, Neustart in %s s", name, RESTART_DELAY_S)
            await asyncio.sleep(RESTART_DELAY_S)


async def wait_for_credentials(stop: asyncio.Event) -> dict | None:
    while not stop.is_set():
        try:
            return await asyncio.to_thread(fetch_credentials)
        except CredentialsError as exc:
            log.error("MQTT: %s – neuer Versuch in %s s", exc, CREDENTIALS_RETRY_S)
        try:
            await asyncio.wait_for(stop.wait(), CREDENTIALS_RETRY_S)
        except asyncio.TimeoutError:
            pass
    return None


Sender = Callable[[str], bool]


@dataclass
class StationRun:
    """Laufende Station: Aufgaben des Anschlusses und Weg für Befehle."""

    monitor: StationMonitor
    tasks: list[asyncio.Task] = field(default_factory=list)
    send: Sender | None = None


def start_station(
    st: StationConfig,
    monitor: StationMonitor,
    bridge: MqttBridge,
    loop: asyncio.AbstractEventLoop,
) -> StationRun:
    run = StationRun(monitor)
    if not st.ok:
        return run
    if st.driver == "simulator":
        sim = SimulatorTransport(monitor)
        run.tasks.append(loop.create_task(supervise(st.label, sim.run)))
        run.send = sim.send_command
    elif st.connection == "tcp":
        tcp = TcpTransport(monitor)
        run.tasks.append(loop.create_task(supervise(st.label, tcp.run)))
        run.send = tcp.send_command
    else:
        raw = MqttRawTransport(monitor, bridge, loop)
        raw.start()
        run.send = raw.send_command
    return run


def handle_command(
    monitor: StationMonitor,
    payload: bytes,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Befehl aus `…/scale/cmd` prüfen und in die Warteschlange stellen."""
    try:
        cmd = parse_command(payload)
    except CommandError as exc:
        log.warning("%s: Befehl verworfen – %s: %r", monitor.cfg.label, exc,
                    bytes(payload)[:80])
        return False
    return monitor.submit_command(cmd, clock())


def listen_commands(
    run: StationRun,
    bridge: MqttBridge,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Befehls-Topic abonnieren; Aufruf aus dem paho-Thread an die Schleife geben."""
    monitor = run.monitor
    topic = cmd_topic(monitor.cfg.station)

    def on_message(payload: bytes) -> None:
        loop.call_soon_threadsafe(handle_command, monitor, bytes(payload))

    bridge.subscribe(topic, on_message)
    log.info("%s: Befehle auf %s", monitor.cfg.label, topic)


def dispatch_commands(runs: list[StationRun], now: float) -> None:
    """Sendet je Waage höchstens den nächsten fälligen Befehl."""
    for run in runs:
        try:
            cmd = run.monitor.next_command(now)
            if cmd is None:
                continue
            label = run.monitor.cfg.label
            if run.send is not None and run.send(cmd):
                log.info("%s: Befehl %s an die Waage gesendet", label, NAMES[cmd])
            else:
                log.warning("%s: Befehl %s nicht gesendet – keine Verbindung", label,
                            NAMES[cmd])
        except Exception:  # noqa: BLE001 – eine Waage darf die andere nicht stören
            log.exception("%s: Fehler beim Senden eines Befehls", run.monitor.cfg.label)


async def publish_loop(
    monitors: list[StationMonitor],
    bridge: MqttBridge,
    clock: Callable[[], float] = time.monotonic,
    runs: list[StationRun] | None = None,
) -> None:
    while True:
        now = clock()
        wall = datetime.now(timezone.utc)
        if runs:
            dispatch_commands(runs, now)
        for monitor in monitors:
            try:
                payload = monitor.poll(now, wall)
                if payload is not None:
                    bridge.publish(state_topic(monitor.cfg.station), payload)
            except Exception:  # noqa: BLE001 – eine Waage darf die andere nicht stören
                log.exception("%s: Fehler beim Melden", monitor.cfg.label)
        await asyncio.sleep(POLL_INTERVAL_S)


async def amain(options_path: Path = OPTIONS_FILE) -> None:
    cfg = load_options(options_path)
    setup_logging(cfg.log_level)
    log_start(cfg)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass

    if not cfg.active:
        log.warning("Keine Waage aktiv – „Waage 1 – aktiv“ in der Konfiguration "
                    "einschalten. Das Add-on wartet.")
        await stop.wait()
        return

    creds = await wait_for_credentials(stop)
    if creds is None:
        return
    bridge = MqttBridge(creds)
    bridge.start()

    monitors = [StationMonitor(st) for st in cfg.active]
    tasks: list[asyncio.Task] = []
    runs: list[StationRun] = []
    for st, monitor in zip(cfg.active, monitors):
        run = start_station(st, monitor, bridge, loop)
        runs.append(run)
        tasks += run.tasks
        if st.ok:
            listen_commands(run, bridge, loop)
    tasks.append(loop.create_task(publish_loop(monitors, bridge, runs=runs)))

    await stop.wait()
    log.info("HA-Rezeptbuch Waage wird beendet")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    bridge.stop()


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
