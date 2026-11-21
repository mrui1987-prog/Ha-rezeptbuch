"""Liest eine Datei in einem eigenen Prozess (Zeitlimit, Absturz trifft nicht den Server).

Aufruf:  python3 -m app.worker LESER PFAD [DATEINAME]   → Leser-Ergebnis als JSON auf stdout
         python3 -m app.worker --selbsttest             → prüft pdfplumber und den Pass-Leser
"""

from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

from .vertrag import FALSCHES_DOKUMENT, FEHLER, LESER, OK, UNLESBAR


def lese(leser: str, pfad: str, dateiname: str | None = None) -> dict:
    if leser == "kennzeichnungspass":
        from .pass_mantel import lese_kennzeichnungspass
        return lese_kennzeichnungspass(pfad, dateiname)
    if leser == "baeko_beleg":
        from .beleg_mantel import lese_baeko_beleg
        return lese_baeko_beleg(pfad, dateiname)
    return {"status": FEHLER, "meldung": f"Unbekannter Leser {leser!r}"}


def selbsttest() -> int:
    import pdfplumber
    from .testpdf import beispiel_rechnung, erzeuge_pdf
    erwartet = [
        ("kennzeichnungspass", erzeuge_pdf(1), FALSCHES_DOKUMENT),
        ("kennzeichnungspass", erzeuge_pdf(1, betreff="Produktspezifikation"), UNLESBAR),
        ("baeko_beleg", erzeuge_pdf(1), FALSCHES_DOKUMENT),
        ("baeko_beleg", beispiel_rechnung(), OK),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for nr, (leser, inhalt, status) in enumerate(erwartet):
            pfad = Path(tmp) / f"t{nr}.pdf"
            pfad.write_bytes(inhalt)
            ergebnis = lese(leser, str(pfad))
            if ergebnis["status"] != status:
                print(f"Selbsttest fehlgeschlagen: {status} erwartet, {ergebnis}", file=sys.stderr)
                return 1
    print(f"Selbsttest bestanden (pdfplumber {pdfplumber.__version__}, Leser {sorted(LESER)})")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["--selbsttest"]:
        return selbsttest()
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    try:
        ergebnis = lese(*argv)
    except Exception as exc:  # Leserfehler → Status „fehler“, nie ein Absturz ohne Antwort
        traceback.print_exc(file=sys.stderr)
        ergebnis = {"status": FEHLER, "meldung": f"Leser abgebrochen: {type(exc).__name__}"}
    sys.stdout.write(json.dumps(ergebnis, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
