"""Mittelsmann der Waagen (M08-7, docs/schnittstellen.md Abschnitte 3 und 4).

Hält je Station den zuletzt empfangenen Zustand von Add-on 2, wendet die
Offline-Regel von Add-on 1 an (M08-4) und meldet jede Änderung an alle Abonnenten
(Live-Kanal, später Modul 09). Befehle gehen über einen austauschbaren Sender.

Alle Methoden laufen in der asyncio-Schleife des Servers (paho übergibt mit
``call_soon_threadsafe``), deshalb sind keine Sperren nötig. Kein MQTT, kein
FastAPI – die Klasse ist ohne Netz und ohne Warten testbar (Uhr übergebbar).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable

from . import messages

log = logging.getLogger("rezeptbuch.scales")

SILENT_AFTER_S = 3.0          # M08-4 (c): so lange ohne Zustand → offline
QUEUE_SIZE = 200              # je Abonnent; bei Überlauf fällt die älteste Meldung weg
LOG_EVERY_S = 60.0            # M08-8: Fehlerart höchstens einmal je Minute protokollieren

MQTT_CONNECTED = "connected"
MQTT_DISCONNECTED = "disconnected"
MQTT_UNAVAILABLE = "unavailable"

REASON_SCALE = "scale"        # Add-on 2 meldet die Waage offline
REASON_BRIDGE = "bridge"      # Add-on 2 weg (Verfügbarkeit offline)
REASON_BROKER = "broker"      # MQTT-Verbindung von Add-on 1 getrennt / nicht vorhanden
REASON_SILENT = "silent"      # seit 3 s kein Zustand

RESULT_SENT = "sent"
RESULT_OFFLINE = "offline"
RESULT_NOT_CONFIGURED = "not_configured"
RESULT_MQTT_DOWN = "mqtt_down"
RESULT_UNKNOWN = "unknown_station"

# Felder, die keine „Änderung“ auslösen (Add-on 2 wiederholt alle 500 ms mit neuer Zeit)
_VOLATILE = ("ts", "received_at")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class StationScale:
    station: int
    name: str
    configured: bool
    status: str
    offline_reason: str | None
    offline_since: str | None
    weight_g: int | None
    stable: bool
    scale_stable: bool | None
    net: bool | None
    capacity_g: int | None
    resolution_g: int | None
    ts: str | None
    received_at: str | None

    @property
    def offline(self) -> bool:
        return self.status == messages.STATUS_OFFLINE

    def to_dict(self) -> dict:
        return asdict(self)

    def same_as(self, other: "StationScale | None") -> bool:
        if other is None:
            return False
        mine, theirs = self.to_dict(), other.to_dict()
        for key in _VOLATILE:
            mine.pop(key)
            theirs.pop(key)
        return mine == theirs


@dataclass
class _Raw:
    data: dict
    received_mono: float
    received_at: str


class ScaleHub:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        now_iso: Callable[[], str] = utc_now_iso,
        silent_after_s: float = SILENT_AFTER_S,
    ) -> None:
        self._clock = clock
        self._now_iso = now_iso
        self._silent_after = silent_after_s
        self._stations: dict[int, tuple[str, bool]] = {}   # Nr → (Name, eingerichtet)
        self._raw: dict[int, _Raw] = {}
        self._current: dict[int, StationScale] = {}
        self._mqtt = MQTT_UNAVAILABLE
        self._bridge = "unknown"
        self._subs: list[asyncio.Queue] = []
        self._publisher: Callable[[str, str], bool] | None = None
        self._log_last: dict[str, float] = {}

    # ------------------------------------------------------------ Einstellen

    def set_publisher(self, publisher: Callable[[str, str], bool] | None) -> None:
        """Sender für Befehle: ``publisher(topic, payload) -> bool`` (QoS 1, nie retained)."""
        self._publisher = publisher

    def set_stations(self, stations: dict[int, tuple[str, bool]]) -> None:
        """Stationen aus Tabelle ``station`` (M08-9): Nr → (Name, aktiv)."""
        clean = {n: (name, bool(active)) for n, (name, active) in stations.items() if n in messages.STATIONS}
        if clean != self._stations:
            self._stations = clean
            self._refresh()

    def set_mqtt(self, state: str) -> None:
        if state != self._mqtt:
            self._mqtt = state
            if state != MQTT_CONNECTED:
                # Ohne Verbindung ist auch der Stand von Add-on 2 unbekannt
                self._bridge = "unknown"
            self._emit({"type": "link", **self.link()})
            self._refresh()

    # ------------------------------------------------------------ Eingang

    def handle_message(self, topic: str, payload: bytes) -> None:
        if topic == messages.AVAILABILITY_TOPIC:
            self.handle_availability(payload)
        else:
            self.handle_state(topic, payload)

    def handle_state(self, topic: str, payload: bytes | str) -> None:
        try:
            data = messages.parse_state(topic, payload)
        except messages.MessageError as exc:
            self._log_throttled(exc.kind, f"Waagenzustand verworfen ({topic}): {exc}")
            return
        self._raw[data["station"]] = _Raw(data, self._clock(), self._now_iso())
        self._refresh([data["station"]])

    def handle_availability(self, payload: bytes | str) -> None:
        try:
            value = messages.parse_availability(payload)
        except messages.MessageError as exc:
            self._log_throttled(exc.kind, f"Verfügbarkeit verworfen: {exc}")
            return
        if value != self._bridge:
            self._bridge = value
            if value == "offline":
                log.warning("Waagen-Add-on meldet offline – alle Stationen offline")
            self._emit({"type": "link", **self.link()})
            self._refresh()

    def check_silence(self) -> None:
        """Wächter (alle 250 ms): Stationen ohne Zustand seit 3 s → offline."""
        self._refresh()

    # ------------------------------------------------------------ Abfragen

    def link(self) -> dict:
        return {"mqtt": self._mqtt, "bridge": self._bridge}

    @property
    def mqtt_state(self) -> str:
        return self._mqtt

    def known_stations(self) -> list[int]:
        return sorted(set(self._stations) | set(self._raw))

    def current_state(self, station: int) -> StationScale | None:
        return self._current.get(station)

    def snapshot(self) -> list[StationScale]:
        return [self._current[n] for n in self.known_stations() if n in self._current]

    # ------------------------------------------------------------ Abo

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subs.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subs:
            self._subs.remove(queue)

    # ------------------------------------------------------------ Befehle

    def send_command(self, station: int, cmd: str) -> str:
        if cmd not in messages.COMMANDS:
            raise ValueError(f"Unbekannter Befehl: {cmd}")
        state = self._current.get(station)
        if state is None:
            return RESULT_UNKNOWN
        if not state.configured:
            return RESULT_NOT_CONFIGURED
        if self._mqtt != MQTT_CONNECTED or self._publisher is None:
            return RESULT_MQTT_DOWN
        if state.offline:
            return RESULT_OFFLINE
        if not self._publisher(messages.cmd_topic(station), messages.command_payload(cmd)):
            return RESULT_MQTT_DOWN
        log.info("Befehl %s an Waage %d gesendet", cmd, station)
        return RESULT_SENT

    # ------------------------------------------------------------ intern

    def _reason(self, raw: _Raw | None) -> str | None:
        if self._mqtt != MQTT_CONNECTED:
            return REASON_BROKER
        if self._bridge == "offline":
            return REASON_BRIDGE
        if raw is None or self._clock() - raw.received_mono > self._silent_after:
            return REASON_SILENT
        if raw.data["status"] == messages.STATUS_OFFLINE:
            return REASON_SCALE
        return None

    def _build(self, station: int, previous: StationScale | None) -> StationScale:
        name, configured = self._stations.get(station, (f"Waage {station}", False))
        raw = self._raw.get(station)
        data = raw.data if raw else {}
        reason = self._reason(raw)
        if reason:
            since = previous.offline_since if previous is not None and previous.offline else self._now_iso()
            return StationScale(
                station=station, name=name, configured=configured,
                status=messages.STATUS_OFFLINE, offline_reason=reason, offline_since=since,
                weight_g=None, stable=False, scale_stable=None, net=None,
                capacity_g=data.get("capacity_g"), resolution_g=data.get("resolution_g"),
                ts=data.get("ts"), received_at=raw.received_at if raw else None,
            )
        return StationScale(
            station=station, name=name, configured=configured,
            status=data["status"], offline_reason=None, offline_since=None,
            weight_g=data["weight_g"], stable=data["stable"], scale_stable=data["scale_stable"],
            net=data["net"], capacity_g=data["capacity_g"], resolution_g=data["resolution_g"],
            ts=data["ts"], received_at=raw.received_at,
        )

    def _refresh(self, stations: list[int] | None = None) -> None:
        for station in stations if stations is not None else self.known_stations():
            previous = self._current.get(station)
            state = self._build(station, previous)
            self._current[station] = state
            if not state.same_as(previous):
                if previous is not None and state.offline != previous.offline:
                    if state.offline:
                        log.warning("Waage %d offline (%s)", station, state.offline_reason)
                    else:
                        log.info("Waage %d wieder verbunden", station)
                self._emit({"type": "scale", **state.to_dict()})
        for station in list(self._current):
            if station not in self._stations and station not in self._raw:
                del self._current[station]

    def _emit(self, event: dict) -> None:
        for queue in list(self._subs):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    def _log_throttled(self, kind: str, text: str) -> None:
        now = self._clock()
        last = self._log_last.get(kind)
        if last is None or now - last >= LOG_EVERY_S:
            self._log_last[kind] = now
            log.warning(text)
