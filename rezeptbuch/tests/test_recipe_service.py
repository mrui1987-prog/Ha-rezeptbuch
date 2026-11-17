"""Tests: Rezeptverwaltung (Modul 05, Teil C2) – Anlegen, Zeilen, Status, Archiv, Kopie, Löschen.

Regeln R05-1 bis R05-14 und R05-20 bis R05-28 aus docs/rezepte.md. Die Versionsregeln
(R05-15 bis R05-19) stehen in test_recipe_versions.py, die Gruppen in test_recipe_groups.py.
"""

import json

import pytest

from app.errors import ConflictError, NotFoundError, ValidationError
from app.raw_materials import archive_raw_material, create_raw_material
from app.recipes import (
    archive_recipe,
    copy_recipe,
    create_group,
    create_recipe,
    delete_recipe,
    get_recipe,
    list_recipes,
    lock_recipe,
    next_number,
    restore_recipe,
    save_recipe,
    set_batch_sizes,
    set_piece_weights,
    unlock_recipe,
    usage,
)

from conftest import add_order


# -- Hilfen ------------------------------------------------------------------------

@pytest.fixture
def rm(conn):
    """Drei Rohstoffe: Mehl (Typ Mehl), Wasser (1 %), Salz (0 %)."""
    return {
        "mehl": create_raw_material(conn, {"name": "Weizenmehl 550", "type": "flour", "tolerance": 20})["id"],
        "wasser": create_raw_material(conn, {"name": "Wasser", "tolerance": "1", "tolerance_unit": "percent"})["id"],
        "salz": create_raw_material(conn, {"name": "Salz", "tolerance": "0", "tolerance_unit": "percent",
                                           "display_name": "Salz fein"})["id"],
    }


def line(raw_material_id, amount=1000, **kw):
    data = {"type": "raw_material", "raw_material_id": raw_material_id, "amount_g": amount}
    data.update(kw)
    return data


def sub(recipe_id, amount=500):
    return {"type": "sub_recipe", "sub_recipe_id": recipe_id, "amount_g": amount}


def make(conn, name="Weizenbrot", items=None, **kw):
    data = {"name": name, "items": items or []}
    data.update(kw)
    return create_recipe(conn, data)


def as_payload(recipe: dict, **changes) -> dict:
    """Rezept aus get_recipe → Speicherdaten, wie die Seite sie schickt."""
    items = []
    for i in recipe["items"]:
        item = {"id": i["id"], "type": i["type"], "amount_g": i["amount_g"], "step_no": i["step_no"],
                "needs_review": i["needs_review"]}
        if i["type"] == "raw_material":
            item["raw_material_id"] = i["raw_material"]["id"]
            if i["tolerance_override"]:
                item["tolerance"] = i["tolerance_override"]["value"]
                item["tolerance_unit"] = i["tolerance_override"]["unit"]
        else:
            item["sub_recipe_id"] = i["sub_recipe"]["id"]
        items.append(item)
    data = {"number": recipe["number"], "name": recipe["name"], "group_id": recipe["group_id"],
            "knead_slow_min": recipe["knead_slow_min"], "knead_fast_min": recipe["knead_fast_min"],
            "note": recipe["note"], "note_display": recipe["note_display"],
            "steps": [{"name": s["name"]} for s in recipe["steps"]], "items": items}
    data.update(changes)
    return data


def save(conn, recipe, mode="overwrite", **changes):
    return save_recipe(conn, recipe["id"], as_payload(recipe, **changes), revision=recipe["revision"],
                       version_mode=mode)


def log_rows(conn, entity="recipe"):
    return [dict(r) for r in conn.execute(
        "SELECT source, entity_id, action, old_values, new_values FROM change_log WHERE entity = ? ORDER BY id",
        (entity,))]


# -- Anlegen, Nummer, Name (R05-1, R05-2, R05-3, R05-7) ----------------------------------

