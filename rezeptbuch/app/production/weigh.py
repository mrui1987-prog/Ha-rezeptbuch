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
  Toleranz und Wanderung (Höchst- minus Mindestwert) ≤ ``auto_ack_span_g``; dazu Ist mindestens
  das halbe Soll und mindestens 1 g (Befund B1, Michael 19.11.2026: sonst würde z. B. 4 g ± 20 g schon
  bei 0 g quittiert) und mindestens die „Mindestlast Autoquittierung“ (Einstellung, Standard 70 g);
  darunter wird von Hand quittiert.
* **Tara ausgeführt** (Befund B2, Michael 19.11.2026, 15:21): auch wenn schon die nächste Zutat
  aufliegt – die Waage springt von brutto auf netto, oder die Anzeige fällt um das tarierte Gewicht.
  Der Nullpunkt ist dann 0 netto. Gilt ebenso für eine verspätet ausgeführte Tara.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LATE_TARE_WINDOW_S = 30.0       # so lange wird ein verspäteter Tara-Sprung noch erkannt
STROKES_EMPTY_S = 1.0           # so lange Striche vor einem Null von Hand = Last war abgenommen (Vorschlag 27.11.)
MANUAL_JUMP_S = 3.0             # Tara/Null von Hand: ruhiger Wert → ~0 ohne Zwischengewicht in höchstens 3 s
                                # (die KERN zeigt beim Tarieren/Nullen kurz Striche; Befund Michael 24.11.2026, 12:37)
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
    peak_g: int | None = None            # höchste Anzeige seit dem Tara-Befehl (B2)
    hint: str | None = None
    last: Sample | None = None
    last_at: float | None = None         # Zeit des letzten Werts (Sprung-Erkennung)
    anchor: Sample | None = None         # letzter ruhiger gültiger Wert (Sprung-Erkennung, M09-19)
    anchor_at: float | None = None
    anchor_dirty: bool = False           # seit dem Anker ein Zwischengewicht gesehen (= Abheben, keine Taste)
    hidden_g: int = 0                    # Last, die ein Nullstellen von Hand an der Waage „versteckt“ hat
    manual_delta_g: int | None = None    # letzter erkannter Sprung durch eine Taste an der Waage
    strokes_since: float | None = None   # Waage zeigt seit … Striche (ungültig)
    strokes_s: float = 0.0               # Dauer der letzten Strich-Phase vor dem aktuellen gültigen Wert
    before_strokes: Sample | None = None # letzter gültiger Wert vor der Strich-Phase
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
            return sample.weight_g + self.hidden_g
        if self.scale_tare_g is None:
            return None
        return self.scale_tare_g + sample.weight_g + self.hidden_g

    def offset(self, sample: Sample | None = None) -> int | None:
        """Gesamtlast − Anzeige (Tara der Waage + von Hand Genulltes); ``None`` = unbekannt."""
        gross = self.gross(sample)
        sample = sample or self.last
        return None if gross is None else gross - sample.weight_g

    def set_offset(self, sample: Sample, offset: int) -> None:
        """Gesamtlast = Anzeige + ``offset`` (nach „Weiter“ ohne neue Tara, M09-17)."""
        if sample.net is False:
            self.scale_tare_g, self.hidden_g = 0, offset
        else:
            self.scale_tare_g, self.hidden_g = offset, 0

    def _manual_jump(self, previous: Sample | None, sample: Sample, now: float, span_g: int) -> tuple[str, int] | None:
        """Tara oder Null von Hand an der Waage (M09-19: Tasten an der Waage ändern nie Ist oder Tara der Software).
        Anker = letzter **ruhige** gültige Wert. Kommt innerhalb von ``MANUAL_JUMP_S`` ein Wert bei ~0 und lag
        dazwischen **kein Zwischengewicht** (nur Striche/ungültige Werte oder Werte beim Anker bzw. bei 0), war es
        eine Taste: Netto danach = Tara von Hand; brutto danach = Null von Hand (die KERN löscht dabei die Tara und
        „versteckt“ die Last); brutto → netto ~0 = Tara von Hand. Abheben zeigt Zwischengewichte, bei tarierter
        Waage ins Minus (``-----``). Der Ausgleich (Gesamtlast − Anzeige) wächst um den Sprung, die Gesamtlast
        bleibt. Gibt (Art, Sprung in g) zurück.
        Befund Michael 24.11.2026, 12:37: Die alte Regel (zwei aufeinanderfolgende Werte ≤ 0,7 s) griff an der KERN
        nie – sie zeigt beim Tastendruck kurz Striche."""
        anchor = self.anchor
        if sample.ok and sample.stable and abs(sample.weight_g) > span_g:
            self.anchor, self.anchor_at, self.anchor_dirty = sample, now, False      # neuer Anker
            return None
        if not sample.ok:
            return None                                    # Striche: Anker bleibt
        if abs(sample.weight_g) > span_g:
            if anchor is not None and abs(sample.weight_g - anchor.weight_g) > span_g:
                self.anchor_dirty = True                   # Zwischengewicht = Last bewegt, keine Taste
            return None
        # Wert bei ~0
        hit = None
        before = self.before_strokes
        if (self.strokes_s >= STROKES_EMPTY_S and sample.net is False and before is not None
                and before.net is True and self.scale_tare_g is not None):
            # Befund 24.11.2026 / Vorschlag angenommen 27.11.2026, 14:39 (Michael): erst längere Zeit Striche
            # (Behälter abgenommen, Waage unter 0), dann brutto ~0 = Null von Hand auf der LEEREN Waage. Nichts ist
            # versteckt: Gesamtlast = Anzeige, Ausgleich 0. Die Tara-Summe der Software bleibt, damit das Ist mit
            # dem wieder aufgestellten Behälter weiterstimmt.
            if self.reference_g is not None:
                self.reference_g += self.scale_tare_g + self.hidden_g
            self.scale_tare_g, self.hidden_g = 0, 0
            self.anchor, self.anchor_at, self.anchor_dirty = None, None, False
            self.before_strokes = None
            return ("manual_zero_empty", 0)
        if anchor is not None and not self.anchor_dirty and self.anchor_at is not None \
                and now - self.anchor_at <= MANUAL_JUMP_S:
            delta = anchor.weight_g - sample.weight_g
            if anchor.net is False and sample.net is True:
                self.scale_tare_g = delta                  # Tara von Hand auf brutto zeigender Waage
                hit = ("manual_tare", delta)
            elif anchor.net is True and anchor.weight_g > span_g and self.scale_tare_g is not None:
                if sample.net is True:
                    self.scale_tare_g += delta             # Tara von Hand auf tarierter Waage
                    hit = ("manual_tare", delta)
                else:
                    self.hidden_g += self.scale_tare_g + delta   # Null von Hand: Tara gelöscht, Last versteckt
                    self.scale_tare_g = 0
                    hit = ("manual_zero", delta)
        self.anchor, self.anchor_at, self.anchor_dirty = None, None, False
        return hit

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
        self.peak_g = sample.weight_g
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
        self.hidden_g = 0
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

    def _tare_executed(self, previous: Sample | None, sample: Sample, before: int, span_g: int) -> bool:
        """Hat die Waage die Tara ausgeführt, obwohl schon wieder Last aufliegt (B2)?
        Ja, wenn sie von brutto auf netto springt oder die Anzeige gegenüber dem Höchstwert seit dem
        Befehl um das tarierte Gewicht gefallen ist (auch wenn inzwischen Last dazukam)."""
        if not sample.ok or abs(before) <= span_g:
            return False
        if previous is not None and previous.ok and previous.net is False and sample.net is True:
            return True
        peak = self.peak_g if self.peak_g is not None else before
        return peak - sample.weight_g >= before - span_g

    def _track_peak(self, sample: Sample) -> None:
        if sample.ok:
            self.peak_g = sample.weight_g if self.peak_g is None else max(self.peak_g, sample.weight_g)

    def observe(self, now: float, sample: Sample, tare_confirm_s: float, span_g: int,
                watch_manual: bool = False) -> list[str]:
        """Neuer Zustand der Waage: Tara-Bestätigung, Zeitablauf, verspäteter Sprung, Tara der Waage.

        Gibt Ereignisse zurück: ``tare_confirmed``, ``tare_timeout``, ``late_tare``, ``manual_tare``,
        ``manual_zero`` (nur mit ``watch_manual``: kein eigener Befehl unterwegs, kein Behälter-Schritt).
        """
        events: list[str] = []
        previous = self.last
        changed = previous is None or sample != previous
        watching = watch_manual and not self.taring and self.late_tare_g is None
        if not watching:
            self.anchor, self.anchor_at, self.anchor_dirty = None, None, False   # eigene Befehle nie als Taste deuten
        if watching and sample.ok and sample.stable and abs(sample.weight_g) > span_g and (
                self.anchor is None or sample == self.anchor):
            # ruhiger Wert steht (auch unverändert): Anker setzen bzw. „zuletzt gesehen“ nachführen
            if self.anchor is None:
                self.anchor_dirty = False
            self.anchor, self.anchor_at = sample, now
        if sample.status == "invalid":
            if self.strokes_since is None:
                self.strokes_since = now
                self.before_strokes = self.last if self.last is not None and self.last.ok else None
        elif sample.ok:
            self.strokes_s = 0.0 if self.strokes_since is None else now - self.strokes_since
            self.strokes_since = None
        if changed and watching:
            jump = self._manual_jump(previous, sample, now, span_g)
            if jump:
                kind, delta = jump
                events.append(kind)
                self.manual_delta_g = delta
                if self.reference_g is not None and kind != "manual_zero_empty":
                    # auch beim laufenden Wiegen: das Ist bleibt (M09-19)
                    self.reference_g -= delta
                    self.reset_ack()
                elif kind == "manual_zero_empty":
                    self.reset_ack()
        self.last = sample
        self.last_at = now                                 # letzte Beobachtung (Hintergrund alle 0,2 s)
        if sample.ok and sample.net is False and "manual_zero" not in events:
            self.scale_tare_g = 0
        if self.taring and self._tare_executed(previous, sample, self.taring_before_g or 0, span_g):
            # Tara ausgeführt, die nächste Zutat liegt schon auf: Nullpunkt = 0 netto (B2)
            before = self.taring_before_g or 0
            if self.scale_tare_g is not None:
                self.scale_tare_g += before
            self.reference_g = 0
            self.taring_since = None
            self.hint = None
            events.append("tare_confirmed")
        elif self.taring:
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
                self.peak_g = None
                self.taring_since = None
                self.hint = "Tara an der Waage nicht bestätigt – die Software rechnet weiter."
                if self.taring_before_g and abs(self.taring_before_g) > span_g:
                    self.late_tare_g = self.taring_before_g
                    self.late_until = now + LATE_TARE_WINDOW_S
                events.append("tare_timeout")
        elif self.late_tare_g is not None:
            if now > self.late_until:
                self.late_tare_g = None
            elif self._tare_executed(previous, sample, self.late_tare_g, span_g):
                # Die Waage hat die Tara doch noch ausgeführt (auch mit Last drauf, B2): Nullpunkt = 0 netto
                self.reference_g = 0
                if self.scale_tare_g is not None:
                    self.scale_tare_g += self.late_tare_g
                self.late_tare_g = None
                self.hint = None
                self.reset_ack()
                events.append("late_tare")
        if self.taring or self.late_tare_g is not None:
            self._track_peak(sample)
        else:
            self.peak_g = None
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
                 seconds: float, span_g: int, min_load_g: int = 0) -> bool:
        """Fortschritt der Auto-Quittung; True, sobald quittiert werden darf (6.3)."""
        sample = self.last
        good = (sample is not None and sample.ok and sample.stable and not self.taring and actual_g is not None
                and abs(actual_g - target_g) <= tolerance_g and actual_g >= auto_ack_minimum(target_g, min_load_g))
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


def auto_ack_minimum(target_g: int, min_load_g: int = 0) -> int:
    """Kleinstes Ist für die Auto-Quittung: halbes Soll (aufgerundet), mindestens 1 g (Befund B1) und
    mindestens die Mindestlast (Einstellung). Von Hand quittieren gilt weiter die volle Toleranz."""
    return max(1, (target_g + 1) // 2, min_load_g)


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
