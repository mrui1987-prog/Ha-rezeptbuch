"""Tests: Alte Version wiederherstellen (Wunsch Michael 18.11.2026, 13:32/13:36; Entscheidungen 15:36; 0.6.3)."""

import pytest

from app.errors import ConflictError, NotFoundError, ValidationError
from app.raw_materials import archive_raw_material, create_raw_material
from app.recipes import archive_recipe, create_recipe, get_recipe, get_version, restore_version, save_recipe

from conftest import add_order
from test_recipe_service import as_payload, line, sub


@pytest.fixture
def rm(conn):
    def make(name, **kw):
        return create_raw_material(conn, {"name": name, "tolerance": 20, **kw})["id"]
    return {"mehl": make("Weizenmehl 550", type="flour"), "wasser": make("Wasser"), "salz": make("Salz")}


@pytest.fixture
def recipe(conn, rm):
    """Weizenbrot Version 1: Mehl 1 000, Wasser 600 (Schritt „Teig“, Knetzeit 5+6)."""
    return create_recipe(conn, {"name": "Weizenbrot", "steps": ["Teig"], "knead_slow_min": 5, "knead_fast_min": 6,
                                "items": [line(rm["mehl"], 1000, step_no=1), line(rm["wasser"], 600, step_no=1)]})


def new_version(conn, recipe, **changes):
    r = save_recipe(conn, recipe["id"], as_payload(recipe, **changes), revision=recipe["revision"], version_mode="new")
    assert r["save_result"]["result"] == "new_version"
    return r


def test_restore_creates_new_version_and_keeps_old(conn, recipe, rm):
    v2 = new_version(conn, recipe, name="Weizenbrot neu", knead_slow_min=7,
                     items=[line(rm["mehl"], 1100, step_no=1), line(rm["salz"], 20, step_no=1)])
    assert v2["version_no"] == 2
    old_before = get_version(conn, recipe["id"], 1)
    r = restore_version(conn, recipe["id"], 1, revision=v2["revision"])
    assert r["save_result"]["result"] == "new_version"
    assert "Version 1 als neue Version 3" in r["save_result"]["message"]
    assert r["version_no"] == 3 and r["name"] == "Weizenbrot" and r["knead_slow_min"] == 5
    assert [(i["raw_material"]["name"], i["amount_g"]) for i in r["items"]] == [("Weizenmehl 550", 1000), ("Wasser", 600)]
    assert [s["name"] for s in r["steps"]] == ["Teig"]
    assert r["revision"] == v2["revision"] + 1
    old_after = get_version(conn, recipe["id"], 1)
    strip = lambda items: [{k: v for k, v in i.items() if k != "current"} for i in items]  # noqa: E731
    assert strip(old_after["items"]) == strip(old_before["items"])       # alte Version unverändert
    log = conn.execute("SELECT new_values FROM change_log WHERE action = 'new_version' ORDER BY id DESC").fetchone()[0]
    assert '"restored_from": 1' in log


def test_restore_works_with_produced_versions(conn, recipe, rm):
    """13:36: geht immer, auch wenn Versionen schon produziert (fixiert) sind."""
    add_order(conn, recipe["id"], version_id=conn.execute(
        "SELECT current_version_id FROM recipe WHERE id = ?", (recipe["id"],)).fetchone()[0])
    v2 = new_version(conn, get_recipe(conn, recipe["id"]), items=[line(rm["mehl"], 900, step_no=1)])
    add_order(conn, recipe["id"], version_id=conn.execute(
        "SELECT current_version_id FROM recipe WHERE id = ?", (recipe["id"],)).fetchone()[0])
    r = restore_version(conn, recipe["id"], 1, revision=v2["revision"])
    assert r["version_no"] == 3 and [i["amount_g"] for i in r["items"]] == [1000, 600]


def test_review_marks_kept(conn, recipe, rm):
    """15:36: „*“ der alten Version wird übernommen."""
    conn.execute("UPDATE recipe_item SET needs_review = 1 WHERE position = 2 AND recipe_version_id = "
                 "(SELECT current_version_id FROM recipe WHERE id = ?)", (recipe["id"],))
    v2 = new_version(conn, get_recipe(conn, recipe["id"]), items=[line(rm["mehl"], 900, step_no=1)])
    r = restore_version(conn, recipe["id"], 1, revision=v2["revision"])
    assert [i["needs_review"] for i in r["items"]] == [False, True]


def test_archived_raw_material_is_restored(conn, recipe, rm):
    """15:36: archivierter Rohstoff wird trotzdem übernommen."""
    v2 = new_version(conn, recipe, items=[line(rm["mehl"], 1000, step_no=1)])
    archive_raw_material(conn, rm["wasser"])
    r = restore_version(conn, recipe["id"], 1, revision=v2["revision"])
    assert r["items"][1]["raw_material"]["archived"] is True


def test_archived_sub_recipe_blocks(conn, recipe, rm):
    """R05-23 (Freigabebericht Modul 05) bleibt: archiviertes Unterrezept verhindert das Wiederherstellen."""
    vorteig = create_recipe(conn, {"name": "Vorteig", "items": [line(rm["mehl"], 500)]})
    v2 = new_version(conn, recipe, items=[sub(vorteig["id"], 500), line(rm["mehl"], 1000, step_no=1)])
    v3 = new_version(conn, v2, items=[line(rm["mehl"], 1000, step_no=1)])
    archive_recipe(conn, vorteig["id"])
    with pytest.raises(ConflictError) as exc:
        restore_version(conn, recipe["id"], 2, revision=v3["revision"])
    assert exc.value.code == "archived_sub_recipe" and "Vorteig" in exc.value.message
    assert exc.value.message == "„Vorteig“ ist archiviert – mit wiederherstellen?"
    assert [x["name"] for x in exc.value.extra["sub_recipes"]] == ["Vorteig"]
    assert get_recipe(conn, recipe["id"])["version_no"] == 3
    assert get_recipe(conn, vorteig["id"])["archived"] is True


