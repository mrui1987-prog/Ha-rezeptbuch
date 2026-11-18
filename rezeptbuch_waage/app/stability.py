"""Stabilität in der Software (M07-3, docs/waage.md Abschnitt 4).

Stabil, wenn seit mindestens `window_s` nur gültige Gewichte gekommen sind und
deren größter und kleinster Wert im Fenster höchstens `span_g` auseinanderliegen.
`reset()` beginnt das Fenster neu (bei `-----`, unlesbar, offline, brutto/netto).
Zeiten sind monotone Sekunden und werden übergeben (testbar ohne Warten).
"""

from __future__ import annotations

from collections import deque


class StabilityChecker:
    def __init__(self, window_ms: int = 1000, span_g: int = 2) -> None:
        self.window_s = window_ms / 1000
        self.span_g = span_g
        self._samples: deque[tuple[float, int]] = deque()
        self._since: float | None = None
        self._net: bool | None = None

    def reset(self) -> None:
        self._samples.clear()
        self._since = None
        self._net = None

    def add(self, now: float, weight_g: int, net: bool = False) -> None:
        if self._net is not None and net != self._net:
            self.reset()
        self._net = net
        if self._since is None:
            self._since = now
        self._samples.append((now, weight_g))
        self._prune(now)

    def _prune(self, now: float) -> None:
        # Werte vor dem Fenster entfallen – bis auf den letzten davor, denn er
        # galt noch zu Beginn des Fensters (vorsichtige Auslegung)
        limit = now - self.window_s
        while len(self._samples) > 1 and self._samples[1][0] <= limit:
            self._samples.popleft()

    def spread(self, now: float) -> int | None:
        """Spanne (max − min) im aktuellen Fenster, None ohne Werte."""
        if not self._samples:
            return None
        self._prune(now)
        weights = [w for _, w in self._samples]
        return max(weights) - min(weights)

    def is_stable(self, now: float) -> bool:
        if self._since is None or now - self._since < self.window_s:
            return False
        spread = self.spread(now)
        return spread is not None and spread <= self.span_g
