"""Mantel um den BÄKO-Belegleser (docs/kennzeichnungspass-import.md 15.4, M04-25).

Liefert das Leser-Ergebnis für den Vertrag: status, meldung, daten (Schema 1),
warnungen, plausibilitaet, seiten. Nur `ok` darf Add-on 1 übernehmen.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pdfplumber

from .vertrag import FALSCHES_DOKUMENT, MAX_SEITEN, OK, UNLESBAR

_LESER_DIR = str(Path(__file__).resolve().parent / "leser")
if _LESER_DIR not in sys.path:
    sys.path.insert(0, _LESER_DIR)

import baeko_beleg  # noqa: E402


def lese_baeko_beleg(pfad: str | Path, dateiname: str | None = None) -> dict:
    pfad = Path(pfad)
    with pdfplumber.open(pfad) as pdf:
        seiten = len(pdf.pages)
        erste = (pdf.pages[0].extract_text() or "") if seiten else ""
    if not baeko_beleg.ist_baeko_beleg(erste):
        return {"status": FALSCHES_DOKUMENT, "seiten": seiten,
                "meldung": "Kein BÄKO-Beleg (Auftragsbestätigung, Rechnung oder Gutschrift) – "
                           "oder ein Scan ohne Text."}
    if seiten > MAX_SEITEN:
        return {"status": UNLESBAR, "seiten": seiten,
                "meldung": f"Beleg hat {seiten} Seiten – mehr als {MAX_SEITEN} liest der Leser nicht."}
    daten = baeko_beleg.lese_beleg(pfad)
    if dateiname:
        daten["datei"] = dateiname
    warn = list(daten.get("warnungen") or [])
    plaus = list(daten.get("plausibilitaet") or [])
    if warn:
        return {"status": UNLESBAR, "seiten": seiten, "daten": daten, "warnungen": warn,
                "plausibilitaet": plaus,
                "meldung": "Beleg nicht sicher lesbar (Aufbau unbekannt oder Summen stimmen nicht) – "
                           "nichts wird übernommen."}
    return {"status": OK, "seiten": seiten, "daten": daten, "plausibilitaet": plaus}
