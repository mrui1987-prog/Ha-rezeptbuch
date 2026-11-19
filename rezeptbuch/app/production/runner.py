"""Waage im Wiegeablauf je Station (Modul 09, docs/ablauf.md Abschnitte 2 und 6).

Stand Teil C1 (0.9.0): Der Runner liest den Zustand der Waage über den Mittelsmann (Modul 08,
``ScaleHub.current_state``) und führt je Station den **Tara-Bezug der Software** (6.1):
``Ist = angezeigter Wert − Tara-Bezug``. Der Bezug wird beim Start, beim „Weiter“, nach jeder
Quittung und auf Tastendruck auf den angezeigten Wert gesetzt; er liegt nur im Speicher und ist
nach einem Neustart unbekannt (K09-4: beim „Weiter“ neu).

Teil C2 (0.9.1) ergänzt Tara an der Waage mit Bestätigung, Auto-Quittung, Höchstlast-Warnung,
45-s-Pause, Behälter wiegen/wechseln und Live-Nachrichten ``weigh``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..scales import messages


@dataclass(frozen=True)
class Reading:
    """Ein Messwert für den Ablauf (aus dem Zustand des Mittelsmanns)."""
    station: int
    status: str                 # ok / invalid / error / offline / unknown
    weight_g: int | None
    stable: bool
    reference_g: int | None     # Tara-Bezug der Software; leer = unbekannt

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
                "reference_g": self.reference_g, "actual_g": self.actual_g}


class ProductionRunner:
    """Waagenzugriff des Ablaufs; ``hub`` ist der Mittelsmann (oder ``None`` ohne Waagen-Anbindung)."""

    def __init__(self, hub=None) -> None:
        self.hub = hub
        self._reference: dict[int, int] = {}

    def reading(self, station: int) -> Reading:
        state = self.hub.current_state(station) if self.hub is not None else None
        if state is None:
            return Reading(station, "unknown", None, False, self._reference.get(station))
        weight = state.weight_g if state.status == messages.STATUS_OK else None
        return Reading(station, state.status, weight, bool(state.stable), self._reference.get(station))

    def set_reference(self, station: int) -> int | None:
        """Tara der Software: Bezug = angezeigter Wert. Ohne gültigen Wert bleibt der Bezug unbekannt."""
        reading = self.reading(station)
        if reading.usable:
            self._reference[station] = reading.weight_g
            return reading.weight_g
        self._reference.pop(station, None)
        return None

    def clear(self, station: int) -> None:
        self._reference.pop(station, None)

    def broadcast(self, event: dict) -> None:
        """Nachricht an alle Teilnehmer des Live-Kanals (Typen ``batch`` und ``orders``)."""
        if self.hub is not None:
            self.hub.broadcast(event)