def test_create_recipe_with_version_one_locked(conn, rm):
    r = make(conn, items=[line(rm["mehl"], 1000), line(rm["wasser"], 600)], knead_slow_min=5, knead_fast_min=6,
             note="- mit Mohn bestreuen", note_display="start")
    assert r["number"] == 1
    assert r["locked"] is True and r["archived"] is False
    assert r["version_no"] == 1 and r["revision"] == 0
    assert r["knead"] == "5+6"
    assert r["note"] == "- mit Mohn bestreuen"        # Hinweistext ist frei (R05-3)
    assert r["note_display"] == "start"
    assert [i["position"] for i in r["items"]] == [1, 2]
    assert r["versions"][0]["label"] == "aktuell"


def test_next_number_counts_archived(conn, rm):
    assert next_number(conn) == 1
    a = make(conn, "A")
    make(conn, "B")
    archive_recipe(conn, a["id"])
    assert next_number(conn) == 3


def test_number_by_hand_and_taken(conn):
    assert make(conn, "A", number=50)["number"] == 50
    with pytest.raises(ConflictError) as exc:
        make(conn, "B", number=50)
    assert exc.value.code == "number_taken"


@pytest.mark.parametrize("value", ["0", "-1", "abc", "²", 1.5])
def test_number_invalid(conn, value):
    with pytest.raises(ValidationError):
        make(conn, "A", number=value)


def test_name_required_and_normalized(conn):
    with pytest.raises(ValidationError):
        make(conn, "   ")
    assert make(conn, "  Weizen   brot ")["name"] == "Weizen brot"


def test_name_max_length(conn):
    make(conn, "x" * 100)
    with pytest.raises(ValidationError):
        make(conn, "y" * 101)


def test_name_unique_case_insensitive_with_umlauts(conn):
    make(conn, "Käsekuchen")
    with pytest.raises(ConflictError) as exc:
        make(conn, "KÄSEKUCHEN")
    assert exc.value.code == "name_taken"


def test_name_of_archived_recipe_is_free(conn):
    a = make(conn, "Stollen")
    archive_recipe(conn, a["id"])
    assert make(conn, "Stollen")["name"] == "Stollen"


@pytest.mark.parametrize("bad", ["=SUMME(A1)", "+1", "-Brot", "@x", "  =x"])
def test_b2_recipe_name(conn, bad):
    with pytest.raises(ValidationError) as exc:
        make(conn, bad)
    assert exc.value.code == "formula_start"


def test_b2_step_name(conn):
    with pytest.raises(ValidationError) as exc:
        make(conn, "A", steps=[{"name": "=Vorteig"}])
    assert exc.value.field == "steps.1.name"


def test_group_must_exist(conn):
    with pytest.raises(ValidationError) as exc:
        make(conn, "A", group_id=99)
    assert exc.value.code == "group_not_found"
    g = create_group(conn, "Brote")
    assert make(conn, "B", group_id=g["id"])["group_name"] == "Brote"


@pytest.mark.parametrize("field,value", [("knead_slow_min", -1), ("knead_fast_min", "x"), ("knead_slow_min", 1000)])
def test_knead_invalid(conn, field, value):
    with pytest.raises(ValidationError):
        make(conn, "A", **{field: value})


def test_knead_one_side_empty(conn):
    assert make(conn, "A", knead_fast_min=4)["knead"] == "0+4"
    assert make(conn, "B")["knead"] is None


def test_note_limits(conn):
    make(conn, "A", note="x" * 2000)
    with pytest.raises(ValidationError):
        make(conn, "B", note="x" * 2001)
    with pytest.raises(ValidationError):
        make(conn, "C", note_display="mitte")
    assert make(conn, "D", note="   ")["note"] is None


# -- Zeilen (R05-8 bis R05-14) -------------------------------------------------------

def test_zero_grams_is_hand_addition(conn, rm):
    r = make(conn, items=[line(rm["salz"], 0)])
    assert r["items"][0]["hand_addition"] is True
    assert r["items"][0]["amount_g"] == 0


def test_negative_or_fraction_amount_rejected(conn, rm):
    with pytest.raises(ValidationError) as exc:
        make(conn, items=[line(rm["mehl"], -1)])
    assert "Zeile 1" in exc.value.message
    with pytest.raises(ValidationError):
        make(conn, items=[line(rm["mehl"], "10,5")])


def test_unknown_raw_material(conn):
    with pytest.raises(ValidationError) as exc:
        make(conn, items=[line(999)])
    assert exc.value.code == "not_found"


