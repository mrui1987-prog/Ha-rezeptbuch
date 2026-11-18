"""Einstiegspunkt der Waagen-Bridge (Add-on 2, docs/waage.md Abschnitt 2).

Liest die Konfiguration, verbindet sich mit dem MQTT-Broker (Letzter Wille),
startet je aktiver Waage den Anschluss (TCP, MQTT-Roh-Topic oder Simulator) und
meldet den Zustand nach Schema 2. Ein Fehler an einer Waage berührt die andere
nicht; ein unerwarteter Fehler im Anschluss startet nur diesen neu.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

from . import __version__
from .config import OPTIONS_FILE, AddonConfig, StationConfig, describe, load_options
from .messages import state_topic
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


def start_station(
    st: StationConfig,
    monitor: StationMonitor,
    bridge: MqttBridge,
    loop: asyncio.AbstractEventLoop,
) -> list[asyncio.Task]:
    if not st.ok:
        return []
    if st.driver == "simulator":
        transport = SimulatorTransport(monitor)
        return [loop.create_task(supervise(st.label, transport.run))]
    if st.connection == "tcp":
        transport_tcp = TcpTransport(monitor)
        return [loop.create_task(supervise(st.label, transport_tcp.run))]
    MqttRawTransport(monitor, bridge, loop).start()
    return []


async def publish_loop(
    monitors: list[StationMonitor],
    bridge: MqttBridge,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    while True:
        now = clock()
        wall = datetime.now(timezone.utc)
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
    for st, monitor in zip(cfg.active, monitors):
        tasks += start_station(st, monitor, bridge, loop)
    tasks.append(loop.create_task(publish_loop(monitors, bridge)))

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
