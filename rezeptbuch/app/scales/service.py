"""Betrieb der Waagen-Anbindung: Start, Stopp, Wächter (docs/schnittstellen.md).

Verbindet Mittelsmann (``hub``), MQTT (``mqtt_link``) und Stationsliste aus der
Datenbank. Ohne MQTT läuft der Rezeptserver weiter (M08-10): die Zugangsdaten
werden alle 30 s erneut beim Supervisor angefragt, die Stationen stehen auf
offline (Grund ``broker``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable

from ..db import connect
from .hub import MQTT_CONNECTED, MQTT_DISCONNECTED, MQTT_UNAVAILABLE, ScaleHub
from .mqtt_link import MqttLink
from .supervisor import CredentialsError, fetch_credentials

log = logging.getLogger("rezeptbuch.scales")

WATCH_INTERVAL_S = 0.25        # Wächter für „3 s still“
STATIONS_INTERVAL_S = 30.0     # Stationsliste neu lesen (M08-9)
CREDENTIALS_RETRY_S = 30.0     # MQTT-Dienst fehlt → neuer Versuch


def load_stations(db_path: str | Path | None) -> dict[int, tuple[str, bool]]:
    """Stationen aus Tabelle ``station``: Nr → (Name, aktiv). Ohne Datenbank leer."""
    if db_path is None:
        return {}
    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT id, name, active FROM station ORDER BY id").fetchall()
    finally:
        conn.close()
    return {int(row[0]): (str(row[1]), bool(row[2])) for row in rows}


class ScaleService:
    def __init__(
        self,
        hub: ScaleHub | None = None,
        db_path: str | Path | None = None,
        fetch: Callable[[], dict] = fetch_credentials,
        link_factory: Callable[..., Any] = MqttLink,
        credentials_retry_s: float = CREDENTIALS_RETRY_S,
    ) -> None:
        self.hub = hub or ScaleHub()
        self.db_path = db_path
        self._fetch = fetch
        self._link_factory = link_factory
        self._retry_s = credentials_retry_s
        self.link: Any = None
        self._tasks: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.reload_stations()
        self.hub.check_silence()
        self._tasks = [
            asyncio.create_task(self._connect(), name="scales-connect"),
            asyncio.create_task(self._watch(), name="scales-watch"),
            asyncio.create_task(self._stations(), name="scales-stations"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks = []
        if self.link is not None:
            self.link.stop()
            self.link = None
        self.hub.set_publisher(None)

    def reload_stations(self) -> None:
        try:
            self.hub.set_stations(load_stations(self.db_path))
        except (sqlite3.Error, OSError) as exc:
            log.warning("Stationsliste nicht lesbar: %s", exc)

    # ------------------------------------------------------------ Aufgaben

    async def _connect(self) -> None:
        last_error = None
        while True:
            try:
                creds = await asyncio.to_thread(self._fetch)
            except CredentialsError as exc:
                self.hub.set_mqtt(MQTT_UNAVAILABLE)
                if str(exc) != last_error:
                    log.error("MQTT nicht verfügbar: %s – neuer Versuch alle %d s, Rezeptbuch läuft weiter",
                              exc, int(self._retry_s))
                    last_error = str(exc)
                await asyncio.sleep(self._retry_s)
                continue
            self.hub.set_mqtt(MQTT_DISCONNECTED)
            link = self._link_factory(creds, on_message=self._from_thread_message,
                                      on_connection=self._from_thread_connection)
            self.link = link
            self.hub.set_publisher(link.publish)
            link.start()
            return

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(WATCH_INTERVAL_S)
            try:
                self.hub.check_silence()
            except Exception:  # noqa: BLE001 – Wächter darf nicht sterben
                log.exception("Fehler im Waagen-Wächter")

    async def _stations(self) -> None:
        while True:
            await asyncio.sleep(STATIONS_INTERVAL_S)
            self.reload_stations()

    # ------------------------------------------------------------ paho-Thread → asyncio

    def _from_thread_message(self, topic: str, payload: bytes) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._safe, self.hub.handle_message, topic, payload)

    def _from_thread_connection(self, connected: bool) -> None:
        if self._loop is not None:
            state = MQTT_CONNECTED if connected else MQTT_DISCONNECTED
            self._loop.call_soon_threadsafe(self._safe, self.hub.set_mqtt, state)

    @staticmethod
    def _safe(func: Callable, *args) -> None:
        try:
            func(*args)
        except Exception:  # noqa: BLE001 – ein Fehler darf die Schleife nicht stören
            log.exception("Fehler bei der Verarbeitung einer Waagen-Nachricht")
