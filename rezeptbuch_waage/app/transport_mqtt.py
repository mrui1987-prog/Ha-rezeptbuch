"""Anschluss über das Roh-Topic der Waveshare-MQTT-Funktion (M07-1, Feldtest).

Der Waveshare veröffentlicht die Rohzeilen der Waage als Pakete (nach 10 ms
Pause, Feldtest 7). Ein Paket kann eine halbe oder mehrere Zeilen enthalten –
die Station zerlegt sie wie den TCP-Strom. Die MQTT-Nachrichten kommen aus dem
Netzwerk-Thread von paho und werden an die asyncio-Schleife übergeben.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Protocol

from .station import StationMonitor

log = logging.getLogger("rezeptbuch_waage")


class Subscriber(Protocol):
    def subscribe(self, topic: str, callback: Callable[[bytes], None]) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MqttRawTransport:
    def __init__(
        self,
        monitor: StationMonitor,
        bridge: Subscriber,
        loop: asyncio.AbstractEventLoop,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.monitor = monitor
        self.cfg = monitor.cfg
        self.bridge = bridge
        self.loop = loop
        self.clock = clock
        self.wall = wall

    def start(self) -> None:
        # Beim MQTT-Weg ist keine Verbindung zur Waage erkennbar (Waveshare
        # ohne Letzten Willen) – es zählt nur „keine Zeile“
        self.monitor.connected = None
        self.bridge.subscribe(self.cfg.raw_topic, self._on_message)
        log.info("%s: lese Roh-Topic %s", self.cfg.label, self.cfg.raw_topic)

    def _on_message(self, payload: bytes) -> None:
        """Aufruf aus dem paho-Thread."""
        self.loop.call_soon_threadsafe(self._feed, bytes(payload))

    def _feed(self, payload: bytes) -> None:
        self.monitor.feed(payload, self.clock(), self.wall())
