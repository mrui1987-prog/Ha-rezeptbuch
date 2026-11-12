"""Einstiegspunkt des Rezeptservers.

Stand 0.1.0: nur Statusseite und Health-Endpunkt. Die Fachlogik folgt ab Modul 02.
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from . import __version__

app = FastAPI(title="HA-Rezeptbuch", version=__version__)


@app.get("/api/v1/health")
def health() -> dict:
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
