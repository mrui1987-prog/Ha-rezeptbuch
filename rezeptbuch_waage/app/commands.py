"""Befehlswarteschlange je Waage (docs/waage.md 6.3, K07-3).

`tare` und `zero` kommen per MQTT als `{"v":2,"cmd":"tare"|"zero"}` und gehen
als `T`/`Z` mit CR LF an die Waage. Zwischen zwei Befehlen an dieselbe Waage
liegt mindestens 1 s (Feldtest 11.4: schnelle Befehle gingen teils verloren).
Weitere Befehle warten, höchstens einer je Art; doppelte werden
zusammengefasst. Keine eigene Bestätigung – die Wirkung zeigt der nächste
Zustand. Ohne Ein-/Ausgabe, Zeiten werden übergeben.
"""

from __future__ import annotations

MIN_INTERVAL_S = 1.0

# Zeichen an die Waage (KFB-TM Fernsteuerbefehle, Feldtest 5)
WIRE: dict[str, bytes] = {"tare": b"T\r\n", "zero": b"Z\r\n"}
NAMES: dict[str, str] = {"tare": "Tara", "zero": "Nullstellen"}

QUEUED = "queued"
MERGED = "merged"


class CommandQueue:
    def __init__(self, min_interval_s: float = MIN_INTERVAL_S) -> None:
        self.min_interval_s = min_interval_s
        self.pending: list[str] = []
        self.last_sent_at: float | None = None

    def add(self, cmd: str) -> str:
        """Stellt einen Befehl ein; ein wartender gleicher wird zusammengefasst."""
        if cmd not in WIRE:
            raise ValueError(f"unbekannter Befehl {cmd!r}")
        if cmd in self.pending:
            return MERGED
        self.pending.append(cmd)
        return QUEUED

    def ready(self, now: float) -> bool:
        """Ein Befehl wartet und der Mindestabstand ist eingehalten."""
        if not self.pending:
            return False
        return self.last_sent_at is None or now - self.last_sent_at >= self.min_interval_s

    def pop(self, now: float) -> str:
        cmd = self.pending.pop(0)
        self.last_sent_at = now
        return cmd

    def clear(self) -> list[str]:
        dropped, self.pending = self.pending, []
        return dropped
