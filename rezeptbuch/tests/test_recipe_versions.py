"""Tests: Speichern und Versionen (Modul 05, R05-15 bis R05-19, K4, K05-5, M05-8)."""

import json
import sqlite3

import pytest

from app.errors import ConflictError, NotFoundError, ValidationError
from app.raw_materials import create_raw_material
from app.recipes import create_group, create_recipe, get_recipe, get_version, save_recipe

from conftest import add_order
from test_recipe_service import as_payload, line, sub


@pytest.fixture
def mehl(conn):
    return create_raw_material(conn, {"name": "Weizenmehl 550", "type": "flour", "tolerance": 20})["id"]


@pytest.fixture
def recipe(conn, mehl):
    return create_recipe(conn, {"name": "Weizenbrot", "steps": ["Teig"],
                                "items": [line(mehl, 1000, step_no=1)]})


def produce(conn, recipe):
    """Fixiert die aktuelle Version in einem Auftrag (wie Modul 09 beim Start der Verwiegung)."""
    add_order(conn, recipe["id"], version_id=conn.execute(
        "SELECT current_version_id FROM recipe WHERE id = ?", (recipe["id"],)).fetchone()[0])


def put(conn, recipe, mode=None, revision=None, **changes):
    return save_recipe(conn, recipe["id"], as_payload(recipe, **changes),
                       revision=recipe["revision"] if revision is None else revision, version_mode=mode)


def with_amount(recipe, amount):
    payload = as_payload(recipe)
    payload["items"][0]["amount_g"] = amount
    return payload["items"]


# -- Versionsentscheidung (R05-16, K4) ------------------------------------------------

def test_unchanged_save_creates_nothing(conn, recipe):
    r = put(conn, recipe)
    assert r["save_result"]["result"] == "unchanged"
    assert r["version_no"] == 1 and r["revision"] == 0


def test_change_on_unproduced_version_needs_choice(conn, recipe):
    with pytest.raises(ConflictError) as exc:
        put(conn, recipe, name="Weizenbrot hell")
    assert exc.value.code == "version_choice_required"
    assert get_recipe(conn, recipe["id"])["name"] == "Weizenbrot"     # nichts gespeichert


def test_overwrite_keeps_version(conn, recipe):
    r = put(conn, recipe, mode="overwrite", name="Weizenbrot hell", items=with_amount(recipe, 1100))
    assert r["save_result"]["result"] == "overwritten"
    assert r["version_no"] == 1 and r["name"] == "Weizenbrot hell" and r["items"][0]["amount_g"] == 1100
    assert r["revision"] == 1
    assert len(r["versions"]) == 1


def test_new_version_keeps_old_one(conn, recipe):
    r = put(conn, recipe, mode="new", items=with_amount(recipe, 1100))
    assert r["save_result"]["result"] == "new_version"
    assert r["version_no"] == 2
    assert [v["label"] for v in r["versions"]] == ["aktuell", "old (1)"]
    old = get_version(conn, recipe["id"], 1)
    assert old["items"][0]["amount_g"] == 1000 and old["current"] is False
    assert old["display_name"] == "Weizenbrot old (1)"


def test_produced_version_gets_new_version_automatically(conn, recipe):
    produce(conn, recipe)
    r = put(conn, recipe, mode="overwrite", items=with_amount(recipe, 900))     # Wahl wird übergangen
    assert r["save_result"]["result"] == "new_version"
    assert r["save_result"]["message"] == "Neue Version angelegt, da bereits produziert."
    assert r["version_no"] == 2
    assert r["versions"][1]["produced"] is True and r["versions"][1]["frozen"] is True
    assert get_version(conn, recipe["id"], 1)["items"][0]["amount_g"] == 1000


def test_produced_version_without_choice(conn, recipe):
    produce(conn, recipe)
    assert put(conn, recipe, note="neu")["version_no"] == 2


def test_invalid_version_mode(conn, recipe):
    with pytest.raises(ValidationError):
        put(conn, recipe, mode="vielleicht", name="X")


