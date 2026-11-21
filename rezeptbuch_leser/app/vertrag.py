"""JSON-Vertrag zwischen Add-on 3 und Add-on 1 (docs/kennzeichnungspass-import.md 15.3).

Fassung 1. Neue Felder dürfen hinzukommen; Umbenennen, Entfernen oder eine andere
Bedeutung heben `FORMAT_VERSION` (Hülle) bzw. die Schema-Fassung des Lesers.
"""

from __future__ import annotations

from . import __version__

FORMAT = "rezeptbuch-leser"
FORMAT_VERSION = 1

# Leser, die dieses Add-on anbietet, mit der Fassung ihres Datenschemas
LESER = {
    "kennzeichnungspass": 2,
    "baeko_beleg": 1,
}

OK = "ok"                              # vollständig gelesen, übernehmbar
UNLESBAR = "unlesbar"                  # Aufbau weicht ab oder Warnungen – nichts geraten (M04-10)
FALSCHES_DOKUMENT = "falsches_dokument"
FEHLER = "fehler"                      # Leser abgestürzt oder Zeitüberschreitung
STATUS = (OK, UNLESBAR, FALSCHES_DOKUMENT, FEHLER)

MAX_BYTES = 10 * 1024 * 1024
MAX_SEITEN = 20
ZEITLIMIT_S = 30


def gesundheit() -> dict:
    return {"format": FORMAT, "format_version": FORMAT_VERSION,
            "addon_version": __version__, "leser": dict(LESER)}


def antwort(leser: str, datei: dict, ergebnis: dict) -> dict:
    """Baut die Antwort; `ergebnis` kommt vom Leser (status, meldung, daten, …)."""
    status = ergebnis.get("status")
    if status not in STATUS:
        status, ergebnis = FEHLER, {"meldung": f"Leser lieferte unbekannten Status {status!r}"}
    if status == OK and ergebnis.get("warnungen"):
        status = UNLESBAR          # Sicherung: mit Warnung ist nichts übernehmbar
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "addon_version": __version__,
        "leser": leser,
        "leser_schema": LESER.get(leser),
        "datei": datei,
        "status": status,
        "meldung": ergebnis.get("meldung"),
        "daten": ergebnis.get("daten"),
        "warnungen": list(ergebnis.get("warnungen") or []),
        "plausibilitaet": list(ergebnis.get("plausibilitaet") or []),
    }
