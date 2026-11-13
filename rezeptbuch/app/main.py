"""Einstiegspunkt des Rezeptservers.

Stand 0.2.0: Statusseite, Health-Endpunkt und Datenbank (Modul 02).
Beim Start wird die Datenbank geöffnet, geprüft und migriert.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from . import __version__
from .db import DatabaseError, init_database

logger = logging.getLogger("rezeptbuch")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = None
    app.state.db_error = None
    try:
        app.state.db = init_database()
    except DatabaseError as exc:
        # Kein Produktionsbetrieb mit fehlerhafter Datenbank (docs/datenmodell.md, Abschnitt 8)
        logger.error("Datenbank nicht betriebsbereit: %s", exc)
        app.state.db_error = str(exc)
    yield
    if app.state.db is not None:
        app.state.db.close()


app = FastAPI(title="HA-Rezeptbuch", version=__version__, lifespan=lifespan)


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
<title>HA-Rezeptbuch</title></head>
<body style="font-family:sans-serif;padding:2rem">
<h1>HA-Rezeptbuch</h1>
<p>Version {__version__} – im Aufbau.</p>
</body>
</html>"""
