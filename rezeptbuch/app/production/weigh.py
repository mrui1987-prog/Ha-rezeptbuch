"""Wiegelogik je Station, ohne Datenbank und Netz (Modul 09 Teil C2, docs/ablauf.md Abschnitt 6).

Alles hier rechnet mit Werten und einer Uhr (Sekunden), damit es ohne Warten getestet werden kann.

* **Ist** (6.1) = angezeigter Wert − Tara-Bezug der Software.
* **Tara** (6.2, M09-5, K09-3): Bezug sofort = angezeigter Wert; der Runner sendet ``tare`` an die
  Waage. Phase „Tara läuft“, bis die Waage stabil bei ~0 meldet (höchstens ``tare_confirm_seconds``);
  dann Bezug = dieser Wert. Ohne Bestätigung bleibt der Software-Bezug (Hinweis); springt die Anzeige
  später um genau den Bezug, wird nachgeführt.
* **Gesamtlast** (6.4) = Tara der Waage + angezeigter Wert. Die Tara der Waage ist bekannt, solange
  die Software jede Tara/Null mitverfolgt hat; zeigt die Waage brutto (``net`` falsch), ist sie 0.
* **Auto-Quittung** (6.3, M09-4): durchgehend ``auto_ack_seconds`` lang Status ok, stabil, in der
  Toleranz und Wanderung (Höchst- minus Mindestwert) ≤ ``auto_ack_span_g``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LATE_TARE_WINDOW_S = 30.0       # so lange wird ein verspäteter Tara-Sprung noch erkannt
EMPTY_LIMIT_G = 50              # „leer“ bzw. „Last weg“ (wie die Null-Grenze der Waage, Z07-1)


@dataclass(frozen=True)
class Sample:
    """Ein Zustand der Waage (aus dem Mittelsmann)."""
    status: str                 # ok / invalid / error / offline / unknown
    weight_g: int | None
    stable: bool
    net: bool | None = None
    capacity_g: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.weight_g is not None


@dataclass
class StationWeigh:
    """Zustand einer Station für den Ablauf."""
    reference_g: int | None = None       # Tara-Bezug der Software
    scale_tare_g: int | None = 0         # Tara der Waage (brutto = Tara + Anzeige); None = unbekannt
    taring_since: float | None = None    # Tara läuft seit …
    taring_before_g: int | None = None   # Anzeige beim Tara-Befehl
    late_tare_g: int | None = None       # nicht bestätigte Tara, die noch nachkommen kann
    late_until: float = 0.0
    hint: str | None = None
    last: Sample | None = None
    # Auto-Quittung
    ack_since: float | None = None
    ack_min: int | None = None
    ack_max: int | None = None
    progress: int = 0
    events: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ Grundwerte

    @property
    def taring(self) -> bool:
        return self.taring_since is not None

    def actual(self, sample: Sample | None = None) -> int | None:
        sample = sample or self.last
        if sample is None or not sample.ok or self.reference_g is None:
            return None
        return sample.weight_g - self.reference_g

    def gross(self, sample: Sample | None = None) -> int | None:
        sample = sample or self.last
        if sample is None or not sample.ok:
            return None
        if sample.net is False:
            return sample.weight_g
        if self.scale_tare_g is None:
            return None
        return self.scale_tare_g + sample.weight_g

    def tare_total(self) -> int | None:
        """Tara gesamt für das Protokoll: Tara der Waage + Bezug der Software (sonst nur der Bezug)."""
        if self.reference_g is None:
            return None
        return self.reference_g + (self.scale_tare_g or 0)

    # ------------------------------------------------------------------ Tara und Null

    def start_tare(self, now: float, sample: Sample) -> int | None:
        """Tara-Befehl: Bezug sofort = Anzeige. Ohne gültigen Wert bleibt der Bezug unbekannt."""
        self.reset_ack()
        self.late_tare_g = None
        if not sample.ok:
            self.reference_g = None
            self.taring_since = None
            return None
        self.reference_g = sample.weight_g
        self.taring_since = now
        self.taring_before_g = sample.weight_g
        self.hint = None
        return sample.weight_g

    def software_only(self, sample: Sample) -> int | None:
        """Bezug nur in der Software setzen (ohne Befehl an die Waage)."""
        self.reset_ack()
        self.taring_since = None
        self.reference_g = sample.weight_g if sample.ok else None
        return self.reference_g

    def zeroed(self) -> None:
        """Nach ``zero``: Waage zeigt brutto 0, Tara der Waage 0."""
        self.scale_tare_g = 0
        self.taring_since = None
        self.late_tare_g = None
        self.reset_ack()

    def clear(self) -> None:
        self.reference_g = None
        self.taring_since = None
        self.late_tare_g = None
        self.hint = None
        self.reset_ack()

    # ------------------------------------------------------------------ Beobachten

    def observe(self, now: float, sample: Sample, tare_confirm_s: float, span_g: int) -> list[str]:
        """Neuer Zustand der Waage: Tara-Bestätigung, Zeitablauf, verspäteter Sprung, Tara der Waage.

        Gibt Ereignisse zurück: ``tare_confirmed``, ``tare_timeout``, ``late_tare``.
        """
        events: list[str] = []
        previous = self.last
        self.last = sample
        if sample.ok and sample.net is False:
            self.scale_tare_g = 0
        if self.taring:
            if sample.ok and sample.stable and abs(sample.weight_g) <= span_g:
                before = self.taring_before_g or 0
                # Tara der Waage wächst um die Anzeige beim Befehl (tara auf leerer Waage bleibt brutto)
                if sample.net is not False and self.scale_tare_g is not None:
                    self.scale_tare_g += before
                self.reference_g = sample.weight_g
                self.taring_since = None
                self.hint = None
                events.append("tare_confirmed")
            elif now - self.taring_since >= tare_confirm_s:
                self.taring_since = None
                self.hint = "Tara an der Waage nicht bestätigt – die Software rechnet weiter."
                if self.taring_before_g and abs(self.taring_before_g) > span_g:
                    self.late_tare_g = self.taring_before_g
                    self.late_until = now + LATE_TARE_WINDOW_S
                events.append("tare_timeout")
        elif self.late_tare_g is not None:
            if now > self.late_until:
                self.late_tare_g = None
            elif (sample.ok and previous is not None and previous.ok
                  and abs((previous.weight_g - sample.weight_g) - self.late_tare_g) <= span_g):
                # Die Waage hat die Tara doch noch ausgeführt: Bezug nachführen
                if self.reference_g is not None:
                    self.reference_g -= self.late_tare_g
                if self.scale_tare_g is not None and sample.net is not False:
                    self.scale_tare_g += self.late_tare_g
                self.late_tare_g = None
                self.hint = None
                self.reset_ack()
                events.append("late_tare")
        if sample.ok and sample.net is True and self.scale_tare_g == 0 and previous is None:
            # Neustart: Waage zeigt netto, Tara unbekannt
            self.scale_tare_g = None
        return events

    # ------------------------------------------------------------------ Auto-Quittung

    def reset_ack(self) -> None:
        self.ack_since = None
        self.ack_min = self.ack_max = None
        self.progress = 0

    def auto_ack(self, now: float, actual_g: int | None, target_g: int, tolerance_g: int,
                 seconds: float, span_g: int) -> bool:
        """Fortschritt der Auto-Quittung; True, sobald quittiert werden darf (6.3)."""
        sample = self.last
        good = (sample is not None and sample.ok and sample.stable and not self.taring and actual_g is not None
                and abs(actual_g - target_g) <= tolerance_g)
        if not good:
            self.reset_ack()
            return False
        if self.ack_since is None:
            self.ack_since, self.ack_min, self.ack_max = now, actual_g, actual_g
        else:
            low, high = min(self.ack_min, actual_g), max(self.ack_max, actual_g)
            if high - low > span_g:
                # zu viel Wanderung: Zeit beginnt neu
                self.ack_since, self.ack_min, self.ack_max = now, actual_g, actual_g
            else:
                self.ack_min, self.ack_max = low, high
        elapsed = now - self.ack_since
        self.progress = 100 if seconds <= 0 else min(100, int(elapsed * 100 / seconds))
        return elapsed >= seconds


def zone(actual_g: int | None, target_g: int, tolerance_g: int) -> str | None:
    """Bereich für den Balken: low, ok, high."""
    if actual_g is None:
        return None
    if actual_g < target_g - tolerance_g:
        return "low"
    if actual_g > target_g + tolerance_g:
        return "high"
    return "ok"


def capacity_warning(gross_g: int | None, display_g: int | None, capacity_g: int | None, warn_g: int,
                     remaining_g: int = 0) -> bool:
    """Höchstlast-Vorwarnung (6.4, M09-7): Gesamtlast (sonst Anzeige) + noch zu wiegende Menge
    ≥ Höchstlast − Vorwarnung."""
    if capacity_g is None:
        return False
    load = gross_g if gross_g is not None else display_g
    if load is None:
        return False
    return load + max(remaining_g, 0) >= capacity_g - warn_g
