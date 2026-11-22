"""Liefert die Seiten des Admin-Bereichs: PIN-Eingabe und Rohstoffliste (``admin.html``),
Rezepte und Gruppen (``recipes.html``, Modul 05), Prüfseite „Berechnung“ (``calc.html``, Modul 06),
Prüfseite „Waagen“ (``scales.html``, Modul 08), Prüfseite „Ablauf“ (``production.html``, Modul 09), Planer (``planner.html``, Modul 10),
Startseite und Stationsoberfläche (``start.html``, ``station.html``, Modul 10), Scan-Seite (``scan.html``, Strichcode S1),
Planen (``plan.html``, Planer P-B, ohne PIN).

Die Admin-Seiten sind je eine in sich geschlossene HTML-Datei (Stil und Skript eingebettet).
Die Stationsoberfläche nutzt zusätzlich die gemeinsamen Dateien ``ui/common.css`` und
``ui/common.js`` (K10-2), eingebunden mit relativen Pfaden, damit sie hinter HA-Ingress
gefunden werden. Die Adresse der Schnittstelle bestimmt jede Seite selbst aus ihrer Adresse.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

PAGE = Path(__file__).parent / "static" / "admin.html"
RECIPES_PAGE = Path(__file__).parent / "static" / "recipes.html"
CALC_PAGE = Path(__file__).parent / "static" / "calc.html"
SCALES_PAGE = Path(__file__).parent / "static" / "scales.html"
PRODUCTION_PAGE = Path(__file__).parent / "static" / "production.html"
PLANNER_PAGE = Path(__file__).parent / "static" / "planner.html"
START_PAGE = Path(__file__).parent / "static" / "start.html"
STATION_PAGE = Path(__file__).parent / "static" / "station.html"
SCAN_PAGE = Path(__file__).parent / "static" / "scan.html"
PLAN_PAGE = Path(__file__).parent / "static" / "plan.html"
UI_DIR = Path(__file__).parent / "static" / "ui"
UI_FILES = {"common.css": "text/css; charset=utf-8", "common.js": "text/javascript; charset=utf-8"}
STATIONS = (1, 2)

router = APIRouter(include_in_schema=False)


@router.get("/admin", response_class=HTMLResponse)
@router.get("/admin/login", response_class=HTMLResponse)
@router.get("/admin/rohstoffe", response_class=HTMLResponse)
@router.get("/admin/rohstoffe/{rest}", response_class=HTMLResponse)
def admin_page(rest: str | None = None) -> HTMLResponse:
    """Rohstoffverwaltung (Modul 03, docs/rohstoffverwaltung.md): Liste, ``/admin/rohstoffe/<Nummer>`` bzw.
    ``/neu`` (Rohstoff als eigene Seite), ``/bestand``, ``/haendler`` – eine Seite, die Ansicht wählt das Skript."""
    return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/admin/rezepte", response_class=HTMLResponse)
def recipes_page() -> HTMLResponse:
    return HTMLResponse(RECIPES_PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/admin/berechnung", response_class=HTMLResponse)
def calc_page() -> HTMLResponse:
    return HTMLResponse(CALC_PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/admin/waagen", response_class=HTMLResponse)
def scales_page() -> HTMLResponse:
    return HTMLResponse(SCALES_PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/admin/ablauf", response_class=HTMLResponse)
def production_page() -> HTMLResponse:
    return HTMLResponse(PRODUCTION_PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/admin/planer", response_class=HTMLResponse)
@router.get("/admin/planer/{rest}", response_class=HTMLResponse)
def planner_page(rest: str | None = None) -> HTMLResponse:
    """Planer (Modul 10, docs/planer.md 12): Unterreiter „Planen“ und „Artikel“;
    Unterpfade (z. B. ``/admin/planer/artikel``) liefern dieselbe Seite."""
    return HTMLResponse(PLANNER_PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


def start_page() -> HTMLResponse:
    """Startseite: öffnet die gespeicherte Station oder fragt einmal danach (K10-3)."""
    return HTMLResponse(START_PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/station/{station}", response_class=HTMLResponse)
def station_page(station: int) -> HTMLResponse:
    if station not in STATIONS:
        return HTMLResponse("Diese Station gibt es nicht.", status_code=404)
    return HTMLResponse(STATION_PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/scannen", response_class=HTMLResponse)
def scan_page() -> HTMLResponse:
    """Scan-Seite (docs/strichcode.md, Teil S1); ersetzt die Prüfseite /kameratest."""
    return HTMLResponse(SCAN_PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/planer", response_class=HTMLResponse)
def plan_page() -> HTMLResponse:
    """Planen: Plan je Tag, „Jetzt planen“, Rohstoffe abbuchen (docs/planer.md 6–10, ohne PIN, K10-P5)."""
    return HTMLResponse(PLAN_PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


@router.get("/ui/{name}")
def ui_file(name: str) -> Response:
    media = UI_FILES.get(name)
    if media is None:
        return Response("Nicht gefunden.", status_code=404, media_type="text/plain; charset=utf-8")
    return Response((UI_DIR / name).read_text(encoding="utf-8"), media_type=media,
                    headers={"Cache-Control": "no-store"})
