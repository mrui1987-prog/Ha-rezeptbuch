"""Tests: Sammelaktionen in der Rezeptliste (Modul 05, Ergänzung C3-E1)."""

import io

import pytest

from app.errors import ConflictError, ValidationError
from app.raw_materials import create_raw_material
from app.recipes import create_recipe, get_recipe, list_recipes
from app.recipes.bulk import bulk_action
from conftest import add_order


@pytest.fixture
def rm(conn):
    return {
        "mehl": create_raw_material(conn, {"name": "Weizenmehl 550", "type": "flour", "tolerance": 20})["id"],
        "salz": create_raw_material(conn, {"name": "Salz", "tolerance": "0", "tolerance_unit": "percent"})["id"],
    }


def make(conn, name, items=()):
    return create_recipe(conn, {"name": name, "items": list(items)})["id"]


def line(rid, amount=1000):
    return {"type": "raw_material", "raw_material_id": rid, "amount_g": amount}


def sub(rid, amount=500):
    return {"type": "sub_recipe", "sub_recipe_id": rid, "amount_g": amount}


def status(conn, rid):
    r = get_recipe(conn, rid)
    return r["locked"], r["archived"]


def test_check_changes_nothing(conn, rm):
    a = make(conn, "A", [line(rm["mehl"])])
    result = bulk_action(conn, "unlock", [a], mode="check")
    assert [e["id"] for e in result["done"]] == [a] and not result["executed"]
    assert status(conn, a) == (True, False)


def test_unlock_many_with_warnings_and_skips(conn, rm):
    a = make(conn, "A", [line(rm["mehl"])])
    b = make(conn, "B", [line(rm["salz"], 20)])          # Toleranz 0 % → Warnung
    empty = make(conn, "Leer")
    result = bulk_action(conn, "unlock", [a, b, empty], mode="run", confirm=True)
    assert result["executed"]
    assert [e["name"] for e in result["done"]] == ["A", "B"]
    assert result["skipped"][0]["name"] == "Leer" and "ohne Zeilen" in result["skipped"][0]["reason"]
    assert [(w["name"], w["zero_percent_count"]) for w in result["warnings"]] == [("B", 1)]
    assert status(conn, a)[0] is False and status(conn, b)[0] is False and status(conn, empty)[0] is True
    assert result["summary"] == "2 Rezepte freigeschaltet, 1 übersprungen."


def test_run_without_confirm_changes_nothing(conn, rm):
    a = make(conn, "A", [line(rm["mehl"])])
    with pytest.raises(ConflictError) as exc:
        bulk_action(conn, "unlock", [a], mode="run")
    assert exc.value.code == "confirmation_required"
    assert status(conn, a)[0] is True


def test_lock_unchanged_and_done(conn, rm):
    a = make(conn, "A", [line(rm["mehl"])])
    b = make(conn, "B", [line(rm["mehl"])])
    bulk_action(conn, "unlock", [a], mode="run", confirm=True)
    result = bulk_action(conn, "lock", [a, b], mode="run", confirm=True)
    assert [e["id"] for e in result["done"]] == [a]
    assert [e["id"] for e in result["unchanged"]] == [b]


def test_archive_parent_and_sub_together(conn, rm):
    vorteig = make(conn, "Vorteig", [line(rm["mehl"])])
    brot = make(conn, "Brot", [sub(vorteig)])
    alone = bulk_action(conn, "archive", [vorteig], mode="check")
    assert alone["done"] == [] and "Unterrezept" in alone["skipped"][0]["reason"]
    result = bulk_action(conn, "archive", [vorteig, brot], mode="run", confirm=True)
    assert {e["name"] for e in result["done"]} == {"Vorteig", "Brot"} and result["skipped"] == []
    assert status(conn, vorteig)[1] and status(conn, brot)[1]


def test_archive_already_archived_skipped(conn, rm):
    a = make(conn, "A", [line(rm["mehl"])])
    bulk_action(conn, "archive", [a], mode="run", confirm=True)
    result = bulk_action(conn, "archive", [a], mode="check")
    assert "bereits archiviert" in result["skipped"][0]["reason"]


def test_delete_used_skipped_unused_deleted(conn, rm):
    used = make(conn, "Benutzt", [line(rm["mehl"])])
    add_order(conn, used)
    free = make(conn, "Frei", [line(rm["mehl"])])
    result = bulk_action(conn, "delete", [used, free], mode="run", confirm=True)
    assert [e["name"] for e in result["done"]] == ["Frei"]
    assert "archivieren" in result["skipped"][0]["reason"]
    assert [r["name"] for r in list_recipes(conn, include_locked=True)] == ["Benutzt"]


def test_delete_parent_and_sub_together(conn, rm):
    vorteig = make(conn, "Vorteig", [line(rm["mehl"])])
    brot = make(conn, "Brot", [sub(vorteig)])
    result = bulk_action(conn, "delete", [vorteig, brot], mode="run", confirm=True)
    assert len(result["done"]) == 2 and list_recipes(conn, include_locked=True, include_archived=True) == []