def test_archived_raw_material_not_selectable_for_new_line(conn, rm):
    archive_raw_material(conn, rm["wasser"])
    with pytest.raises(ValidationError) as exc:
        make(conn, items=[line(rm["wasser"])])
    assert exc.value.code == "raw_material_archived"


def test_existing_line_with_archived_raw_material_is_kept(conn, rm):
    r = make(conn, items=[line(rm["wasser"], 600)])
    archive_raw_material(conn, rm["wasser"])
    r = get_recipe(conn, r["id"])
    assert r["items"][0]["raw_material"]["archived"] is True
    # Speichern mit geänderter Menge bleibt möglich (bestehende Zeile)
    payload = as_payload(r)
    payload["items"][0]["amount_g"] = 650
    saved = save_recipe(conn, r["id"], payload, revision=r["revision"], version_mode="overwrite")
    assert saved["items"][0]["amount_g"] == 650


def test_effective_tolerance_and_station_name(conn, rm):
    r = make(conn, items=[line(rm["mehl"]), line(rm["salz"], 20), line(rm["wasser"], 600, tolerance="2,5",
                                                                        tolerance_unit="percent")])
    mehl, salz, wasser = r["items"]
    assert mehl["tolerance"] == {"unit": "g", "value": 20} and mehl["tolerance_override"] is None
    assert salz["tolerance"] == {"unit": "percent", "value": 0.0}
    assert salz["raw_material"]["station_name"] == "Salz fein"
    assert wasser["tolerance_override"] == {"unit": "percent", "value": 2.5}
    assert wasser["tolerance"] == {"unit": "percent", "value": 2.5}


@pytest.mark.parametrize("tol,unit", [("-1", "g"), ("1,5", "g"), ("100,1", "percent"), ("2,55", "percent"), ("x", "g")])
def test_line_tolerance_invalid(conn, rm, tol, unit):
    with pytest.raises(ValidationError) as exc:
        make(conn, items=[line(rm["mehl"], tolerance=tol, tolerance_unit=unit)])
    assert exc.value.message.startswith("Zeile 1:")


def test_line_tolerance_zero_g_and_zero_percent(conn, rm):
    r = make(conn, items=[line(rm["mehl"], tolerance="0", tolerance_unit="g"),
                          line(rm["wasser"], tolerance="0", tolerance_unit="percent")])
    assert r["items"][0]["tolerance"] == {"unit": "g", "value": 0}
    assert r["items"][1]["tolerance"] == {"unit": "percent", "value": 0.0}


def test_sub_recipe_line(conn, rm):
    vorteig = make(conn, "Vorteig", items=[line(rm["mehl"], 300)])
    lock_recipe(conn, vorteig["id"])                         # gesperrt bleibt verwendbar (M05-5)
    r = make(conn, "Hauptteig", items=[sub(vorteig["id"], 500)])
    assert r["items"][0]["type"] == "sub_recipe"
    assert r["items"][0]["sub_recipe"]["name"] == "Vorteig"
    assert r["items"][0]["sub_recipe"]["locked"] is True
    assert r["items"][0]["tolerance"] is None


def test_sub_recipe_needs_amount_and_no_tolerance(conn, rm):
    vorteig = make(conn, "Vorteig")
    with pytest.raises(ValidationError):
        make(conn, "H", items=[sub(vorteig["id"], 0)])
    with pytest.raises(ValidationError):
        make(conn, "H", items=[{**sub(vorteig["id"]), "tolerance": "5"}])


def test_archived_sub_recipe_not_selectable(conn):
    vorteig = make(conn, "Vorteig")
    archive_recipe(conn, vorteig["id"])
    with pytest.raises(ValidationError) as exc:
        make(conn, "H", items=[sub(vorteig["id"])])
    assert exc.value.code == "sub_recipe_archived"


def test_cycle_direct_self(conn, rm):
    r = make(conn, "A")
    with pytest.raises(ConflictError) as exc:
        save(conn, r, items=[sub(r["id"])])
    assert exc.value.code == "cycle"
    assert "A → A" in exc.value.message


