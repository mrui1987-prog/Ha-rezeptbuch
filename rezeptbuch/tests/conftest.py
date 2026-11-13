"""Gemeinsame Hilfen für die Datenbanktests."""

import sqlite3

import pytest

from app.db import init_database


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "rezeptbuch.db"


@pytest.fixture
def conn(db_path):
    connection = init_database(db_path)
    yield connection
    connection.close()


# ---------------------------------------------------------------------------
# Kleine Helfer zum Anlegen von Testdaten (nur für Tests, keine Fachlogik)
# ---------------------------------------------------------------------------

def add_raw_material(conn, number, name="Weizenmehl 550", type_="standard",
                     tolerance_unit="g", tolerance_value=20, unit_size_g=None, unit_label=None):
    cur = conn.execute(
        "INSERT INTO raw_material (number, name, type, tolerance_unit, tolerance_value, unit_size_g, unit_label) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (number, name, type_, tolerance_unit, tolerance_value, unit_size_g, unit_label),
    )
    return cur.lastrowid


def add_recipe(conn, number, name="Weizenbrot", locked=0):
    """Legt Rezept mit Version 1 an und setzt sie als aktuelle Version."""
    recipe_id = conn.execute("INSERT INTO recipe (number, locked) VALUES (?, ?)", (number, locked)).lastrowid
    version_id = add_version(conn, recipe_id, 1, name)
    conn.execute("UPDATE recipe SET current_version_id = ? WHERE id = ?", (version_id, recipe_id))
    return recipe_id, version_id


def add_version(conn, recipe_id, version_no, name="Weizenbrot"):
    return conn.execute(
        "INSERT INTO recipe_version (recipe_id, version_no, name) VALUES (?, ?, ?)",
        (recipe_id, version_no, name),
    ).lastrowid


def add_item(conn, version_id, position, raw_material_id=None, amount_g=1000, sub_recipe_id=None):
    item_type = "sub_recipe" if sub_recipe_id else "raw_material"
    return conn.execute(
        "INSERT INTO recipe_item (recipe_version_id, position, item_type, raw_material_id, sub_recipe_id, amount_g) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (version_id, position, item_type, raw_material_id, sub_recipe_id, amount_g),
    ).lastrowid


def add_order(conn, recipe_id, version_id=None, basis_type="total", basis_value=10000, **extra):
    columns = ["recipe_id", "recipe_version_id", "basis_type", "basis_value", *extra.keys()]
    values = [recipe_id, version_id, basis_type, basis_value, *extra.values()]
    placeholders = ", ".join("?" for _ in values)
    return conn.execute(
        f"INSERT INTO production_order ({', '.join(columns)}) VALUES ({placeholders})", values
    ).lastrowid


def raises_db_error(match=None):
    return pytest.raises(sqlite3.DatabaseError, match=match)
