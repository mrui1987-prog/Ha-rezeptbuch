"""Datenbankschicht des Rezeptservers (Modul 02).

Öffentliche Funktionen:

* ``init_database()`` – beim Start: öffnen, prüfen, migrieren, erneut prüfen
* ``connect()`` – Verbindung mit den verbindlichen Einstellungen
* ``transaction()`` – Kontextmanager für Transaktionen
* ``migrate()`` / ``backup_database()`` – Migrationen und Sicherungskopien

Tabellenspezifische Lese- und Schreibfunktionen entstehen in den Fachmodulen
(03 Rohstoffe, 05 Rezepte, 09 Wiegeablauf, 11 Chargen).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from .connection import connect, default_db_path, transaction
from .errors import DatabaseError, DatabaseIntegrityError, MigrationError
from .integrity import check_integrity
from .migrate import MIGRATIONS_DIR, backup_database, current_version, migrate

__all__ = [
    "DatabaseError",
    "DatabaseIntegrityError",
    "MIGRATIONS_DIR",
    "MigrationError",
    "backup_database",
    "check_integrity",
    "connect",
    "current_version",
    "default_db_path",
    "init_database",
    "migrate",
    "transaction",
]

logger = logging.getLogger(__name__)


def init_database(
    path: str | Path | None = None,
    backup_dir: str | Path | None = None,
    migrations_dir: str | Path = MIGRATIONS_DIR,
) -> sqlite3.Connection:
    """Öffnet die Datenbank beim Start des Add-ons und bringt sie auf den neuesten Stand.

    Ablauf: Verbindung öffnen → Integrität prüfen → Migrationen (mit Sicherung)
    → Integrität erneut prüfen. Bei einem Fehler wird eine ``DatabaseError``
    ausgelöst; die Datenbankdatei bleibt unverändert bzw. zurückgerollt.
    """
    db_path = Path(path) if path is not None else default_db_path()
    if backup_dir is None:
        backup_dir = db_path.parent / "backups"

    try:
        conn = connect(db_path)
    except sqlite3.DatabaseError as exc:
        raise DatabaseIntegrityError(f"Datenbank {db_path} kann nicht geöffnet werden: {exc}") from exc

    try:
        problems = check_integrity(conn)
        if problems:
            raise DatabaseIntegrityError("Integritätsprüfung fehlgeschlagen: " + "; ".join(problems))

        applied = migrate(conn, migrations_dir=migrations_dir, backup_dir=backup_dir)
        if applied:
            logger.info("Datenbank-Migrationen eingespielt: %s", ", ".join(f"{v:04d}" for v in applied))

        problems = check_integrity(conn)
        if problems:
            raise DatabaseIntegrityError("Integritätsprüfung nach Migration fehlgeschlagen: " + "; ".join(problems))
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise DatabaseIntegrityError(f"Datenbank {db_path} ist nicht lesbar: {exc}") from exc
    except Exception:
        conn.close()
        raise

    logger.info("Datenbank bereit: %s (Stand %d)", db_path, current_version(conn))
    return conn
