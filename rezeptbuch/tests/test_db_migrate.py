"""Tests: Verbindung, Migrationen, Sicherungskopien (Modul 02)."""

import os
import shutil
import sqlite3
import time

import pytest

from app.db import (
    MIGRATIONS_DIR,
    DatabaseIntegrityError,
    MigrationError,
    connect,
    current_version,
    init_database,
    migrate,
    transaction,
)
from app.db.migrate import discover, prune_backups

EXPECTED_TABLES = {
    "station", "raw_material",
    "recipe_group", "recipe", "recipe_version", "recipe_version_step", "recipe_item", "recipe_batch_size",
    "recipe_piece_weight", "production_order", "order_piece", "order_item_override", "batch", "batch_item", "weighing_event",
    "setting", "change_log", "migration_log",
}


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


@pytest.fixture
def migrations_copy(tmp_path):
    """Kopie der echten Migrationen, um zusätzliche Test-Migrationen anzuhängen."""
    target = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, target)
    return target


def test_fresh_database_has_full_schema(conn):
    assert tables(conn) == EXPECTED_TABLES
    assert current_version(conn) == 3
    log = conn.execute("SELECT version, file_name, backup_file FROM migration_log ORDER BY version").fetchall()
    assert [tuple(r) for r in log] == [(1, "0001_initial.sql", None), (2, "0002_raw_material.sql", None),
                                       (3, "0003_recipe.sql", None)]


def test_connection_settings(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_stations_prepared(conn):
    rows = [tuple(r) for r in conn.execute("SELECT id, name, active FROM station ORDER BY id")]
    assert rows == [(1, "Waage 1", 1), (2, "Waage 2", 0)]


def test_restart_changes_nothing(db_path, tmp_path):
    init_database(db_path).close()
    conn = init_database(db_path)
    assert current_version(conn) == 3
    assert conn.execute("SELECT count(*) FROM migration_log").fetchone()[0] == 3
    assert not (tmp_path / "backups").exists()  # keine Sicherung ohne neue Migration
    conn.close()


def test_new_migration_creates_backup_first(db_path, tmp_path, migrations_copy):
    init_database(db_path, migrations_dir=migrations_copy).close()
    (migrations_copy / "0004_test_column.sql").write_text(
        "ALTER TABLE recipe_group ADD COLUMN color TEXT;", encoding="utf-8"
    )
    conn = init_database(db_path, migrations_dir=migrations_copy)
    assert current_version(conn) == 4

    backups = list((tmp_path / "backups").glob("pre_migration_0003_*.db"))
    assert len(backups) == 1
    old = sqlite3.connect(backups[0])
    assert old.execute("PRAGMA user_version").fetchone()[0] == 3
    old.close()

    backup_file = conn.execute("SELECT backup_file FROM migration_log WHERE version = 4").fetchone()[0]
    assert backup_file == str(backups[0])
    conn.close()


def test_failing_migration_is_rolled_back(db_path, tmp_path, migrations_copy):
    init_database(db_path, migrations_dir=migrations_copy).close()
    (migrations_copy / "0004_broken.sql").write_text(
        "CREATE TABLE half_done (id INTEGER PRIMARY KEY);\n"
        "INSERT INTO table_that_does_not_exist VALUES (1);",
        encoding="utf-8",
    )
    with pytest.raises(MigrationError, match="zurückgerollt"):
        init_database(db_path, migrations_dir=migrations_copy)

    conn = connect(db_path)
    assert current_version(conn) == 3
    assert "half_done" not in tables(conn)
    assert len(list((tmp_path / "backups").glob("pre_migration_*.db"))) == 1
    conn.close()


def test_database_newer_than_addon_is_refused(db_path):
    init_database(db_path).close()
    conn = connect(db_path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(MigrationError, match="Stand 99"):
        init_database(db_path)


def test_migration_files_must_be_numbered_without_gap(migrations_copy):
    (migrations_copy / "0005_gap.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="lückenlos"):
        discover(migrations_copy)


def test_migration_file_name_is_checked(migrations_copy):
    (migrations_copy / "zwei.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="Dateiname"):
        discover(migrations_copy)


def test_shipped_migrations_are_valid():
    migrations = discover()
    assert migrations[0].path.name == "0001_initial.sql"
    assert migrations[1].path.name == "0002_raw_material.sql"
    assert migrations[2].path.name == "0003_recipe.sql"


def test_prune_keeps_newest_five(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    now = time.time()
    for i in range(8):
        f = backup_dir / f"pre_migration_0001_{i}.db"
        f.write_bytes(b"")
        os.utime(f, (now + i, now + i))
    (backup_dir / "andere_datei.db").write_bytes(b"")  # fremde Dateien bleiben

    removed = prune_backups(backup_dir, keep=5)
    assert len(removed) == 3
    remaining = sorted(p.name for p in backup_dir.glob("pre_migration_*.db"))
    assert remaining == [f"pre_migration_0001_{i}.db" for i in range(3, 8)]
    assert (backup_dir / "andere_datei.db").exists()


def test_corrupt_file_is_refused(db_path):
    db_path.write_bytes(b"das ist keine datenbank" * 100)
    with pytest.raises(DatabaseIntegrityError):
        init_database(db_path)


def test_transaction_commits_and_rolls_back(conn):
    with transaction(conn):
        conn.execute("INSERT INTO setting (key, value) VALUES ('a', '1')")
    with pytest.raises(RuntimeError):
        with transaction(conn):
            conn.execute("INSERT INTO setting (key, value) VALUES ('b', '2')")
            raise RuntimeError("Abbruch")
    keys = [r[0] for r in conn.execute("SELECT key FROM setting ORDER BY key")]
    assert keys == ["a"]


def test_migrate_on_empty_dir_does_nothing(tmp_path):
    empty = tmp_path / "leer"
    empty.mkdir()
    conn = connect(tmp_path / "x.db")
    assert migrate(conn, migrations_dir=empty) == []
    conn.close()
