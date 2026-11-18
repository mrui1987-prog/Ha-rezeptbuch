"""Zeilenzerlegung und Telegramm der KERN KFB-TM (docs/waage.md Abschnitt 3).

Beispiele (vor CR LF): `ST,G    0.077kg`, `US,G    0.091kg`, `ST,N    0.000kg`,
`-----`. Gewichte werden exakt über Dezimalzahlen in ganze Gramm umgerechnet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MAX_LINE = 64  # Längenschutz: so viele Zeichen ohne Zeilenende → verwerfen

WEIGHT = "weight"
INVALID = "invalid"        # `-----`: kein gültiger Wert, aber Lebenszeichen
UNREADABLE = "unreadable"  # alles andere

_LINE = re.compile(
    r"^(?P<flag>ST|US),(?P<mode>GS|NT|G|N)\s*(?P<value>[+-]?\s*\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z]+)$"
)
_DASHES = re.compile(r"^-{3,}$")


@dataclass(frozen=True)
class Reading:
    kind: str
    weight_g: int | None = None
    scale_stable: bool | None = None
    net: bool | None = None
    text: str = ""


class LineSplitter:
    """Zerlegt einen Bytestrom (TCP oder MQTT-Pakete) in Zeilen.

    Zeilenende ist CR LF; ein einzelnes CR oder LF gilt ebenfalls. Leere Zeilen
    entfallen. Kommt MAX_LINE Zeichen lang kein Zeilenende, wird der Puffer als
    überlange Zeile gemeldet (`None`) und verworfen.
    """

    def __init__(self, max_line: int = MAX_LINE) -> None:
        self.max_line = max_line
        self._buf = bytearray()
        self._overlong = False

    def feed(self, data: bytes) -> list[str | None]:
        out: list[str | None] = []
        for byte in data:
            if byte in (0x0D, 0x0A):
                if self._overlong:
                    self._overlong = False
                elif self._buf:
                    out.append(self._buf.decode("ascii", errors="replace"))
                self._buf.clear()
                continue
            if self._overlong:
                continue
            self._buf.append(byte)
            if len(self._buf) > self.max_line:
                out.append(None)
                self._buf.clear()
                self._overlong = True
        return out

    def reset(self) -> None:
        self._buf.clear()
        self._overlong = False


def kg_to_g(value: str) -> int:
    """'0.077' → 77; kaufmännisch gerundet, ohne float."""
    grams = Decimal(value.replace(" ", "")) * 1000
    return int(grams.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_line(line: str | None) -> Reading:
    """Wertet eine Zeile ohne Zeilenende aus."""
    if line is None:
        return Reading(UNREADABLE, text="<überlange Zeile>")
    text = line.strip()
    if _DASHES.match(text):
        return Reading(INVALID, text=text)
    match = _LINE.match(text)
    if not match or match["unit"] != "kg":
        return Reading(UNREADABLE, text=text)
    try:
        grams = kg_to_g(match["value"])
    except InvalidOperation:
        return Reading(UNREADABLE, text=text)
    return Reading(
        WEIGHT,
        weight_g=grams,
        scale_stable=match["flag"] == "ST",
        net=match["mode"] in ("N", "NT"),
        text=text,
    )


def format_line(weight_g: int | None, stable: bool = True, net: bool = False) -> str:
    """Erzeugt eine KERN-Zeile ohne Zeilenende (für Simulator und Tests)."""
    if weight_g is None:
        return "-----"
    flag = "ST" if stable else "US"
    mode = "N" if net else "G"
    kg = Decimal(weight_g) / 1000
    return f"{flag},{mode}{kg:>9.3f}kg"