def test_header_fields_never_create_version(conn, recipe):
    g = create_group(conn, "Brote")
    r = put(conn, recipe, number=77, group_id=g["id"])
    assert r["save_result"]["result"] == "unchanged" and r["save_result"]["message"] == "Gespeichert."
    assert (r["number"], r["group_id"], r["version_no"], r["revision"]) == (77, g["id"], 1, 1)


def test_group_can_be_removed(conn, recipe):
    g = create_group(conn, "Brote")
    r = put(conn, recipe, group_id=g["id"])
    r = put(conn, r, group_id=None)
    assert r["group_id"] is None


def test_number_locked_after_use(conn, mehl, recipe):
    parent = create_recipe(conn, {"name": "Hauptteig", "items": [sub(recipe["id"])]})
    r = get_recipe(conn, recipe["id"])
    assert r["number_locked"] is True
    with pytest.raises(ConflictError) as exc:
        put(conn, r, number=99)
    assert exc.value.code == "number_locked"
    assert get_recipe(conn, parent["id"])["number_locked"] is False


def test_number_taken_on_save(conn, recipe):
    create_recipe(conn, {"name": "Anderes", "number": 5})
    with pytest.raises(ConflictError) as exc:
        put(conn, recipe, number=5)
    assert exc.value.code == "number_taken"


def test_rename_to_existing_name(conn, recipe):
    create_recipe(conn, {"name": "Roggenbrot"})
    with pytest.raises(ConflictError):
        put(conn, recipe, mode="overwrite", name="roggenbrot")


def test_old_b2_name_stays_saveable(conn, recipe):
    conn.execute("UPDATE recipe_version SET name = '-Altname' WHERE recipe_id = ?", (recipe["id"],))
    conn.execute("UPDATE recipe_version_step SET name = '+Alt'")
    r = get_recipe(conn, recipe["id"])
    saved = put(conn, r, mode="overwrite", items=with_amount(r, 1200))
    assert saved["name"] == "-Altname" and saved["steps"][0]["name"] == "+Alt"
    with pytest.raises(ValidationError):
        put(conn, get_recipe(conn, recipe["id"]), mode="overwrite", name="-Neu")


# -- Gleichzeitiges Bearbeiten (R05-17) ----------------------------------------------------

def test_revision_conflict(conn, recipe):
    put(conn, recipe, mode="overwrite", note="Gerät A")
    with pytest.raises(ConflictError) as exc:
        put(conn, recipe, mode="overwrite", note="Gerät B")         # alter Stand 0
    assert exc.value.code == "changed_elsewhere"
    assert exc.value.extra["revision"] == 1
    assert get_recipe(conn, recipe["id"])["note"] == "Gerät A"


def test_revision_missing(conn, recipe):
    with pytest.raises(ValidationError) as exc:
        save_recipe(conn, recipe["id"], as_payload(recipe), revision=None)
    assert exc.value.code == "revision_missing"


def test_unknown_recipe(conn):
    with pytest.raises(NotFoundError):
        save_recipe(conn, 99, {"name": "X"}, revision=0)


# -- Prüfmarkierung „*“ (R05-14, K05-5) ------------------------------------------------------

def mark_all(conn, recipe):
    conn.execute("UPDATE recipe_item SET needs_review = 1")
    return get_recipe(conn, recipe["id"])


def test_review_mark_stays_when_line_unchanged(conn, mehl, recipe):
    r = mark_all(conn, recipe)
    saved = put(conn, r, mode="overwrite", note="nur Hinweis")
    assert saved["items"][0]["needs_review"] is True


def test_review_confirm_only_overwrites_without_question(conn, recipe):
    r = mark_all(conn, recipe)
    payload = as_payload(r)
    payload["items"][0]["needs_review"] = False                         # Taste „geprüft“
    saved = save_recipe(conn, r["id"], payload, revision=r["revision"])  # ohne version_mode
    assert saved["save_result"]["result"] == "overwritten"
    assert saved["version_no"] == 1 and saved["items"][0]["needs_review"] is False


