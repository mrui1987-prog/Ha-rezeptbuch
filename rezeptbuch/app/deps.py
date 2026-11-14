"""Abhängigkeiten für die Schnittstellen (FastAPI ``Depends``).

``get_db`` öffnet je Anfrage eine **eigene** Datenbankverbindung und schließt sie
am Ende (K03-1, Befund B6 aus Modul 02). Dadurch stören sich gleichzeitige
Speichervorgänge nicht; SQLite (WAL-Modus, 5 s Wartezeit) regelt die Reihenfolge.
"""

from __future__ import annotations

from fastapi import Request

from .db import connect
from .errors import DatabaseNotReadyError


def get_db(request: Request):
    state = request.app.state
    db_path = getattr(state, "db_path", None)
    if getattr(state, "db_error", None) or db_path is None:
        raise DatabaseNotReadyError(
            "Die Datenbank ist nicht betriebsbereit. Bitte das Protokoll des Add-ons prüfen "
            "und gegebenenfalls eine Sicherung wiederherstellen.",
            code="database_not_ready",
        )
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()
