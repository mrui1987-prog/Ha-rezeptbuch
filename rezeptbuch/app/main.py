"""Einstiegspunkt des Rezeptservers.

Stand 0.10.22: Statusseite, Health-Endpunkt, Datenbank (Modul 02), Rohstoffverwaltung
und PIN-Schutz (Modul 03), Rohstoff-CSV-Import (Modul 05, Teil C1), Rezeptpflege (Modul 05, Teil C2),
Vorlagen-Import und Export .xlsx (Modul 05, Teil C3), Rezeptberechnung (Modul 06),
Waagen-Anbindung per MQTT mit Live-Kanal (Modul 08), Wiegeablauf (Modul 09, Teile C1 und C2), Stationsoberfläche (Modul 10, Teil C1),
Händler und Bezugsquellen mit Preis je Bezugsquelle (Modul 04, Teil C1), Verkaufsartikel und Stückliste (Modul 10, Planer Teil P-A). Beim Start wird die Datenbank geöffnet, geprüft und
migriert; danach öffnet jede Anfrage eine eigene Verbindung (``deps.get_db``).
"""

import logging
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__
from .auth.pin import ensure_default_pin
from .articles.router import router as articles_router
from .auth.router import router as auth_router
from .auth.sessions import AdminSessions
from .calculation.router import router as calculation_router
from .dealers.router import router as dealers_router
from .display.router import router as display_router
from .db import DatabaseError, default_db_path, init_database
from .errors import ServiceError
from .logsetup import setup_logging, setup_timezone
from .production.batches import pause_running
from .production.router import router as production_router
from .production.runner import ProductionRunner
from .exports.router import router as exports_router
from .imports.router import router as imports_router
from .raw_materials.router import router as raw_materials_router
from .recipes.router import router as recipes_router
from .scales.router import router as scales_router
from .scales.service import ScaleService
from .settings import admin_timeout_minutes, load_options
from .web.router import router as web_router, start_page

logger = logging.getLogger("rezeptbuch")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Protokoll: Ortszeit und Stufe aus der Add-on-Option log_level (Befund B1, 0.8.1)
    tz = setup_timezone()
    level = setup_logging(load_options())
    logger.info("HA-Rezeptbuch %s startet (Protokollstufe %s, Ortszeit %s)", __version__, level, tz)
    app.state.db = None          # Verbindung nur für Start und Tests; Anfragen nutzen deps.get_db
    app.state.db_path = None
    app.state.db_error = None
    app.state.sessions = AdminSessions(timeout_minutes=admin_timeout_minutes(load_options()))
    try:
        app.state.db = init_database()
        app.state.db_path = default_db_path()
        ensure_default_pin(app.state.db)       # Probebetrieb mit PIN 1234, solange keine PIN gesetzt ist
        # Neustart mitten im Wiegen: laufende Teige werden pausiert (M09-11, Grund „Neustart“)
        paused = pause_running(app.state.db)
        if paused:
            logger.warning("%d laufende(r) Teig(e) nach dem Neustart pausiert", paused)
    except (DatabaseError, sqlite3.DatabaseError) as exc:
        # Kein Produktionsbetrieb mit fehlerhafter Datenbank (docs/datenmodell.md, Abschnitt 8)
        logger.error("Datenbank nicht betriebsbereit: %s", exc)
        app.state.db_error = str(exc)
    # Waagen-Anbindung (Modul 08): läuft auch ohne MQTT oder ohne Datenbank weiter (M08-10)
    app.state.scales = ScaleService(db_path=app.state.db_path)
    await app.state.scales.start()
    # Wiegeablauf (Modul 09): Waage über den Mittelsmann, Hintergrund für Auto-Quittung & Co. (Teil C2)
    app.state.production = ProductionRunner(app.state.scales.hub)
    await app.state.production.start(app.state.db_path)
    yield
    await app.state.production.stop()
    await app.state.scales.stop()
    if app.state.db is not None:
        app.state.db.close()


app = FastAPI(title="HA-Rezeptbuch", version=__version__, lifespan=lifespan)


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError):
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


@app.exception_handler(sqlite3.OperationalError)
async def database_busy_handler(request: Request, exc: sqlite3.OperationalError):
    text = str(exc).lower()
    if "locked" in text or "busy" in text:
        return JSONResponse(status_code=503, content={
            "detail": "Die Datenbank ist gerade beschäftigt. Bitte noch einmal versuchen.",
            "code": "database_busy"})
    logger.exception("Datenbankfehler bei %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Interner Datenbankfehler.", "code": "database_error"})


app.include_router(auth_router)
app.include_router(raw_materials_router)
app.include_router(dealers_router)
app.include_router(articles_router)
app.include_router(imports_router)
app.include_router(exports_router)      # vor recipes_router: /admin/recipes/export.xlsx ist keine Rezept-ID
app.include_router(recipes_router)
app.include_router(calculation_router)
app.include_router(scales_router)
app.include_router(production_router)
app.include_router(display_router)
app.include_router(web_router)


@app.get("/api/v1/health")
def health():
    db_error = getattr(app.state, "db_error", None)
    # MQTT-Stand nur zur Information: ohne MQTT bleibt der Status 200 (M08-10, K08-7)
    scales = getattr(app.state, "scales", None)
    mqtt = scales.hub.mqtt_state if scales is not None else "unavailable"
    if db_error:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "version": __version__, "detail": db_error, "mqtt": mqtt},
        )
    return {"status": "ok", "version": __version__, "mqtt": mqtt}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    # Startseite (Modul 10, K10-3): öffnet die gespeicherte Station oder fragt einmal danach
    return start_page()