def test_cycle_over_three_recipes(conn, rm):
    a = make(conn, "A", items=[line(rm["mehl"])])
    b = make(conn, "B", items=[sub(a["id"])])
    c = make(conn, "C", items=[sub(b["id"])])
    a = get_recipe(conn, a["id"])
    with pytest.raises(ConflictError) as exc:
        save(conn, a, items=[sub(c["id"])])
    assert exc.value.code == "cycle"
    assert exc.value.message.endswith("A → C → B → A")
    assert get_recipe(conn, a["id"])["items"][0]["type"] == "raw_material"     # nichts gespeichert


def test_positions_renumbered_and_steps(conn, rm):
    r = make(conn, items=[line(rm["mehl"], step_no=1), line(rm["wasser"], 600, step_no=2), line(rm["salz"], 20)],
             steps=[{"name": "Vorteig"}, "Hauptteig"])
    assert [s["name"] for s in r["steps"]] == ["Vorteig", "Hauptteig"]
    assert [(i["position"], i["step_no"]) for i in r["items"]] == [(1, 1), (2, 2), (3, None)]


def test_step_reference_must_exist(conn, rm):
    with pytest.raises(ValidationError):
        make(conn, items=[line(rm["mehl"], step_no=2)], steps=[{"name": "Teig"}])


def test_step_name_required_and_max(conn):
    with pytest.raises(ValidationError):
        make(conn, steps=[{"name": " "}])
    with pytest.raises(ValidationError):
        make(conn, steps=[{"name": "x" * 61}])


def test_new_lines_never_get_review_mark(conn, rm):
    r = make(conn, items=[line(rm["mehl"], needs_review=True)])
    assert r["items"][0]["needs_review"] is False


# -- Summen (R05-27) ------------------------------------------------------------------

def test_sums_count_direct_flour_only(conn, rm):
    vorteig = make(conn, "Vorteig", items=[line(rm["mehl"], 300), line(rm["wasser"], 300)])
    r = make(conn, "Hauptteig", items=[line(rm["mehl"], 1000), line(rm["wasser"], 600), sub(vorteig["id"], 600)])
    assert r["sums"] == {"total_g": 2200, "flour_g": 1000}


# -- Liste (Lese-Schnittstelle) ---------------------------------------------------------

def test_list_default_is_station_view(conn, rm):
    a = make(conn, "A", items=[line(rm["mehl"])])
    b = make(conn, "B", items=[line(rm["mehl"])])
    c = make(conn, "C", items=[line(rm["mehl"])])
    unlock_recipe(conn, a["id"])
    unlock_recipe(conn, c["id"])
    archive_recipe(conn, c["id"])
    assert [r["name"] for r in list_recipes(conn)] == ["A"]
    assert [r["name"] for r in list_recipes(conn, include_locked=True)] == ["A", "B"]
    assert len(list_recipes(conn, include_locked=True, include_archived=True)) == 3
    assert b["locked"] is True


def test_list_new_filters(conn, rm):
    vor = make(conn, "Vorteig", items=[line(rm["mehl"])])
    haupt = make(conn, "Hauptteig", items=[sub(vor["id"]), line(rm["mehl"])])
    unlock_recipe(conn, vor["id"])
    names = lambda **kw: [r["name"] for r in list_recipes(conn, include_locked=True, **kw)]  # noqa: E731
    assert names() == ["Vorteig", "Hauptteig"]
    assert names(include_public=False) == ["Hauptteig"]          # öffentliche ausgeblendet
    assert names(has_sub_recipes=True) == ["Hauptteig"]
    assert names(never_weighed=True) == ["Vorteig", "Hauptteig"]  # noch nie verwogen
    conn.execute("INSERT INTO production_order (recipe_id, basis_type, basis_value) VALUES (?, 'total', 1000)",
                 (haupt["id"],))
    assert names(never_weighed=True) == ["Vorteig"]


def test_list_search_and_group(conn, rm):
    g = create_group(conn, "Kuchen")
    make(conn, "Käsekuchen", number=12, group_id=g["id"])
    make(conn, "Weizenbrot", number=30)
    assert [r["name"] for r in list_recipes(conn, search="KÄSE", include_locked=True)] == ["Käsekuchen"]
    assert [r["name"] for r in list_recipes(conn, search="30", include_locked=True)] == ["Weizenbrot"]
    assert [r["name"] for r in list_recipes(conn, group_id=g["id"], include_locked=True)] == ["Käsekuchen"]


