"""Tests: Migration 0016 (verworfene Menge im Wiegeprotokoll, M09-20) – Protokoll bleibt erhalten."""

import shutil
import sqlite3

import pytest

from app.db import MIGRATIONS_DIR, init_database


def test_discarded_event_allowed_and_rules_kept(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(weighing_event)")]
    assert "note" in cols
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'weighing_event'").fetchone()[0]
    assert "'discarded'" in sql
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' "
                                        "AND tbl_name = 'weighing_event'")}
    assert names == {"trg_weighing_event_closed_insert", "trg_weighing_event_no_update",
                     "trg_weighing_event_no_delete"}


def test_upgrade_from_0015(tmp_path):
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 15:
            shutil.copy(path, old_dir / path.name)
    db = tmp_path / "r.db"
    conn = init_database(db, backup_dir=tmp_path / "b", migrations_dir=old_dir)
    conn.close()
    conn = init_database(db, backup_dir=tmp_path / "b")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("SELECT max(version) FROM migration_log").fetchone()[0] == 16
