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
                             "Rohstoffe"]
    names = [r[2] for r in wb["Rezepte"].iter_rows(min_row=2, values_only=True) if r[2]]
    assert "Schwarzwälder Kirschtorte (Muster)" in names


def test_sample_imports_cleanly_with_samples(conn):
    data = build_sample()
    check = import_recipe_template(conn, data, mode="check", confirm_overwrite=False, include_samples=True)
    assert not check.get("errors")
    import_recipe_template(conn, data, mode="run", confirm_overwrite=False, include_samples=True)
    found = [r for r in service.list_recipes(conn, include_locked=True, include_archived=True)
             if r["name"] == "Schwarzwälder Kirschtorte (Muster)"]
    assert len(found) == 1
    rec = service.get_recipe(conn, found[0]["id"])
    assert len(rec["items"]) == 8 and len(rec["batch_sizes"]) == 2

    by_name = {i["raw_material"]["name"]: i for i in rec["items"] if i["type"] == "raw_material"}
    assert by_name["Muster Kirschwasser"]["amount_g"] == 38 and by_name["Muster Kirschwasser"]["needs_review"]
    biskuit = service.get_recipe(conn, [r for r in service.list_recipes(conn, include_locked=True)
                                        if r["name"] == "Schoko-Biskuit (Muster)"][0]["id"])
    assert biskuit["items"][0]["amount_g"] == 300 and biskuit["items"][0]["needs_review"]   # 6 Stück × 50 g


def test_sample_is_ignored_by_default(conn):
    report = import_recipe_template(conn, build_sample(), mode="check")
    assert report["ok"] and report["nothing_to_import"]
    assert report["counts"]["samples_recipes"] == 2 and report["counts"]["samples_raw_materials"] == 11


def test_conversion_columns_in_raw_material_sheet():
    wb = load_workbook(io.BytesIO(build_sample()))
    ws = wb["Rohstoffe"]
    header = [c.value for c in ws[1]]
    assert header[8].startswith("Umrechnung Einheit") and header[9].startswith("Gramm je Einheit")
    assert "Nur ausfüllen" in ws.cell(row=1, column=9).comment.text
    guide = " ".join(str(c.value or "") for c in wb["Anleitung"]["A"])
    assert "LibreOffice" in guide and "überspringt" in guide


def test_sample_names_list():
    from app.exports.sample_template import SAMPLE_RAW_NAMES, SAMPLE_RECIPE_NAMES
    assert set(SAMPLE_RECIPE_NAMES) == {"Schoko-Biskuit (Muster)", "Schwarzwälder Kirschtorte (Muster)"}
    assert len(SAMPLE_RAW_NAMES) == 11 and all(n.startswith("Muster ") for n in SAMPLE_RAW_NAMES)