def test_list_counts(conn, rm):
    make(conn, "A", items=[line(rm["mehl"], 1000), line(rm["wasser"], 600)])
    row = list_recipes(conn, include_locked=True)[0]
    assert (row["total_g"], row["item_count"], row["review_count"], row["version_no"]) == (1600, 2, 0, 1)


def test_get_unknown_recipe(conn):
    with pytest.raises(NotFoundError):
        get_recipe(conn, 99)


# -- Stückgewichte und Chargengrößen (R05-20) ----------------------------------------------

def test_piece_weights_and_batch_sizes(conn):
    r = make(conn)
    r = set_piece_weights(conn, r["id"], [{"label": "Stück", "weight_g": 65}, {"label": "Ballen", "weight_g": 1550}])
    assert [(p["label"], p["weight_g"]) for p in r["piece_weights"]] == [("Stück", 65), ("Ballen", 1550)]
    assert r["version_no"] == 1                                   # keine neue Version (M05-2)
    r = set_batch_sizes(conn, r["id"], [{"label": "30 Stück", "kind": "pieces", "value": 30, "piece_weight_label": "stück"},
                                        {"label": "10 kg", "kind": "weight", "value": 10000}])
    assert r["batch_sizes"][0]["piece_weight_label"] == "Stück"
    assert r["batch_sizes"][1]["piece_weight_id"] is None


def test_piece_weight_label_unique_and_b2(conn):
    r = make(conn)
    with pytest.raises(ValidationError) as exc:
        set_piece_weights(conn, r["id"], [{"label": "Stück", "weight_g": 65}, {"label": "STÜCK", "weight_g": 70}])
    assert exc.value.code == "label_taken"
    with pytest.raises(ValidationError):
        set_piece_weights(conn, r["id"], [{"label": "@Stück", "weight_g": 65}])
    with pytest.raises(ValidationError):
        set_piece_weights(conn, r["id"], [{"label": "Stück", "weight_g": 0}])
    with pytest.raises(ValidationError):
        set_piece_weights(conn, r["id"], [{"label": "x" * 31, "weight_g": 5}])


def test_piece_weights_keep_ids_and_swap_labels(conn):
    r = make(conn)
    r = set_piece_weights(conn, r["id"], [{"label": "A", "weight_g": 1}, {"label": "B", "weight_g": 2}])
    a, b = r["piece_weights"]
    r = set_piece_weights(conn, r["id"], [{"id": a["id"], "label": "B", "weight_g": 1},
                                          {"id": b["id"], "label": "A", "weight_g": 2}])
    assert [(p["id"], p["label"]) for p in r["piece_weights"]] == [(a["id"], "B"), (b["id"], "A")]


def test_delete_piece_weight_with_batch_size_needs_confirmation(conn):
    r = make(conn)
    r = set_piece_weights(conn, r["id"], [{"label": "Stück", "weight_g": 65}])
    r = set_batch_sizes(conn, r["id"], [{"label": "30 Stück", "kind": "pieces", "value": 30,
                                         "piece_weight_id": r["piece_weights"][0]["id"]}])
    with pytest.raises(ConflictError) as exc:
        set_piece_weights(conn, r["id"], [])
    assert exc.value.code == "confirmation_required"
    assert exc.value.extra["batch_sizes"][0]["label"] == "30 Stück"
    assert len(get_recipe(conn, r["id"])["piece_weights"]) == 1      # nichts geändert
    r = set_piece_weights(conn, r["id"], [], confirm_delete_batch_sizes=True)
    assert r["piece_weights"] == [] and r["batch_sizes"] == []


def test_batch_size_rules(conn):
    r = make(conn)
    with pytest.raises(ValidationError) as exc:
        set_batch_sizes(conn, r["id"], [{"label": "30 Stück", "kind": "pieces", "value": 30, "piece_weight_label": "Stück"}])
    assert exc.value.code == "piece_weight_missing"
    with pytest.raises(ValidationError):
        set_batch_sizes(conn, r["id"], [{"label": "x", "kind": "weight", "value": 0}])
    with pytest.raises(ValidationError):
        set_batch_sizes(conn, r["id"], [{"label": "=x", "kind": "weight", "value": 5}])
    with pytest.raises(ValidationError):
        set_batch_sizes(conn, r["id"], [{"label": "x", "kind": "liter", "value": 5}])


