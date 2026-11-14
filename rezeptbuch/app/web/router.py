"""Liefert die Seite des Admin-Bereichs (PIN-Eingabe und Rohstoffliste).

Es ist eine einzige, in sich geschlossene HTML-Datei (Stil und Skript eingebettet).
Dadurch gibt es keine weiteren Adressen für Dateien, die hinter HA-Ingress wechseln
könnten. Die Adresse der Schnittstelle bestimmt die Seite selbst aus ihrer Adresse.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

PAGE = Path(__file__).parent / "static" / "admin.html"

router = APIRouter(include_in_schema=False)


@router.get("/admin", response_class=HTMLResponse)
@router.get("/admin/login", response_class=HTMLResponse)
@router.get("/admin/rohstoffe", response_class=HTMLResponse)
def admin_page() -> HTMLResponse:
    return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})
