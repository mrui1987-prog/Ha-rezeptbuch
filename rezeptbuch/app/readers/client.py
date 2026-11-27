"""Ruft Add-on 3 `rezeptbuch_leser` auf (docs/kennzeichnungspass-import.md 15, K04-12/K04-14).

Adresse: Option ``reader_url`` oder aus dem eigenen Rechnernamen (``…-rezeptbuch`` → ``…-rezeptbuch-leser``),
Port 8100. Add-on 1 hängt nicht von Add-on 3 ab: ist der Leser nicht erreichbar, kommt eine Meldung (W8).
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request

from ..errors import ConflictError
from ..settings import load_options

PORT = 8100
TIMEOUT_S = 45


def reader_url() -> str:
    url = (load_options().get("reader_url") or os.environ.get("REZEPTBUCH_READER_URL") or "").strip()
    if url:
        return url.rstrip("/")
    host = socket.gethostname()
    return f"http://{host}-leser:{PORT}"


def _post(url: str, body: bytes, headers: dict) -> dict:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:  # noqa: S310 – internes Add-on-Netz
        return json.loads(res.read().decode("utf-8"))


def read(reader: str, pdf: bytes, file_name: str | None) -> dict:
    """PDF an den Leser; liefert die Antwort-Hülle (status, daten, meldung, …)."""
    headers = {"Content-Type": "application/pdf"}
    if file_name:
        headers["X-Dateiname"] = file_name.encode("ascii", "replace").decode("ascii")[:120]
    try:
        return _post(f"{reader_url()}/v1/lesen/{reader}", pdf, headers)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ConflictError("Leser nicht erreichbar – Add-on „HA-Rezeptbuch Leser“ starten.",
                            code="reader_unreachable", reason=str(exc)[:200]) from None


def page_image(pdf: bytes, page: int) -> bytes | None:
    """Seite als PNG vom Leser (ab Leser 0.2.0, Vorschaubild der Zuordnung); None, wenn der Leser die Seite
    nicht liefert (Seite fehlt, älterer Leser ohne Seitenbild)."""
    req = urllib.request.Request(f"{reader_url()}/v1/seitenbild?seite={int(page)}", data=pdf, method="POST",
                                 headers={"Content-Type": "application/pdf"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:  # noqa: S310 – internes Add-on-Netz
            body = res.read()
    except urllib.error.HTTPError:
        return None
    except (urllib.error.URLError, OSError) as exc:
        raise ConflictError("Leser nicht erreichbar – Add-on „HA-Rezeptbuch Leser“ starten.",
                            code="reader_unreachable", reason=str(exc)[:200]) from None
    return body if body.startswith(b"\x89PNG") else None