def test_piece_weight_of_other_recipe_not_usable(conn):
    a = set_piece_weights(conn, make(conn, "A")["id"], [{"label": "Stück", "weight_g": 65}])
    b = make(conn, "B")
    with pytest.raises(ValidationError):
        set_batch_sizes(conn, b["id"], [{"label": "x", "kind": "pieces", "value": 3,
                                         "piece_weight_id": a["piece_weights"][0]["id"]}])


def test_portion_revision_conflict(conn):
    r = make(conn)
    set_piece_weights(conn, r["id"], [{"label": "Stück", "weight_g": 65}], revision=0)
    with pytest.raises(ConflictError) as exc:
        set_batch_sizes(conn, r["id"], [], revision=0)
    assert exc.value.code == "changed_elsewhere"


# -- Freischalten und Sperren (R05-21, K05-3, K05-4) -----------------------------------

def test_unlock_needs_lines(conn):
    r = make(conn)
    with pytest.raises(ConflictError) as exc:
        unlock_recipe(conn, r["id"])
    assert exc.value.code == "empty_recipe"


def test_unlock_warns_for_zero_percent(conn, rm):
    r = make(conn, items=[line(rm["mehl"]), line(rm["salz"], 20)])
    with pytest.raises(ConflictError) as exc:
        unlock_recipe(conn, r["id"])
    assert exc.value.code == "confirmation_required"
    assert exc.value.extra["zero_percent_items"] == [{"position": 2, "name": "Salz"}]
    assert get_recipe(conn, r["id"])["locked"] is True
    assert unlock_recipe(conn, r["id"], confirm=True)["locked"] is False


def test_unlock_warns_for_review_marks(conn, rm):
    r = make(conn, items=[line(rm["mehl"])])
    conn.execute("UPDATE recipe_item SET needs_review = 1")          # wie nach dem Import
    with pytest.raises(ConflictError) as exc:
        unlock_recipe(conn, r["id"])
    assert exc.value.extra["review_items"] == [{"position": 1, "name": "Weizenmehl 550"}]


def test_lock_and_log(conn, rm):
    r = make(conn, items=[line(rm["mehl"])])
    unlock_recipe(conn, r["id"])
    assert lock_recipe(conn, r["id"])["locked"] is True
    actions = [(row["action"], json.loads(row["new_values"])) for row in log_rows(conn)][1:]
    assert actions == [("update", {"locked": 0}), ("update", {"locked": 1})]


# -- Archivieren, Wiederherstellen (R05-22, R05-23) -----------------------------------------

def test_archive_blocked_while_sub_recipe_of_active_recipe(conn, rm):
    vorteig = make(conn, "Vorteig", items=[line(rm["mehl"])])
    haupt = make(conn, "Hauptteig", items=[sub(vorteig["id"])])
    with pytest.raises(ConflictError) as exc:
        archive_recipe(conn, vorteig["id"])
    assert exc.value.code == "in_use_as_sub_recipe"
    assert "1 Rezept " in exc.value.message and "Hauptteig" in exc.value.message
    archive_recipe(conn, haupt["id"])                     # Eltern archiviert → jetzt möglich
    assert archive_recipe(conn, vorteig["id"])["archived"] is True


def test_archive_allowed_when_only_old_version_uses_it(conn, rm):
    vorteig = make(conn, "Vorteig", items=[line(rm["mehl"])])
    haupt = make(conn, "Hauptteig", items=[sub(vorteig["id"])])
    save(conn, haupt, mode="new", items=[line(rm["mehl"])])
    assert archive_recipe(conn, vorteig["id"])["archived"] is True


def test_archived_recipe_cannot_be_edited(conn, rm):
    r = make(conn, items=[line(rm["mehl"])])
    archive_recipe(conn, r["id"])
    r = get_recipe(conn, r["id"])
    with pytest.raises(ConflictError) as exc:
        save(conn, r, name="Neu")
    assert exc.value.code == "archived"