def test_unknown_id_skipped(conn, rm):
    a = make(conn, "A", [line(rm["mehl"])])
    result = bulk_action(conn, "lock", [a, 999], mode="check")
    assert result["skipped"] == [{"id": 999, "number": None, "name": None, "reason": "Rezept nicht gefunden."}]


@pytest.mark.parametrize("ids", [[], None, ["1"], [0], [True], list(range(1, 1002))])
def test_bad_ids(conn, ids):
    with pytest.raises(ValidationError):
        bulk_action(conn, "lock", ids)


def test_bad_action_and_mode(conn, rm):
    a = make(conn, "A", [line(rm["mehl"])])
    with pytest.raises(ValidationError):
        bulk_action(conn, "copy", [a])
    with pytest.raises(ValidationError):
        bulk_action(conn, "lock", [a], mode="los")


def test_change_log_entries(conn, rm):
    a = make(conn, "A", [line(rm["mehl"])])
    b = make(conn, "B", [line(rm["mehl"])])
    bulk_action(conn, "unlock", [a, b], mode="run", confirm=True)
    n = conn.execute("SELECT count(*) FROM change_log WHERE entity = 'recipe' AND action = 'update' "
                     "AND new_values LIKE '%locked%'").fetchone()[0]
    assert n == 2


def test_export_selection_with_sub_recipe(conn, rm):
    pytest.importorskip("openpyxl")
    from openpyxl import load_workbook

    from app.exports import build_workbook
    vorteig = make(conn, "Vorteig", [line(rm["mehl"])])
    brot = make(conn, "Brot", [sub(vorteig)])
    make(conn, "Anderes", [line(rm["mehl"])])
    wb = load_workbook(io.BytesIO(build_workbook(conn, ids=[brot])))
    names = [r[2] for r in wb["Rezepte"].iter_rows(min_row=2, values_only=True)]
    assert names == ["Vorteig", "Brot"]


# -- Wiederherstellen (C3-E8, 0.5.8) ---------------------------------------------------------

def test_restore_many(conn, rm):
    a = make(conn, "A", [line(rm["mehl"])])
    b = make(conn, "B", [line(rm["mehl"])])
    active = make(conn, "C", [line(rm["mehl"])])
    bulk_action(conn, "archive", [a, b], mode="run", confirm=True)
    preview = bulk_action(conn, "restore", [a, b, active], mode="check")
    assert [e["id"] for e in preview["done"]] == [a, b] and [e["id"] for e in preview["unchanged"]] == [active]
    assert status(conn, a) == (True, True)                       # Vorschau ändert nichts
    result = bulk_action(conn, "restore", [a, b, active], mode="run", confirm=True)
    assert result["executed"] and result["summary"].startswith("2 Rezepte wiederhergestellt")
    assert status(conn, a) == (True, False) and status(conn, b) == (True, False)


def test_restore_skips_name_conflict(conn, rm):
    old = make(conn, "Brot", [line(rm["mehl"])])
    bulk_action(conn, "archive", [old], mode="run", confirm=True)
    make(conn, "Brot", [line(rm["mehl"])])                         # neues aktives Rezept mit gleichem Namen
    other = make(conn, "Zopf", [line(rm["mehl"])])
    bulk_action(conn, "archive", [other], mode="run", confirm=True)
    result = bulk_action(conn, "restore", [old, other], mode="run", confirm=True)
    assert [e["id"] for e in result["done"]] == [other]
    assert result["skipped"][0]["id"] == old and "denselben Namen" in result["skipped"][0]["reason"]
    assert status(conn, old) == (True, True)


def test_restore_two_archived_with_same_name(conn, rm):
    a = make(conn, "Brot", [line(rm["mehl"])])
    bulk_action(conn, "archive", [a], mode="run", confirm=True)
    b = make(conn, "Brot", [line(rm["mehl"])])
    bulk_action(conn, "archive", [b], mode="run", confirm=True)
    result = bulk_action(conn, "restore", [a, b], mode="run", confirm=True)
    assert len(result["done"]) == 1 and len(result["skipped"]) == 1


def test_restore_keeps_lock_state_and_logs(conn, rm):
    a = make(conn, "A", [line(rm["mehl"])])
    bulk_action(conn, "unlock", [a], mode="run", confirm=True)
    bulk_action(conn, "archive", [a], mode="run", confirm=True)
    bulk_action(conn, "restore", [a], mode="run", confirm=True)
    assert status(conn, a) == (False, False)                       # Status bleibt (R05-23)
    actions = [r[0] for r in conn.execute(
        "SELECT action FROM change_log WHERE entity = 'recipe' AND entity_id = ? ORDER BY id", (a,))]
    assert actions[-1] == "restore"
