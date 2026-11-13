"""Prüfungen beim Start (docs/datenmodell.md, Abschnitt 5, Punkt 7)."""

from __future__ import annotations

import sqlite3


def check_integrity(conn: sqlite3.Connection) -> list[str]:
    """Prüft Datei und Fremdschlüssel. Gibt eine Liste gefundener Probleme zurück (leer = in Ordnung)."""
    problems: list[str] = []

    rows = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall()]
    if rows != ["ok"]:
        problems.extend(f"Datei beschädigt: {row}" for row in rows)

    for table, rowid, parent, _fk_index in conn.execute("PRAGMA foreign_key_check").fetchall():
        problems.append(f"Verweis ungültig: Tabelle {table}, Zeile {rowid} → {parent}")

    return problems
