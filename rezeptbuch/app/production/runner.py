"""Waage im Wiegeablauf je Station (Modul 09, docs/ablauf.md Abschnitte 2, 6 und 9).

Der Runner liest die Waage über den Mittelsmann (Modul 08, ``current_state``/``send_command``) und
hält je Station den Zustand aus ``weigh.StationWeigh`` (Tara-Bezug, Tara der Waage, Tara läuft,
Auto-Quittung) sowie die Behälter-Abläufe (K09-13, K09-14). Was die Datenbank braucht
(Auto-Quittung, Pause nach Waagenausfall, Abschluss durch Abnehmen, Behälter speichern), erledigt
``automation.tick`` – der Runner ruft es im Hintergrund alle ``TICK_S`` Sekunden auf.

Zugriffe kommen aus der Ereignisschleife (Hintergrund) und aus den Anfragen (Threads); der Zustand
ist deshalb mit einer Sperre geschützt.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from ..scales import messages
from .settings import SETTINGS
from .weigh import Sample, StationWeigh

log = logging.getLogger("rezeptbuch.production")

TICK_S = 0.2
SETTINGS_EVERY_S = 5.0
WEIGH_EMIT_MIN_S = 0.1
MANUAL_NOTICE_S = 30.0     # so lange steht der Hinweis nach einem erkannten Tastendruck (ohne Bestätigung)
MANUAL_NOTICE_TEXT = "Hey! Die Waage bitte nicht über ihre Tasten bedienen – das geht hier am Tablet."
OWN_COMMAND_QUIET_S = 3.0   # so lange nach einem eigenen tare/zero keine „Tara/Null von Hand“ erkennen


@dataclass(frozen=True)
class Reading:
    """Messwert und Stand der Station für Anzeige und Quittieren."""
    station: int
    status: str                 # ok / invalid / error / offline / unknown
    weight_g: int | None
    stable: bool
    reference_g: int | None     # Tara-Bezug der Software; leer = unbekannt
    taring: bool = False
    gross_g: int | None = None
    hint: str | None = None
    container_step: str | None = None

    @property
    def usable(self) -> bool:
        return self.status == messages.STATUS_OK and self.weight_g is not None

    @property
    def actual_g(self) -> int | None:
        if not self.usable or self.reference_g is None:
            return None
        return self.weight_g - self.reference_g

    def to_dict(self) -> dict:
        return {"status": self.status, "weight_g": self.weight_g, "stable": self.stable,
                "reference_g": self.reference_g, "actual_g": self.actual_g, "taring": self.taring,
                "gross_g": self.gross_g, "hint": self.hint, "container_step": self.container_step}


@dataclass
class ContainerFlow:
    """Behälter wiegen (``weigh``) oder wechseln (``change``) an einer Station (K09-13, K09-14).

    Schritte: ``empty`` (Waage leeren) bzw. ``remove`` (Behälter abnehmen und ausleeren) →
    ``zeroing`` (Tara, Pause, Null, Null bis zu zweimal wiederholen, Michael 17:14) →
    ``place`` (Behälter aufstellen) → bei Abweichung zum bekannten Behältergewicht ``confirm``.
    """
    kind: str
    batch_id: int
    step: str
    sent_at: float | None = None
    measured_g: int | None = None
    zero_sent: int = 0              # wie oft ``zero`` im Schritt ``zeroing`` gesendet wurde
    zero_at: float | None = None    # Zeit des letzten ``zero``
    zero_failed: bool = False       # Null nach allen Versuchen nicht bestätigt: von Hand nullen

    HINTS = {
        ("weigh", "empty"): "Waage leeren",
        ("change", "remove"): "Behälter abnehmen und ausleeren",
        ("weigh", "zeroing"): "Waage wird genullt – bitte warten",
        ("change", "zeroing"): "Waage wird genullt – bitte warten",
        ("weigh", "place"): "Behälter jetzt aufstellen",
        ("change", "place"): "Leeren Behälter aufstellen",
        ("weigh", "final_tare"): "Waage wird tariert – bitte warten",
        ("change", "final_tare"): "Waage wird tariert – bitte warten",
        ("weigh", "confirm"): "Anderer Behälter? Bitte bestätigen",
        ("change", "confirm"): "Anderer Behälter? Bitte bestätigen",
    }

    @property
    def hint(self) -> str:
        if self.step == "zeroing" and self.zero_failed:
            return "Waage leer lassen und an der Waage Null drücken"
        return self.HINTS.get((self.kind, self.step), "")


class ProductionRunner:
    """Waagenzugriff des Ablaufs; ``hub`` ist der Mittelsmann (oder ``None`` ohne Waagen-Anbindung)."""

    def __init__(self, hub=None, clock: Callable[[], float] = time.monotonic) -> None:
        self.hub = hub
        self.clock = clock
        self.settings: dict[str, int] = {key: spec[0] for key, spec in SETTINGS.items()}
        self._settings_at = -1e9
        self._stations: dict[int, StationWeigh] = {}
        self._flows: dict[int, ContainerFlow] = {}
        self._offline_seen: dict[int, float] = {}
        self._snap_written: dict[int, tuple] = {}
        self._last_command: dict[int, float] = {}
        self._notice: dict[int, float] = {}       # Station → Zeit, bis zu der der Tasten-Hinweis steht
        self._last_emit: dict[int, tuple[float, dict]] = {}
        self._lock = threading.RLock()
        self._task: asyncio.Task | None = None
        self._db_path = None

    # ------------------------------------------------------------------ Einstellungen

    def refresh_settings(self, conn, force: bool = False) -> dict[str, int]:
        from .settings import load_settings
        now = self.clock()
        if force or now - self._settings_at >= SETTINGS_EVERY_S:
            try:
                self.settings = load_settings(conn)
                self._settings_at = now
            except Exception:  # noqa: BLE001 – Einstellungen sind nicht lebenswichtig
                log.exception("Einstellungen des Wiegeablaufs nicht lesbar")
        return self.settings

    # ------------------------------------------------------------------ Waage lesen

    def sample(self, station: int) -> Sample:
        state = self.hub.current_state(station) if self.hub is not None else None
        if state is None:
            return Sample("unknown", None, False)
        weight = state.weight_g if state.status == messages.STATUS_OK else None
        return Sample(state.status, weight, bool(state.stable), getattr(state, "net", None),
                      getattr(state, "capacity_g", None))

    def weigh_state(self, station: int) -> StationWeigh:
        with self._lock:
            return self._stations.setdefault(station, StationWeigh())

    def observe(self, station: int) -> tuple[StationWeigh, Sample, list[str]]:
        """Aktuellen Wert übernehmen (Tara-Bestätigung, Zeitablauf, verspäteter Sprung)."""
        with self._lock:
            sw = self.weigh_state(station)
            sample = self.sample(station)
            now = self.clock()
            quiet = now - self._last_command.get(station, -1e9) >= OWN_COMMAND_QUIET_S
            events = sw.observe(now, sample, self.settings["tare_confirm_seconds"],
                                self.settings["auto_ack_span_g"], watch_manual=quiet and station not in self._flows)
            for event in events:
                if event in ("manual_tare", "manual_zero"):
                    self._notice[station] = now + MANUAL_NOTICE_S
                    log.info("Waage %d: %s von Hand an der Waage erkannt (Sprung %s g) – Ist und Gesamtlast "
                             "bleiben (M09-19, Ausgleich jetzt %s g)", station,
                             "Tara" if event == "manual_tare" else "Null", sw.manual_delta_g, sw.offset(sample))
                if event == "tare_timeout":
                    log.warning("Waage %d: Tara nicht bestätigt – Software-Tara", station)
                elif event == "late_tare":
                    log.info("Waage %d: Tara verspätet ausgeführt, Bezug nachgeführt", station)
            return sw, sample, events

    def reading(self, station: int) -> Reading:
        with self._lock:
            sw, sample, _events = self.observe(station)
            flow = self._flows.get(station)
            return Reading(station, sample.status, sample.weight_g, sample.stable, sw.reference_g,
                           taring=sw.taring, gross_g=sw.gross(sample),
                           hint=flow.hint if flow else sw.hint, container_step=flow.step if flow else None)

    def gross(self, station: int) -> int | None:
        with self._lock:
            sw, sample, _ = self.observe(station)
            return sw.gross(sample)

    def tare_total(self, station: int) -> int | None:
        with self._lock:
            return self.weigh_state(station).tare_total()

    def busy(self, station: int) -> str | None:
        """Warum gerade nicht quittiert werden darf: ``taring`` oder ``container``."""
        with self._lock:
            self.observe(station)
            if station in self._flows:
                return "container"
            if self.weigh_state(station).taring:
                return "taring"
            return None

    # ------------------------------------------------------------------ Befehle

    def send(self, station: int, cmd: str) -> str:
        if self.hub is None or not hasattr(self.hub, "send_command"):
            return "unavailable"
        with self._lock:
            self._last_command[station] = self.clock()
        try:
            result = self.hub.send_command(station, cmd)
        except Exception:  # noqa: BLE001
            log.exception("Befehl %s an Waage %d fehlgeschlagen", cmd, station)
            return "error"
        if result != "sent":
            log.warning("Befehl %s an Waage %d nicht gesendet (%s)", cmd, station, result)
        return result

    def set_reference(self, station: int) -> int | None:
        """Tara (6.2): Bezug sofort = Anzeige, dazu ``tare`` an die Waage; Phase „Tara läuft“.
        Ohne gültigen Wert bleibt der Bezug unbekannt und es wird nichts gesendet."""
        with self._lock:
            sw, sample, _ = self.observe(station)
            reference = sw.start_tare(self.clock(), sample)
            if reference is None:
                return None
            result = self.send(station, "tare")
            if result != "sent":
                # Befehl nicht unterwegs: Software-Tara, Hinweis (K09-3)
                sw.taring_since = None
                sw.hint = "Tara an der Waage nicht möglich – die Software rechnet weiter."
            # sofort beobachten: eine schnelle Waage bestätigt gleich
            self.observe(station)
            return self.weigh_state(station).reference_g

    def zero(self, station: int) -> str:
        with self._lock:
            result = self.send(station, "zero")
            if result == "sent":
                self.weigh_state(station).zeroed()
            return result

    def clear(self, station: int) -> None:
        with self._lock:
            self.weigh_state(station).clear()
            self._flows.pop(station, None)
            self._offline_seen.pop(station, None)

    # ------------------------------------------------------------------ Gespeicherter Stand (M09-17)

    def snap_written(self, batch_id: int):
        with self._lock:
            return self._snap_written.get(batch_id)

    def remember_snap(self, batch_id: int, key, at: float, snap: dict) -> None:
        with self._lock:
            self._snap_written[batch_id] = (key, at, snap)

    def forget_snap(self, batch_id: int) -> None:
        with self._lock:
            self._snap_written.pop(batch_id, None)

    # ------------------------------------------------------------------ Stand für „Weiter“ (M09-17)

    def snapshot(self, station: int, *, need_stable: bool = True) -> dict | None:
        """Stand der Waage für die laufende Zutat: Gesamtlast, Tara-Bezug als Gesamtlast, Tara der Waage, Ist.
        Nur mit gültigem Wert, ohne laufende Tara und ohne Behälter-Schritt; sonst ``None``."""
        with self._lock:
            sw, sample, _ = self.observe(station)
            if station in self._flows or sw.taring or not sample.ok:
                return None
            if need_stable and not sample.stable:
                return None
            gross = sw.gross(sample)
            actual = sw.actual(sample)
            if gross is None or actual is None:
                return None
            # „scale_tare_g“ = Gesamtlast − Anzeige (Tara der Waage + von Hand Genulltes)
            return {"load_g": gross, "tare_g": gross - actual, "scale_tare_g": gross - sample.weight_g,
                    "actual_g": actual}

    def notice(self, station: int) -> str | None:
        """Hinweis nach erkanntem Tastendruck an der Waage (Michael 24.11.2026, 12:51: über der Weiter-Taste,
        ohne Bestätigung; ändert M09-19 Punkt 3 „nur Protokoll“)."""
        with self._lock:
            until = self._notice.get(station)
            return MANUAL_NOTICE_TEXT if until is not None and self.clock() < until else None

    def live_offset(self, station: int) -> int | None:
        """Gesamtlast − Anzeige, wie der Runner sie gerade verfolgt (``None`` = unbekannt, z. B. nach Neustart)."""
        with self._lock:
            sw, sample, _ = self.observe(station)
            return sw.offset(sample) if sample.ok else None

    def keep_tare(self, station: int, tare_g: int, scale_tare_g: int | None) -> int | None:
        """„Weiter“ ohne neue Tara (M09-17): Ausgleich (Gesamtlast − Anzeige, Parameter ``scale_tare_g``) und Bezug
        so setzen, dass Ist = Gesamtlast − ``tare_g``.
        Gibt das Ist zurück (``None`` ohne gültigen Wert)."""
        with self._lock:
            sw, sample, _ = self.observe(station)
            if not sample.ok:
                return None
            sw.reset_ack()
            sw.taring_since = None
            sw.late_tare_g = None
            sw.hint = None
            if scale_tare_g is None:
                return None
            sw.set_offset(sample, scale_tare_g)
            sw.reference_g = tare_g - scale_tare_g
            return sw.actual(sample)

    # ------------------------------------------------------------------ Behälter (K09-13, K09-14)

    def flow(self, station: int) -> ContainerFlow | None:
        with self._lock:
            return self._flows.get(station)

    def start_flow(self, station: int, kind: str, batch_id: int) -> ContainerFlow:
        with self._lock:
            sw = self.weigh_state(station)
            sw.reset_ack()
            sw.taring_since = None
            flow = ContainerFlow(kind, batch_id, "empty" if kind == "weigh" else "remove")
            self._flows[station] = flow
            return flow

    def finish_container(self, station: int, kind: str, batch_id: int) -> None:
        """Behälter gemerkt: nur noch ``tare`` mit dem Behälter (M09-19, Michael 24.11.2026: kein ``zero`` mit
        Last – die KERN löscht dabei die Tara und versteckt den Behälter). Schritt ``final_tare`` wartet auf die
        Bestätigung und wiederholt die Tara bei ruhiger Anzeige höchstens zweimal."""
        with self._lock:
            self._flows.pop(station, None)
            self.set_reference(station)
            self._flows[station] = ContainerFlow(kind, batch_id, "final_tare", sent_at=self.clock())

    def end_flow(self, station: int) -> None:
        with self._lock:
            self._flows.pop(station, None)

    # ------------------------------------------------------------------ Waagenausfall (M09-8)

    def offline_for(self, station: int, sample: Sample) -> float:
        """Sekunden, seit die Station ohne Unterbrechung offline ist (0 = nicht offline)."""
        with self._lock:
            if sample.status != messages.STATUS_OFFLINE:
                self._offline_seen.pop(station, None)
                return 0.0
            since = self._offline_seen.setdefault(station, self.clock())
            return self.clock() - since

    # ------------------------------------------------------------------ Live-Kanal

    def broadcast(self, event: dict) -> None:
        """Nachricht an alle Teilnehmer des Live-Kanals (Typen ``batch``, ``orders``, ``weigh``)."""
        if self.hub is not None and hasattr(self.hub, "broadcast"):
            self.hub.broadcast(event)

    def emit_weigh(self, station: int, message: dict) -> None:
        """``weigh`` nur bei Änderung, höchstens etwa zehnmal je Sekunde."""
        now = self.clock()
        with self._lock:
            last = self._last_emit.get(station)
            if last is not None and (last[1] == message or now - last[0] < WEIGH_EMIT_MIN_S):
                return
            self._last_emit[station] = (now, message)
        self.broadcast(message)

    # ------------------------------------------------------------------ Hintergrund

    def stations(self) -> list[int]:
        if self.hub is None:
            return []
        if hasattr(self.hub, "known_stations"):
            return list(self.hub.known_stations())
        return sorted(getattr(self.hub, "states", {}).keys())

    async def start(self, db_path) -> None:
        if db_path is None or self._task is not None:
            return
        self._db_path = db_path
        self._task = asyncio.create_task(self._loop(), name="wiegeablauf")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except BaseException:  # noqa: BLE001 – abgebrochen
                pass
            self._task = None

    async def _loop(self) -> None:
        from ..db import connect
        from .automation import tick
        conn = connect(self._db_path)
        try:
            while True:
                try:
                    tick(conn, self)
                except Exception:  # noqa: BLE001 – der Ablauf läuft weiter
                    log.exception("Fehler im Wiegeablauf")
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                await asyncio.sleep(TICK_S)
        finally:
            conn.close()
