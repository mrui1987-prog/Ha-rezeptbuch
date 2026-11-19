"""Simulator einer KERN-Waage im Sendemodus CONT (M07-9, docs/waage.md 8).

Erzeugt echte KERN-Zeilen (10 je Sekunde), damit dieselbe Auswertung wie bei der
echten Waage durchlaufen wird. Ablauf in Schleife (60 s): leer → Behälter
1 200 g → langsames Befüllen bis 5 000 g mit Schwanken → ruhig → kurz `-----`
→ Abnehmen → leer → 8 s keine Zeilen (damit „offline“ sichtbar wird).
Der Kern (`SimulatedScale`) ist ohne Ein-/Ausgabe und wird auch vom Werkzeug
`tools/waagen_simulator` (Waveshare-Ersatz per TCP) genutzt.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .kern import format_line
from .station import StationMonitor

LINE_INTERVAL_S = 0.1
CYCLE_S = 60.0
CONTAINER_G = 1200
FILLED_G = 5000


@dataclass(frozen=True)
class Phase:
    start: float
    end: float
    kind: str            # "steady", "ramp", "dashes", "silent"
    from_g: int = 0
    to_g: int = 0
    noise_g: int = 0
    stable: bool = True


PHASES: tuple[Phase, ...] = (
    Phase(0, 5, "steady", 0, 0),
    Phase(5, 6, "ramp", 0, CONTAINER_G, noise_g=20, stable=False),
    Phase(6, 9, "steady", CONTAINER_G, CONTAINER_G),
    Phase(9, 29, "ramp", CONTAINER_G, FILLED_G, noise_g=3, stable=False),
    Phase(29, 31, "steady", FILLED_G, FILLED_G, noise_g=2, stable=False),
    Phase(31, 39, "steady", FILLED_G, FILLED_G),
    Phase(39, 41, "dashes"),
    Phase(41, 42, "ramp", FILLED_G, 0, noise_g=30, stable=False),
    Phase(42, 50, "steady", 0, 0),
    Phase(50, 58, "silent"),
    Phase(58, 60, "steady", 0, 0),
)


class SimulatedScale:
    """Gewichtsverlauf mit Tara und Nullstellen wie an der echten Waage."""

    def __init__(self, seed: int = 7) -> None:
        self._rng = random.Random(seed)
        self.zero_offset_g = 0
        self.tare_g: int | None = None  # gesetzt = Waage meldet netto

    @staticmethod
    def phase_at(t: float) -> Phase:
        t = t % CYCLE_S
        for phase in PHASES:
            if phase.start <= t < phase.end:
                return phase
        return PHASES[-1]

    def raw_weight(self, t: float) -> int | None:
        """Bruttogewicht auf der Plattform (ohne Nullstellen), None bei `-----`."""
        phase = self.phase_at(t)
        if phase.kind in ("dashes", "silent"):
            return None
        if phase.kind == "ramp":
            share = (t % CYCLE_S - phase.start) / (phase.end - phase.start)
            base = round(phase.from_g + (phase.to_g - phase.from_g) * share)
        else:
            base = phase.from_g
        if phase.noise_g:
            base = max(0, base + self._rng.randint(-phase.noise_g, phase.noise_g))
        return base

    def line(self, t: float) -> str | None:
        """KERN-Zeile ohne Zeilenende; None = Waage sendet nichts."""
        phase = self.phase_at(t)
        if phase.kind == "silent":
            return None
        raw = self.raw_weight(t)
        if raw is None:
            return "-----"
        gross = raw - self.zero_offset_g
        if self.tare_g is not None:
            value = gross - self.tare_g
        else:
            value = gross
        if value < 0:
            return "-----"  # die KFB-TM zeigt Negativwerte als `-----` (Feldtest)
        return format_line(value, stable=phase.stable, net=self.tare_g is not None)

    def tare(self, t: float) -> None:
        raw = self.raw_weight(t)
        if raw is not None:
            self.tare_g = raw - self.zero_offset_g

    def zero(self, t: float) -> None:
        raw = self.raw_weight(t)
        if raw is not None:
            self.zero_offset_g = raw
            self.tare_g = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SimulatorTransport:
    """Treiber `simulator`: liefert die Zeilen direkt an die Station."""

    def __init__(
        self,
        monitor: StationMonitor,
        scale: SimulatedScale | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = _utcnow,
        interval_s: float = LINE_INTERVAL_S,
    ) -> None:
        self.monitor = monitor
        self.scale = scale or SimulatedScale(seed=monitor.cfg.station)
        self.clock = clock
        self.wall = wall
        self.interval_s = interval_s
        self._start: float | None = None

    def send_command(self, cmd: str) -> bool:
        """Führt `tare`/`zero` im Simulator aus (wie `T`/`Z` an der Waage)."""
        if self._start is None:
            return False
        t = self.clock() - self._start
        if cmd == "tare":
            self.scale.tare(t)
        elif cmd == "zero":
            self.scale.zero(t)
        else:
            return False
        return True

    async def run(self) -> None:
        self._start = self.clock()
        self.monitor.connected = None
        while True:
            now = self.clock()
            line = self.scale.line(now - self._start)
            if line is not None:
                self.monitor.feed((line + "\r\n").encode("ascii"), now, self.wall())
            await asyncio.sleep(self.interval_s)
