"""Datenbankverbindung des Rezeptservers.

Jede Verbindung wird mit denselben Einstellungen geöffnet (docs/datenmodell.md,
Abschnitt 2): Fremdschlüsselprüfung an, WAL-Modus, 5 s Wartezeit bei Sperren.
Die Datenbank wird ausschließlich über den Rezeptserver benutzt.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# Standardpfad im persistenten Add-on-Verzeichnis (wird vom HA-Backup erfasst).
# Für Tests und Entwicklung über die Umgebungsvariable REZEPTBUCH_DB änderbar.
DEFAULT_DB_PATH = Path("/data/rezeptbuch.db")

BUSY_TIMEOUT_MS = 5000


def default_db_path() -> Path:
    """Pfad der Datenbankdatei (Umgebungsvariable REZEPTBUCH_DB oder /data)."""
    return Path(os.environ.get("REZEPTBUCH_DB", str(DEFAULT_DB_PATH)))


def connect(path: str | Path) -> sqlite3.Connection:
    """Öffnet die Datenbank mit den verbindlichen Einstellungen.

    Die Verbindung arbeitet im Autocommit-Modus. Transaktionen werden
    ausdrücklich mit BEGIN/COMMIT gesteuert (siehe ``transaction``).
    """
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(path),
        timeout=BUSY_TIMEOUT_MS / 1000,
        isolation_level=None,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    if str(path) != ":memory:":
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            conn.close()
            raise sqlite3.OperationalError(f"WAL-Modus konnte nicht aktiviert werden (Modus: {mode})")
    return conn


class transaction:
    """Kontextmanager für eine Transaktion: COMMIT bei Erfolg, sonst ROLLBACK.

    Beispiel::

        with transaction(conn):
            conn.execute("INSERT ...")
    """

    def __init__(self, conn: sqlite3.Connection, immediate: bool = True):
        self.conn = conn
        self.immediate = immediate

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE" if self.immediate else "BEGIN")
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.conn.execute("COMMIT")
        elif self.conn.in_transaction:
            self.conn.execute("ROLLBACK")
        return False