def test_archived_sub_recipe_restored_together(conn, recipe, rm):
    """Mit Bestätigung wird das Unterrezept mit wiederhergestellt (Michael 18.11.2026, 0.6.4)."""
    vorteig = create_recipe(conn, {"name": "Vorteig", "items": [line(rm["mehl"], 500)]})
    v2 = new_version(conn, recipe, items=[sub(vorteig["id"], 500), line(rm["mehl"], 1000, step_no=1)])
    v3 = new_version(conn, v2, items=[line(rm["mehl"], 1000, step_no=1)])
    archive_recipe(conn, vorteig["id"])
    r = restore_version(conn, recipe["id"], 2, revision=v3["revision"], restore_sub_recipes=True)
    assert r["save_result"]["result"] == "new_version" and r["version_no"] == 4
    assert get_recipe(conn, vorteig["id"])["archived"] is False


def test_archived_sub_sub_recipe_restored_in_order(conn, recipe, rm):
    """Auch archivierte Unterrezepte der Unterrezepte werden mit zurückgeholt, tiefstes zuerst."""
    tief = create_recipe(conn, {"name": "Sauer", "items": [line(rm["mehl"], 100)]})
    vorteig = create_recipe(conn, {"name": "Vorteig", "items": [sub(tief["id"], 100), line(rm["mehl"], 400)]})
    v2 = new_version(conn, recipe, items=[sub(vorteig["id"], 500), line(rm["mehl"], 1000, step_no=1)])
    v3 = new_version(conn, v2, items=[line(rm["mehl"], 1000, step_no=1)])
    archive_recipe(conn, vorteig["id"])
    archive_recipe(conn, tief["id"])
    with pytest.raises(ConflictError) as exc:
        restore_version(conn, recipe["id"], 2, revision=v3["revision"])
    assert [x["name"] for x in exc.value.extra["sub_recipes"]] == ["Sauer", "Vorteig"]
    restore_version(conn, recipe["id"], 2, revision=v3["revision"], restore_sub_recipes=True)
    assert get_recipe(conn, tief["id"])["archived"] is False
    assert get_recipe(conn, vorteig["id"])["archived"] is False


def test_sub_recipe_restore_fails_all_or_nothing(conn, recipe, rm):
    """Kann das Unterrezept nicht zurück (Name belegt), bleibt alles unverändert."""
    vorteig = create_recipe(conn, {"name": "Vorteig", "items": [line(rm["mehl"], 500)]})
    v2 = new_version(conn, recipe, items=[sub(vorteig["id"], 500), line(rm["mehl"], 1000, step_no=1)])
    v3 = new_version(conn, v2, items=[line(rm["mehl"], 1000, step_no=1)])
    archive_recipe(conn, vorteig["id"])
    create_recipe(conn, {"name": "Vorteig", "items": [line(rm["mehl"], 300)]})
    with pytest.raises(ConflictError) as exc:
        restore_version(conn, recipe["id"], 2, revision=v3["revision"], restore_sub_recipes=True)
    assert exc.value.code == "name_taken"
    assert get_recipe(conn, vorteig["id"])["archived"] is True
    assert get_recipe(conn, recipe["id"])["version_no"] == 3


def test_same_content_and_current_version(conn, recipe, rm):
    v2 = new_version(conn, recipe, items=[line(rm["mehl"], 1000, step_no=1)])
    v3 = new_version(conn, v2, items=[line(rm["mehl"], 1000, step_no=1), line(rm["wasser"], 600, step_no=1)])
    r = restore_version(conn, recipe["id"], 1, revision=v3["revision"])           # Version 3 = Version 1
    assert r["save_result"]["result"] == "unchanged" and r["version_no"] == 3
    with pytest.raises(ConflictError) as exc:
        restore_version(conn, recipe["id"], 3, revision=v3["revision"])
    assert exc.value.code == "already_current"


def test_name_taken_revision_and_missing(conn, recipe, rm):
    v2 = new_version(conn, recipe, name="Weizenbrot neu")
    create_recipe(conn, {"name": "Weizenbrot", "items": [line(rm["mehl"], 500)]})   # alter Name jetzt vergeben
    with pytest.raises(ConflictError):
        restore_version(conn, recipe["id"], 1, revision=v2["revision"])
    with pytest.raises(ConflictError) as exc:
        restore_version(conn, recipe["id"], 1, revision=v2["revision"] - 1)
    assert exc.value.code == "changed_elsewhere"
    with pytest.raises(ValidationError):
        restore_version(conn, recipe["id"], 1, revision=None)
    with pytest.raises(NotFoundError):
        restore_version(conn, recipe["id"], 9, revision=v2["revision"])


def test_archived_recipe_cannot_restore_version(conn, recipe, rm):
    v2 = new_version(conn, recipe, items=[line(rm["mehl"], 900, step_no=1)])
    archive_recipe(conn, recipe["id"])
    with pytest.raises(ConflictError) as exc:
        restore_version(conn, recipe["id"], 1, revision=get_recipe(conn, recipe["id"])["revision"])
    assert exc.value.code == "archived"
