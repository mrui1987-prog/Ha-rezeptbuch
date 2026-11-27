"""Einstiegspunkt des Lesers (Add-on 3, docs/kennzeichnungspass-import.md 15).

HTTP-Server aus der Standardbibliothek, Port 8100, nur im internen Netz der Add-ons.
Jede Datei wird in einem eigenen Prozess gelesen (Zeitlimit 30 s). Es wird nichts
gespeichert: das PDF liegt nur kurz als Wegwerfdatei vor.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .localtime import setup_timezone
from .vertrag import FEHLER, LESER, MAX_BYTES, MAX_SEITEN, ZEITLIMIT_S, antwort, gesundheit

PORT = 8100
OPTIONS_FILE = Path("/data/options.json")
PFAD_LESEN = re.compile(r"^/v1/lesen/([a-z-]+)$")
PFAD_BILD = re.compile(r"^/v1/seitenbild\?seite=(\d{1,2})$")

log = logging.getLogger("rezeptbuch_leser")


def _sauberer_name(name: str | None) -> str | None:
    if not name:
        return None
    name = os.path.basename(name.replace("\\", "/")).strip()
    name = "".join(z for z in name if z.isprintable())[:200]
    return name or None


def lese_im_prozess(leser: str, inhalt: bytes, dateiname: str | None,
                    zeitlimit: float = ZEITLIMIT_S) -> dict:
    with tempfile.TemporaryDirectory(prefix="leser-") as tmp:
        pfad = Path(tmp) / "eingang.pdf"
        pfad.write_bytes(inhalt)
        befehl = [sys.executable, "-m", "app.worker", leser, str(pfad)] + ([dateiname] if dateiname else [])
        try:
            lauf = subprocess.run(befehl, capture_output=True, timeout=zeitlimit,
                                  cwd=str(Path(__file__).resolve().parent.parent))
        except subprocess.TimeoutExpired:
            return {"status": FEHLER, "meldung": f"Zeitüberschreitung nach {zeitlimit:g} s"}
    if lauf.returncode != 0:
        log.warning("Leser %s endete mit Code %s: %s", leser, lauf.returncode,
                    lauf.stderr.decode("utf-8", "replace")[-500:])
        return {"status": FEHLER, "meldung": "Leser abgebrochen"}
    if lauf.stderr:
        log.debug("Leser %s meldete: %s", leser, lauf.stderr.decode("utf-8", "replace")[-500:])
    try:
        return json.loads(lauf.stdout.decode("utf-8"))
    except ValueError:
        return {"status": FEHLER, "meldung": "Leser lieferte keine gültige Antwort"}


def bild_im_prozess(inhalt: bytes, seite: int, zeitlimit: float = ZEITLIMIT_S) -> bytes | None:
    """Seitenbild in eigenem Prozess (wie das Lesen); None, wenn die Seite fehlt oder das PDF kaputt ist."""
    with tempfile.TemporaryDirectory(prefix="bild-") as tmp:
        pfad = Path(tmp) / "eingang.pdf"
        pfad.write_bytes(inhalt)
        try:
            lauf = subprocess.run([sys.executable, "-m", "app.worker", "--bild", str(pfad), str(seite)],
                                  capture_output=True, timeout=zeitlimit,
                                  cwd=str(Path(__file__).resolve().parent.parent))
        except subprocess.TimeoutExpired:
            return None
    if lauf.returncode != 0 or not lauf.stdout.startswith(b"\x89PNG"):
        log.info("Seitenbild %s: %s", seite, lauf.stderr.decode("utf-8", "replace")[-300:])
        return None
    return lauf.stdout


class Handler(BaseHTTPRequestHandler):
    server_version = f"rezeptbuch-leser/{__version__}"

    def log_message(self, fmt, *args):  # Standardprotokoll von http.server stumm
        log.debug("%s – " + fmt, self.address_string(), *args)

    def _json(self, code: int, daten: dict) -> None:
        roh = json.dumps(daten, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def _fehler(self, code: int, meldung: str) -> None:
        self._json(code, {"format": "rezeptbuch-leser", "fehler": meldung})

    def do_GET(self):
        if self.path == "/v1/gesundheit":
            return self._json(200, gesundheit())
        self._fehler(404, "Unbekannter Pfad")

    def _pdf_lesen(self) -> bytes | None:
        try:
            laenge = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            laenge = 0
        if laenge <= 0:
            self._fehler(400, "Leerer Anfragekörper – PDF erwartet")
            return None
        if laenge > MAX_BYTES:
            self.close_connection = True
            self._fehler(413, f"PDF größer als {MAX_BYTES // (1024 * 1024)} MB")
            return None
        inhalt = self.rfile.read(laenge)
        if not inhalt.startswith(b"%PDF-"):
            self._fehler(400, "Kein PDF")
            return None
        return inhalt

    def _seitenbild(self, seite: int) -> None:
        inhalt = self._pdf_lesen()
        if inhalt is None:
            return
        png = bild_im_prozess(inhalt, seite) if 1 <= seite <= MAX_SEITEN else None
        if png is None:
            return self._fehler(404, f"Seite {seite} nicht vorhanden oder nicht darstellbar")
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(png)))
        self.end_headers()
        self.wfile.write(png)

    def do_POST(self):
        bild = PFAD_BILD.match(self.path)
        if bild:
            return self._seitenbild(int(bild.group(1)))
        treffer = PFAD_LESEN.match(self.path)
        if not treffer:
            return self._fehler(404, "Unbekannter Pfad")
        leser = treffer.group(1).replace("-", "_")
        if leser not in LESER:
            return self._fehler(404, f"Leser {treffer.group(1)!r} gibt es (noch) nicht")
        try:
            laenge = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            laenge = 0
        if laenge <= 0:
            return self._fehler(400, "Leerer Anfragekörper – PDF erwartet")
        if laenge > MAX_BYTES:
            self.close_connection = True
            return self._fehler(413, f"PDF größer als {MAX_BYTES // (1024 * 1024)} MB")
        inhalt = self.rfile.read(laenge)
        if not inhalt.startswith(b"%PDF-"):
            return self._fehler(400, "Kein PDF")
        name = _sauberer_name(self.headers.get("X-Dateiname"))
        start = time.monotonic()
        ergebnis = lese_im_prozess(leser, inhalt, name)
        sha = hashlib.sha256(inhalt).hexdigest()
        datei = {"name": name, "bytes": len(inhalt), "sha256": sha, "seiten": ergebnis.get("seiten")}
        daten = antwort(leser, datei, ergebnis)
        log.info("%s: %s in %.1f s (sha256 %s…)", leser, daten["status"], time.monotonic() - start, sha[:12])
        self._json(200, daten)


def _log_level() -> str:
    try:
        stufe = json.loads(OPTIONS_FILE.read_text(encoding="utf-8")).get("log_level", "info")
    except (OSError, ValueError):
        stufe = "info"
    return stufe if stufe in ("debug", "info", "warning", "error") else "info"


def main() -> int:
    tz = setup_timezone()
    stufe = _log_level()
    logging.basicConfig(level=stufe.upper(), format="%(asctime)s %(levelname)s %(message)s")
    log.info("HA-Rezeptbuch Leser %s startet (Port %d, Leser %s, Protokollstufe %s, Ortszeit %s)",
             __version__, PORT, ", ".join(f"{k} Schema {v}" for k, v in LESER.items()), stufe, tz)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
