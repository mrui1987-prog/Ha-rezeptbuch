"""Tests: Rezeptgruppen (Modul 05, M05-9, R05-26)."""

import pytest

from app.errors import ConflictError, NotFoundError, ValidationError
from app.recipes import (
    archive_recipe,
    create_group,
    create_recipe,
    delete_group,
    list_groups,
    rename_group,
    reorder_groups,
)


def test_create_and_order(conn):
    a = create_group(conn, "Brote")
    b = create_group(conn, " Kuchen  und Torten ")
    assert b["name"] == "Kuchen und Torten"
    assert [(g["name"], g["sort_order"]) for g in list_groups(conn)] == [("Brote", 1), ("Kuchen und Torten", 2)]
    assert a["recipe_count"] == 0


def test_name_rules(conn):
    create_group(conn, "Brote")
    with pytest.raises(ConflictError):
        create_group(conn, "BROTE")
    with pytest.raises(ValidationError):
        create_group(conn, "")
    with pytest.raises(ValidationError):
        create_group(conn, "x" * 61)
    with pytest.raises(ValidationError) as exc:
        create_group(conn, "=Brote")
    assert exc.value.code == "formula_start"


def test_rename(conn):
    a = create_group(conn, "Brote")
    create_group(conn, "Kuchen")
    assert rename_group(conn, a["id"], "Brot")["name"] == "Brot"
    assert rename_group(conn, a["id"], "BROT")["name"] == "BROT"          # nur Schreibweise ändern
    with pytest.raises(ConflictError):
        rename_group(conn, a["id"], "kuchen")
    with pytest.raises(ValidationError):
        rename_group(conn, a["id"], "+Brot")
    with pytest.raises(NotFoundError):
        rename_group(conn, 99, "X")


def test_reorder(conn):
    a, b, c = (create_group(conn, n)["id"] for n in ("A", "B", "C"))
    assert [g["name"] for g in reorder_groups(conn, [c, a, b])] == ["C", "A", "B"]
    with pytest.raises(ValidationError):
        reorder_groups(conn, [c, a])
    with pytest.raises(ValidationError):
        reorder_groups(conn, "abc")


def test_delete_only_when_empty_including_archived(conn):
    g = create_group(conn, "Brote")
    r = create_recipe(conn, {"name": "Weizenbrot", "group_id": g["id"]})
    archive_recipe(conn, r["id"])
    groups = list_groups(conn)
    assert (groups[0]["recipe_count"], groups[0]["recipe_count_all"]) == (0, 1)
    with pytest.raises(ConflictError) as exc:
        delete_group(conn, g["id"])
    assert exc.value.code == "in_use"
    empty = create_group(conn, "Leer")
    delete_group(conn, empty["id"])
    assert [x["name"] for x in list_groups(conn)] == ["Brote"]


def test_change_log(conn):
    g = create_group(conn, "Brote")
    rename_group(conn, g["id"], "Brot")
    delete_group(conn, g["id"])
    actions = [r[0] for r in conn.execute(
        "SELECT action FROM change_log WHERE entity = 'recipe_group' ORDER BY id")]
    assert actions == ["create", "update", "delete"]
