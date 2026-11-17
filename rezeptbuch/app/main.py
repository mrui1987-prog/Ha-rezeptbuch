"""Einstiegspunkt des Rezeptservers.

Stand 0.5.2: Statusseite, Health-Endpunkt, Datenbank (Modul 02), Rohstoffverwaltung
und PIN-Schutz (Modul 03), Rohstoff-CSV-Import (Modul 05, Teil C1), Rezeptpflege (Modul 05, Teil C2),
Vorlagen-Import und Export .xlsx (Modul 05, Teil C3). Beim Start wird die Datenbank geöffnet, geprüft und
migriert; danach öffnet jede Anfrage eine eigene Verbindung (``deps.get_db``).
"""

import logging
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__
from .auth.pin import ensure_default_pin
from .auth.router import router as auth_router
from .auth.sessions import AdminSessions
from .db import DatabaseError, default_db_path, init_database
from .errors import ServiceError
from .exports.router import router as exports_router
from .imports.router import router as imports_router
from .raw_materials.router import router as raw_materials_router
from .recipes.router import router as recipes_router
from .settings import admin_timeout_minutes, load_options
from .web.router import router as web_router

logger = logging.getLogger("rezeptbuch")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = None          # Verbindung nur für Start und Tests; Anfragen nutzen deps.get_db
    app.state.db_path = None
    app.state.db_error = None
    app.state.sessions = AdminSessions(timeout_minutes=admin_timeout_minutes(load_options()))
    try:
        app.state.db = init_database()
        app.state.db_path = default_db_path()
        ensure_default_pin(app.state.db)       # Probebetrieb mit PIN 1234, solange keine PIN gesetzt ist
    except (DatabaseError, sqlite3.DatabaseError) as exc:
        # Kein Produktionsbetrieb mit fehlerhafter Datenbank (docs/datenmodell.md, Abschnitt 8)
        logger.error("Datenbank nicht betriebsbereit: %s", exc)
        app.state.db_error = str(exc)
    yield
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
app.include_router(imports_router)
app.include_router(exports_router)      # vor recipes_router: /admin/recipes/export.xlsx ist keine Rezept-ID
app.include_router(recipes_router)
app.include_router(web_router)


@app.get("/api/v1/health")
def health():
    db_error = getattr(app.state, "db_error", None)
    if db_error:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "version": __version__, "detail": db_error},
        )
    return {"status": "ok", "version": __version__}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    # Relative Links, damit die Seite hinter HA-Ingress funktioniert
    return f"""<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>HA-Rezeptbuch</title>
<style>
  :root {{ color-scheme: light; }}
  html {{ background: #fafafa; }}
  body {{ font-family: sans-serif; padding: 2rem; margin: 0; background: #fafafa; color: #222;
         min-height: 100vh; -webkit-transform: translateZ(0); transform: translateZ(0); }}
  a.button {{ display: inline-block; padding: .8rem 1.4rem; background: #2563eb; color: #fff;
             text-decoration: none; border-radius: 6px; font-size: 1.1rem; }}
</style></head>
<body>
<h1>HA-Rezeptbuch</h1>
<p>Version {__version__} – im Aufbau.</p>
<p><a class="button" href="admin/login">Admin-Bereich (Rohstoffe, Rezepte)</a></p>
<script>
  // iOS-App (WKWebView/Ingress): erstes Zeichnen erzwingen, sonst bleibt die Seite bis zur Berührung leer
  function repaint() {{ document.body.style.display = 'none'; void document.body.offsetHeight; document.body.style.display = ''; }}
  window.addEventListener('load', function () {{ repaint(); requestAnimationFrame(repaint); setTimeout(repaint, 150); }});
  window.addEventListener('pageshow', repaint);
</script>
</body>
</html>"""