def test_restore_keeps_status_and_checks_name(conn, rm):
    a = make(conn, "Stollen", items=[line(rm["mehl"])])
    unlock_recipe(conn, a["id"])
    archive_recipe(conn, a["id"])
    b = make(conn, "STOLLEN")
    with pytest.raises(ConflictError) as exc:
        restore_recipe(conn, a["id"])
    assert exc.value.code == "name_taken"
    delete_recipe(conn, b["id"])
    restored = restore_recipe(conn, a["id"])
    assert restored["archived"] is False and restored["locked"] is False


def test_archive_twice_and_restore_active(conn):
    r = make(conn)
    archive_recipe(conn, r["id"])
    with pytest.raises(ConflictError):
        archive_recipe(conn, r["id"])
    restore_recipe(conn, r["id"])
    with pytest.raises(ConflictError):
        restore_recipe(conn, r["id"])


# -- Kopieren (R05-24) --------------------------------------------------------------------

def test_copy_takes_everything(conn, rm):
    g = create_group(conn, "Brote")
    r = make(conn, "Weizenbrot", group_id=g["id"], steps=["Teig"], knead_slow_min=5, knead_fast_min=6,
             items=[line(rm["mehl"], step_no=1), line(rm["wasser"], 600, tolerance="2", tolerance_unit="g")])
    conn.execute("UPDATE recipe_item SET needs_review = 1 WHERE position = 2")
    r = set_piece_weights(conn, r["id"], [{"label": "Stück", "weight_g": 65}])
    set_batch_sizes(conn, r["id"], [{"label": "30 Stück", "kind": "pieces", "value": 30, "piece_weight_label": "Stück"}])
    unlock_recipe(conn, r["id"], confirm=True)

    c = copy_recipe(conn, r["id"])
    assert c["name"] == "Kopie von Weizenbrot" and c["number"] == 2
    assert c["locked"] is True and c["group_id"] == g["id"] and c["knead"] == "5+6"
    assert [s["name"] for s in c["steps"]] == ["Teig"]
    assert [(i["amount_g"], i["step_no"], i["needs_review"]) for i in c["items"]] == [(1000, 1, False), (600, None, True)]
    assert c["items"][1]["tolerance_override"] == {"unit": "g", "value": 2}
    assert c["piece_weights"][0]["label"] == "Stück" and c["piece_weights"][0]["id"] != r["piece_weights"][0]["id"]
    assert c["batch_sizes"][0]["piece_weight_id"] == c["piece_weights"][0]["id"]
    assert copy_recipe(conn, r["id"])["name"] == "Kopie 2 von Weizenbrot"
    created = json.loads(log_rows(conn)[-1]["new_values"])
    assert created["copied_from"]["number"] == 1


def test_copy_long_name_is_shortened(conn):
    r = make(conn, "x" * 100)
    assert len(copy_recipe(conn, r["id"])["name"]) == 100


# -- Löschen (R05-25) ---------------------------------------------------------------------

def test_delete_unused_recipe_with_everything(conn, rm):
    r = make(conn, items=[line(rm["mehl"])], steps=["Teig"])
    r = set_piece_weights(conn, r["id"], [{"label": "Stück", "weight_g": 65}])
    set_batch_sizes(conn, r["id"], [{"label": "10", "kind": "pieces", "value": 10, "piece_weight_label": "Stück"}])
    save(conn, get_recipe(conn, r["id"]), mode="new", name="Weizenbrot neu")
    delete_recipe(conn, r["id"])
    for table in ("recipe", "recipe_version", "recipe_item", "recipe_version_step", "recipe_piece_weight",
                  "recipe_batch_size"):
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert log_rows(conn)[-1]["action"] == "delete"


def test_delete_used_as_sub_recipe_or_in_order(conn, rm):
    vorteig = make(conn, "Vorteig", items=[line(rm["mehl"])])
    haupt = make(conn, "Hauptteig", items=[sub(vorteig["id"])])
    with pytest.raises(ConflictError) as exc:
        delete_recipe(conn, vorteig["id"])
    assert exc.value.code == "in_use"
    add_order(conn, haupt["id"])
    with pytest.raises(ConflictError):
        delete_recipe(conn, haupt["id"])