def test_review_confirm_on_produced_version_gives_new_version(conn, recipe):
    r = mark_all(conn, recipe)
    produce(conn, r)
    payload = as_payload(r)
    payload["items"][0]["needs_review"] = False
    saved = save_recipe(conn, r["id"], payload, revision=r["revision"])
    assert saved["save_result"]["result"] == "new_version" and saved["version_no"] == 2


def test_review_mark_removed_when_amount_changes(conn, recipe):
    r = mark_all(conn, recipe)
    saved = put(conn, r, mode="overwrite", items=with_amount(r, 1234))
    assert saved["items"][0]["needs_review"] is False


def test_review_mark_removed_when_raw_material_changes(conn, recipe):
    r = mark_all(conn, recipe)
    other = create_raw_material(conn, {"name": "Roggenmehl", "type": "flour", "tolerance": 20})["id"]
    payload = as_payload(r)
    payload["items"][0]["raw_material_id"] = other
    saved = save_recipe(conn, r["id"], payload, revision=r["revision"], version_mode="overwrite")
    assert saved["items"][0]["needs_review"] is False


def test_review_mark_moves_with_line(conn, mehl, recipe):
    """Die Markierung hängt an der Zeile (ID), nicht an der Position."""
    r = put(conn, recipe, mode="overwrite", items=[*as_payload(recipe)["items"], line(mehl, 50)])
    conn.execute("UPDATE recipe_item SET needs_review = 1 WHERE position = 1")
    r = get_recipe(conn, r["id"])
    payload = as_payload(r)
    payload["items"].reverse()
    saved = save_recipe(conn, r["id"], payload, revision=r["revision"], version_mode="overwrite")
    assert [(i["amount_g"], i["needs_review"]) for i in saved["items"]] == [(50, False), (1000, True)]


def test_review_mark_cannot_be_set_by_page(conn, recipe):
    payload = as_payload(recipe)
    payload["items"][0]["needs_review"] = True
    saved = save_recipe(conn, recipe["id"], payload, revision=0)
    assert saved["save_result"]["result"] == "unchanged" and saved["items"][0]["needs_review"] is False


# -- Leeres Rezept, Schritte, Datenbankschutz -----------------------------------------------

def test_empty_recipe_can_be_saved(conn, recipe):
    saved = put(conn, recipe, mode="overwrite", items=[], steps=[])
    assert saved["items"] == [] and saved["steps"] == []


def test_overwrite_with_step_changes(conn, mehl, recipe):
    payload = as_payload(recipe, steps=[{"name": "Vorteig"}, {"name": "Teig"}])
    payload["items"][0]["step_no"] = 2
    saved = save_recipe(conn, recipe["id"], payload, revision=0, version_mode="overwrite")
    assert [s["name"] for s in saved["steps"]] == ["Vorteig", "Teig"] and saved["items"][0]["step_no"] == 2


def test_frozen_version_untouched_by_database(conn, recipe):
    produce(conn, recipe)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE recipe_item SET amount_g = 1 WHERE id = ?", (recipe["items"][0]["id"],))


def test_change_log_for_versions(conn, recipe):
    put(conn, recipe, mode="overwrite", note="A")
    r = get_recipe(conn, recipe["id"])
    put(conn, r, mode="new", note="B")
    rows = [dict(x) for x in conn.execute("SELECT action, old_values, new_values FROM change_log "
                                           "WHERE entity = 'recipe' ORDER BY id")]
    assert [x["action"] for x in rows] == ["create", "update", "new_version"]
    assert json.loads(rows[1]["old_values"])["note"] is None and json.loads(rows[1]["new_values"])["note"] == "A"
    assert json.loads(rows[2]["new_values"])["version_no"] == 2


def test_unknown_version(conn, recipe):
    with pytest.raises(NotFoundError):
        get_version(conn, recipe["id"], 5)
