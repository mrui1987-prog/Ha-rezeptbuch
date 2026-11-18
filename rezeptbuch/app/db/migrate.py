"""Migrationen der Datenbank (docs/datenmodell.md, Abschnitt 6).

* Jede Schemaänderung ist eine nummerierte SQL-Datei in ``migrations/``:
  ``0001_initial.sql``, ``0002_….sql`` usw. Ausgelieferte Dateien werden nie
  geändert, Änderungen kommen immer als neue Datei dazu.
* Der Stand steht in ``PRAGMA user_version`` und in der Tabelle ``migration_log``.
* Vor dem Einspielen neuer Migrationen in eine bestehende Datenbank wird eine
  Sicherungskopie angelegt. Jede Migration läuft in einer eigenen Transaktion;
  bei einem Fehler wird sie vollständig zurückgerollt.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import MigrationError

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Anzahl aufbewahrter Sicherungen vor Migrationen (bis Modul 13 Genaueres festlegt)
BACKUP_KEEP = 5
BACKUP_PREFIX = "pre_migration_"

# Erste Zeile einer Migration, die mit ausgeschalteten Fremdschlüsseln laufen muss
FK_OFF_MARKER = "-- migration: foreign_keys=off"

_FILE_PATTERN = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    path: Path


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def discover(migrations_dir: str | Path = MIGRATIONS_DIR) -> list[Migration]:
    """Liest alle Migrationsdateien und prüft die Nummerierung (1, 2, 3 … ohne Lücke)."""
    migrations_dir = Path(migrations_dir)
    migrations: list[Migration] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        match = _FILE_PATTERN.match(path.name)
        if not match:
            raise MigrationError(
                f"Ungültiger Dateiname für eine Migration: {path.name} "
                "(erwartet z. B. 0002_neue_spalte.sql)"
            )
        migrations.append(Migration(int(match.group(1)), path))

    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise MigrationError(
                f"Migrationen sind nicht lückenlos nummeriert: erwartet {expected:04d}, "
                f"gefunden {migration.path.name}"
            )
    return migrations


def current_version(conn: sqlite3.Connection) -> int:
    """Aktueller Schemastand der Datenbank (0 = leer)."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def backup_database(conn: sqlite3.Connection, backup_dir: str | Path, label: str) -> Path:
    """Konsistente Sicherungskopie über die SQLite-Backup-Funktion.

    Funktioniert auch, während die Datenbank geöffnet ist.
    """
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now().strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{label}_{stamp}.db"
    counter = 1
    while target.exists():
        target = backup_dir / f"{label}_{stamp}_{counter}.db"
        counter += 1

    dest = sqlite3.connect(str(target))
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return target


def prune_backups(backup_dir: str | Path, keep: int = BACKUP_KEEP, prefix: str = BACKUP_PREFIX) -> list[Path]:
    """Löscht ältere Sicherungen vor Migrationen, behält die neuesten ``keep``."""
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []
    backups = sorted(
        (p for p in backup_dir.glob(f"{prefix}*.db") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = []
    for old in backups[keep:]:
        old.unlink()
        removed.append(old)
    return removed


def migrate(
    conn: sqlite3.Connection,
    migrations_dir: str | Path = MIGRATIONS_DIR,
    backup_dir: str | Path | None = None,
) -> list[int]:
    """Bringt die Datenbank auf den neuesten Stand.

    Gibt die Nummern der eingespielten Migrationen zurück (leer, wenn nichts zu tun war).
    """
    migrations = discover(migrations_dir)
    latest = migrations[-1].version if migrations else 0
    version = current_version(conn)

    if version > latest:
        raise MigrationError(
            f"Die Datenbank hat Stand {version}, dieses Add-on kennt nur bis Stand {latest}. "
            "Bitte das Add-on aktualisieren oder eine passende Sicherung wiederherstellen."
        )

    pending = [m for m in migrations if m.version > version]
    if not pending:
        return []

    backup_file: Path | None = None
    if version > 0 and backup_dir is not None:
        backup_file = backup_database(conn, backup_dir, f"{BACKUP_PREFIX}{version:04d}")
        prune_backups(backup_dir)

    applied: list[int] = []
    for migration in pending:
        sql = migration.path.read_text(encoding="utf-8")
        # Tabellen-Neuaufbau (z. B. geänderte CHECK-Regel, Migration 0006) braucht ausgeschaltete
        # Fremdschlüssel; das geht in SQLite nur außerhalb einer Transaktion. Die Prüfung mit
        # PRAGMA foreign_key_check unten läuft trotzdem vor dem COMMIT.
        fk_off = sql.lstrip().lower().startswith(FK_OFF_MARKER)
        fk_was_on = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
        if fk_off:
            conn.execute("PRAGMA foreign_keys = OFF")
        try:
            # Das Skript läuft innerhalb einer Transaktion; Fehler lassen sie offen
            # und werden unten zurückgerollt.
            conn.executescript("BEGIN IMMEDIATE;\n" + sql)
            conn.execute(f"PRAGMA user_version = {migration.version}")
            conn.execute(
                "INSERT INTO migration_log (version, file_name, applied_at, backup_file) "
                "VALUES (?, ?, ?, ?)",
                (
                    migration.version,
                    migration.path.name,
                    _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    str(backup_file) if backup_file else None,
                ),
            )
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise MigrationError(f"{len(violations)} Fremdschlüssel-Verletzung(en) nach der Migration")
            conn.execute("COMMIT")
        except Exception as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            hint = f" Sicherung: {backup_file}." if backup_file else ""
            raise MigrationError(
                f"Migration {migration.path.name} ist fehlgeschlagen und wurde zurückgerollt "
                f"(Datenbank bleibt auf Stand {current_version(conn)}): {exc}.{hint}"
            ) from exc
        finally:
            if fk_off and fk_was_on:
                conn.execute("PRAGMA foreign_keys = ON")
        applied.append(migration.version)

    return applied
