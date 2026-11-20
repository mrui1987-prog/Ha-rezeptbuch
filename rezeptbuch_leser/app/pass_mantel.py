"""Mantel um den freigegebenen Kennzeichnungspass-Leser (K04-17: Leser-Code unverändert).

Liefert das Leser-Ergebnis für den Vertrag: status, meldung, daten (Schema 2),
warnungen, plausibilitaet, seiten.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pdfplumber

from .vertrag import FALSCHES_DOKUMENT, MAX_SEITEN, OK, UNLESBAR

# Der Leser liegt als eigenständige Module vor (wie früher unter tools/kennzeichnungspass)
_LESER_DIR = str(Path(__file__).resolve().parent / "leser")
if _LESER_DIR not in sys.path:
    sys.path.insert(0, _LESER_DIR)

import kennzeichnungspass  # noqa: E402
import zwischenstruktur  # noqa: E402

BETREFF = "Produktspezifikation"


def lese_kennzeichnungspass(pfad: str | Path, dateiname: str | None = None) -> dict:
    pfad = Path(pfad)
    with pdfplumber.open(pfad) as pdf:
        seiten = len(pdf.pages)
        betreff = (pdf.metadata.get("Subject") or "").strip()
    if betreff != BETREFF:
        return {"status": FALSCHES_DOKUMENT, "seiten": seiten,
                "meldung": "Kein Kennzeichnungspass (PDF-Betreff ist nicht „Produktspezifikation“)."}
    if seiten > MAX_SEITEN:
        return {"status": UNLESBAR, "seiten": seiten,
                "meldung": f"PDF hat {seiten} Seiten – so lange Pässe kennt der Leser nicht."}
    roh = kennzeichnungspass.lese_pdf_roh(pfad)
    if "schema" not in roh:
        warn = roh.get("warnungen") or []
        return {"status": UNLESBAR, "seiten": seiten, "warnungen": warn,
                "meldung": "Pass nicht lesbar: " + ("; ".join(warn) or "unbekannter Aufbau")}
    daten = zwischenstruktur.aus_roh(roh)
    if dateiname and isinstance(daten.get("quelle"), dict):
        daten["quelle"]["datei"] = dateiname   # statt des Namens der Wegwerfdatei
    warn = list(daten.get("warnungen") or [])
    plaus = list(daten.get("plausibilitaet") or [])
    if warn:
        return {"status": UNLESBAR, "seiten": seiten, "daten": daten, "warnungen": warn,
                "plausibilitaet": plaus,
                "meldung": "Pass nicht vollständig lesbar – nichts wird übernommen."}
    return {"status": OK, "seiten": seiten, "daten": daten, "plausibilitaet": plaus}
