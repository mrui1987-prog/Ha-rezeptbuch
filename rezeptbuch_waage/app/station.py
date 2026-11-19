"""Zustand einer Waagestation: Status, Wächter, Melderegel, Befehle (docs/waage.md 4–6).

Die Station bekommt Bytes vom Anschluss (TCP, MQTT-Roh-Topic oder Simulator)
und liefert bei `poll()` die nächste Zustandsmeldung, wenn eine fällig ist:
sofort bei Änderung, sonst alle 500 ms (M07-7). Ohne Ein-/Ausgabe, Zeiten
werden übergeben (monoton für Fristen, Wanduhr für `ts`).
"""

from __future__ import annotations

import logging
from datetime import datetime

from . import kern
from .commands import MERGED, NAMES, CommandQueue
from .config import StationConfig
from .messages import (
    STATUS_ERROR,
    STATUS_INVALID,
    STATUS_OFFLINE,
    STATUS_OK,
    state_payload,
)
from .stability import StabilityChecker

UNREADABLE_ERROR_S = 3.0  # K07-6
REPEAT_S = 0.5            # M07-7: sonst mindestens 2× je Sekunde

log = logging.getLogger("rezeptbuch_waage")


class StationMonitor:
    def __init__(self, cfg: StationConfig) -> None:
        self.cfg = cfg
        self.splitter = kern.LineSplitter()
        self.stability = StabilityChecker(cfg.stable_window_ms, cfg.stable_span_g)
        # Vom TCP-Anschluss gesetzt (True/False); beim MQTT-Weg unbekannt (None)
        self.connected: bool | None = None
        self._last_line_at: float | None = None
        self._last_line_wall: datetime | None = None
        self._last_reading: kern.Reading | None = None
        self._unreadable_since: float | None = None
        self._last_key: tuple | None = None
        self._last_pub_at: float | None = None
        self._last_status: str | None = None
        self.commands = CommandQueue()

    # --- Eingang ------------------------------------------------------------

    def feed(self, data: bytes, now: float, wall: datetime) -> None:
        for line in self.splitter.feed(data):
            self.handle_line(line, now, wall)

    def handle_line(self, line: str | None, now: float, wall: datetime) -> None:
        reading = kern.parse_line(line)
        self._last_line_at = now
        self._last_line_wall = wall
        if reading.kind == kern.UNREADABLE:
            if self._unreadable_since is None:
                self._unreadable_since = now
            self.stability.reset()
            log.debug("%s: unlesbar %r", self.cfg.label, reading.text)
            return
        self._unreadable_since = None
        self._last_reading = reading
        if reading.kind == kern.WEIGHT:
            self.stability.add(now, reading.weight_g, bool(reading.net))
            log.debug("%s: %r → %s g, Spanne %s g", self.cfg.label, reading.text,
                      reading.weight_g, self.stability.spread(now))
        else:
            self.stability.reset()
            log.debug("%s: %r → kein gültiger Wert", self.cfg.label, reading.text)

    def connection_lost(self) -> None:
        """Anschluss getrennt: halbe Zeile verwerfen (Status erst nach Frist)."""
        self.splitter.reset()

    # --- Zustand ------------------------------------------------------------

    def _clear(self) -> None:
        self._last_reading = None
        self._unreadable_since = None
        self.stability.reset()
        self.splitter.reset()

    def status(self, now: float) -> str:
        if not self.cfg.ok:
            return STATUS_ERROR
        alive = (self._last_line_at is not None
                 and now - self._last_line_at < self.cfg.offline_after_s)
        if not alive:
            if self._last_reading is not None or self._unreadable_since is not None:
                self._clear()
            return STATUS_OFFLINE
        if (self._unreadable_since is not None
                and now - self._unreadable_since >= UNREADABLE_ERROR_S):
            return STATUS_ERROR
        if self._last_reading is None:
            return STATUS_OFFLINE  # bisher nur unlesbare Zeilen, unter 3 s
        if self._last_reading.kind == kern.WEIGHT:
            return STATUS_OK
        return STATUS_INVALID

    def state(self, now: float) -> dict:
        """Aktueller Zustand ohne Zeitstempel."""
        status = self.status(now)
        reading = self._last_reading if status == STATUS_OK else None
        return {
            "status": status,
            "weight_g": reading.weight_g if reading else None,
            "stable": self.stability.is_stable(now) if reading else False,
            "scale_stable": reading.scale_stable if reading else None,
            "net": reading.net if reading else None,
        }

    def poll(self, now: float, wall: datetime) -> str | None:
        """Nächste Meldung, falls fällig (Änderung oder 500 ms), sonst None."""
        st = self.state(now)
        key = tuple(st.values())
        changed = key != self._last_key
        if not changed and self._last_pub_at is not None and now - self._last_pub_at < REPEAT_S:
            return None
        if st["status"] != self._last_status:
            self._log_transition(self._last_status, st["status"])
            self._last_status = st["status"]
        self._last_key = key
        self._last_pub_at = now
        ts = wall
        if st["status"] != STATUS_OFFLINE and self._last_line_wall is not None:
            ts = self._last_line_wall
        return state_payload(
            self.cfg.station,
            capacity_g=self.cfg.capacity_g,
            resolution_g=self.cfg.resolution_g,
            ts=ts,
            **st,
        )

    # --- Befehle (docs/waage.md 6.3) -----------------------------------------

    def submit_command(self, cmd: str, now: float) -> bool:
        """Nimmt `tare`/`zero` an, wenn die Waage Zeilen liefert (nicht bei offline)."""
        name = self.cfg.label
        status = self.status(now)
        if status == STATUS_OFFLINE:
            log.warning("%s: Befehl %s verworfen – Waage liefert keine Zeilen (offline)",
                        name, NAMES[cmd])
            return False
        if not self.cfg.ok:
            log.warning("%s: Befehl %s verworfen – Konfiguration fehlerhaft", name, NAMES[cmd])
            return False
        if cmd == "zero":
            reason = self.zero_refusal(now)
            if reason:
                log.warning("%s: Befehl %s verworfen – %s", name, NAMES[cmd], reason)
                return False
        if self.commands.add(cmd) == MERGED:
            log.info("%s: Befehl %s wartet bereits, zusammengefasst", name, NAMES[cmd])
        else:
            log.info("%s: Befehl %s angenommen", name, NAMES[cmd])
        return True

    def next_command(self, now: float) -> str | None:
        """Nächster Befehl zum Senden (Mindestabstand 1 s), sonst None.

        Ist die Waage inzwischen offline, werden wartende Befehle verworfen.
        """
        if not self.commands.ready(now):
            return None
        if self.status(now) == STATUS_OFFLINE:
            for cmd in self.commands.clear():
                log.warning("%s: wartender Befehl %s verworfen – Waage offline",
                            self.cfg.label, NAMES[cmd])
            return None
        if self.commands.pending[0] == "zero":
            reason = self.zero_refusal(now)
            if reason:
                self.commands.pending.pop(0)
                log.warning("%s: wartender Befehl %s verworfen – %s",
                            self.cfg.label, NAMES["zero"], reason)
                return None
        return self.commands.pop(now)

    def zero_refusal(self, now: float) -> str | None:
        """Grund, warum `zero` jetzt nicht erlaubt ist (Z07-1, Z07-2), sonst None.

        - `invalid` (`-----`): erlaubt, ohne Gewichtsgrenze (Z07-2, wie Konzept
          6.3: leere Waage im Minus lässt sich nullstellen).
        - `ok`: erlaubt, wenn der angezeigte Wert – brutto oder netto (Tara an
          der Waage aktiv, Z07-2) – höchstens ±`zero_limit_g` beträgt. Sonst
          würde die Waage aufliegende Last als 0 melden (Null-Taste wirkt bis
          knapp 10 kg, Z07-1).
        - sonst (`error`, kein Wert): verworfen.
        """
        status = self.status(now)
        if status == STATUS_INVALID:
            return None
        limit = self.cfg.zero_limit_g
        if status != STATUS_OK or self._last_reading is None:
            return "kein gültiges Gewicht, Nullstellen nur bei leerer Waage"
        reading = self._last_reading
        if abs(reading.weight_g) > limit:
            art = "netto" if reading.net else "brutto"
            return (f"Waage zeigt {reading.weight_g} g {art}, Nullstellen nur bei "
                    f"leerer Waage (bis ±{limit} g)")
        return None

    # --- Protokoll ----------------------------------------------------------

    def _log_transition(self, old: str | None, new: str) -> None:
        name = self.cfg.label
        if new == STATUS_ERROR and self.cfg.ok:
            log.warning("%s liefert unlesbare Daten – Baudrate %s und Format %s an "
                        "Waage und Waveshare prüfen", name, self.cfg.baud, self.cfg.format)
        elif new == STATUS_OFFLINE and old is not None:
            if self.connected:
                log.warning("%s: keine Zeilen – Sendemodus %s an der Waage prüfen",
                            name, self.cfg.mode)
            else:
                log.warning("%s getrennt (seit %s s keine Zeile)", name,
                            self.cfg.offline_after_s)
        elif new in (STATUS_OK, STATUS_INVALID) and old in (None, STATUS_OFFLINE, STATUS_ERROR):
            log.info("%s liefert Werte", name)
        elif new == STATUS_INVALID:
            log.info("%s: kein gültiger Wert (Überlast, Negativwert oder Bewegung)", name)