def test_usage(conn, rm):
    vorteig = make(conn, "Vorteig", items=[line(rm["mehl"])])
    haupt = make(conn, "Hauptteig", items=[sub(vorteig["id"])])
    use = usage(conn, vorteig["id"])
    assert use["used"] is True and use["parents"] == [{"id": haupt["id"], "number": 2, "name": "Hauptteig"}]
    assert usage(conn, haupt["id"])["used"] is False


# -- Protokoll (R05-28) -------------------------------------------------------------------

def test_change_log_for_create(conn, rm):
    r = make(conn, items=[line(rm["mehl"])])
    rows = log_rows(conn)
    assert len(rows) == 1 and rows[0]["action"] == "create" and rows[0]["entity_id"] == r["id"]
    new = json.loads(rows[0]["new_values"])
    assert new["name"] == "Weizenbrot" and new["locked"] == 1 and new["items"][0]["amount_g"] == 1000


# -- Teil C3: interne Notiz (KC2-2) und Filter „mit archivierten Rohstoffen“ (KC2-5) ------------

def test_internal_note_create_and_public_view(conn, rm):
    r = make(conn, items=[line(rm["mehl"])], internal_note="  Ofen 2 nehmen  ")
    assert r["internal_note"] == "Ofen 2 nehmen"
    assert "internal_note" not in get_recipe(conn, r["id"], include_internal=False)   # Stationen sehen sie nie


def test_internal_note_change_creates_no_version(conn, rm):
    r = make(conn, items=[line(rm["mehl"])])
    unlock_recipe(conn, r["id"])
    conn.execute("UPDATE recipe_version SET frozen_at = CURRENT_TIMESTAMP WHERE id = "
                 "(SELECT current_version_id FROM recipe WHERE id = ?)", (r["id"],))   # schon gewogen
    data = {"name": r["name"], "items": [line(rm["mehl"], id=r["items"][0]["id"])], "internal_note": "neu"}
    result = save_recipe(conn, r["id"], data, revision=r["revision"])
    assert result["internal_note"] == "neu"
    assert result["version_no"] == 1 and result["save_result"]["result"] == "unchanged"
    assert result["revision"] == r["revision"] + 1
    log = conn.execute("SELECT old_values, new_values FROM change_log WHERE entity = 'recipe' AND action = 'update' "
                       "ORDER BY id DESC LIMIT 1").fetchone()
    assert json.loads(log[1]) == {"internal_note": "neu"}


def test_internal_note_missing_field_unchanged(conn, rm):
    r = make(conn, items=[line(rm["mehl"])], internal_note="bleibt")
    data = {"name": r["name"], "items": [line(rm["mehl"], id=r["items"][0]["id"])]}
    assert save_recipe(conn, r["id"], data, revision=r["revision"])["internal_note"] == "bleibt"
    data["internal_note"] = ""
    assert save_recipe(conn, r["id"], data, revision=r["revision"])["internal_note"] is None


def test_internal_note_too_long(conn, rm):
    with pytest.raises(ValidationError, match="Interne Notiz"):
        make(conn, internal_note="x" * 2001)


def test_internal_note_copied(conn, rm):
    r = make(conn, items=[line(rm["mehl"])], internal_note="Notiz")
    assert copy_recipe(conn, r["id"])["internal_note"] == "Notiz"


def test_filter_archived_raw_materials(conn, rm):
    a = make(conn, "Mit Salz", items=[line(rm["mehl"]), line(rm["salz"], 20)])
    make(conn, "Ohne Salz", items=[line(rm["mehl"])])
    assert list_recipes(conn, include_locked=True, archived_raw_materials=True) == []
    archive_raw_material(conn, rm["salz"])
    hits = list_recipes(conn, include_locked=True, archived_raw_materials=True)
    assert [h["id"] for h in hits] == [a["id"]]
    assert hits[0]["archived_raw_material_count"] == 1
    assert {r["name"]: r["archived_raw_material_count"] for r in list_recipes(conn, include_locked=True)} == \
        {"Mit Salz": 1, "Ohne Salz": 0}
