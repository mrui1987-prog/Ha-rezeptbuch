"""TCP-Anschluss zum Waveshare-Konverter (M07-1, Standard).

Verbindet sich mit dem TCP-Server des Waveshare (Port 8899) und gibt die Bytes an
die Station weiter; Befehle gehen über dieselbe Verbindung zurück. Bricht die Verbindung ab, wird sofort neu verbunden, danach
mit Wartezeit 1, 2, 5, dann alle 10 s. Kommen sehr lange keine Daten (z. B.
Waveshare ohne Strom, Verbindung hängt), wird die Verbindung neu aufgebaut.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Callable

from .commands import WIRE
from .station import StationMonitor

BACKOFF_S = (1, 2, 5, 10)
CONNECT_TIMEOUT_S = 5
READ_SIZE = 1024

log = logging.getLogger("rezeptbuch_waage")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TcpTransport:
    def __init__(
        self,
        monitor: StationMonitor,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = _utcnow,
        backoff: tuple[float, ...] = BACKOFF_S,
        idle_timeout_s: float | None = None,
    ) -> None:
        self.monitor = monitor
        self.cfg = monitor.cfg
        self.clock = clock
        self.wall = wall
        self.backoff = backoff
        # Doppelte Offline-Frist: vorher meldet die Station schon „offline“
        # (mit Hinweis Sendemodus), danach wird die Verbindung neu aufgebaut
        self.idle_timeout_s = idle_timeout_s or 2 * self.cfg.offline_after_s
        self._writer: asyncio.StreamWriter | None = None
        self.connects = 0  # für Tests und Protokoll

    def send_command(self, cmd: str) -> bool:
        """Schreibt `T`/`Z` + CR LF über die offene Verbindung."""
        writer = self._writer
        if writer is None or writer.is_closing():
            return False
        writer.write(WIRE[cmd])
        return True

    async def run(self) -> None:
        failures = 0
        reported = False
        address = f"{self.cfg.host}:{self.cfg.port}"
        while True:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.cfg.host, self.cfg.port),
                    CONNECT_TIMEOUT_S,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                if not reported:
                    log.warning("%s: keine Verbindung zu %s (%s)", self.cfg.label,
                                address, exc or "Zeitüberschreitung")
                    reported = True
                await asyncio.sleep(self.backoff[min(failures, len(self.backoff) - 1)])
                failures += 1
                continue

            failures = 0
            reported = False
            self.connects += 1
            log.info("%s: verbunden mit %s", self.cfg.label, address)
            self._writer = writer
            self.monitor.connected = True
            reason = "Verbindung beendet"
            try:
                while True:
                    try:
                        data = await asyncio.wait_for(reader.read(READ_SIZE),
                                                      self.idle_timeout_s)
                    except asyncio.TimeoutError:
                        reason = f"{self.idle_timeout_s:g} s keine Daten"
                        break
                    if not data:
                        break
                    self.monitor.feed(data, self.clock(), self.wall())
            except OSError as exc:
                reason = str(exc) or exc.__class__.__name__
            finally:
                self._writer = None
                self.monitor.connected = False
                self.monitor.connection_lost()
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
            log.warning("%s: Verbindung zu %s getrennt (%s), baue neu auf",
                        self.cfg.label, address, reason)
