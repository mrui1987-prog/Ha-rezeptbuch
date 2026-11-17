"""Tests: Mustervorlage (Modul 05, C3-E2) – muss ohne Änderung fehlerfrei importierbar sein."""

import io

import pytest

pytest.importorskip("openpyxl")

from openpyxl import load_workbook  # noqa: E402

from app.exports.sample_template import build_sample  # noqa: E402
from app.imports.recipe_template import import_recipe_template  # noqa: E402
from app.recipes import service  # noqa: E402


def test_sheets_and_content():
    wb = load_workbook(io.BytesIO(build_sample()))
    assert wb.sheetnames == ["Anleitung", "Rezepte", "Rezeptzeilen", "Stückgewichte", "Chargengrößen",
                             "Rohstoffe", "Umrechnung"]
    names = [r[2] for r in wb["Rezepte"].iter_rows(min_row=2, values_only=True) if r[2]]
    assert "Schwarzwälder Kirschtorte (Muster)" in names


def test_sample_imports_cleanly(conn):
    data = build_sample()
    check = import_recipe_template(conn, data, mode="check", confirm_overwrite=False)
    assert not check.get("errors")
    import_recipe_template(conn, data, mode="run", confirm_overwrite=False)
    found = [r for r in service.list_recipes(conn, include_locked=True, include_archived=True)
             if r["name"] == "Schwarzwälder Kirschtorte (Muster)"]
    assert len(found) == 1
    rec = service.get_recipe(conn, found[0]["id"])
    assert len(rec["items"]) == 8 and len(rec["batch_sizes"]) == 2
