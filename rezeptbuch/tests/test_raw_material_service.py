"""Tests: Rohstoffverwaltung (Modul 03, Regeln R03-1 bis R03-12)."""

import json
import threading

import pytest

from app.db import connect, init_database
from app.errors import ConflictError, NotFoundError, ValidationError
from app.raw_materials import (
    archive_raw_material,
    build_csv,
    create_raw_material,
    delete_raw_material,
    get_raw_material,
    list_raw_materials,
    next_number,
    restore_raw_material,
    similar_names,
    update_raw_material,
    usage,
)

from conftest import add_item, add_order, add_raw_material, add_recipe


def make(conn, name="Weizenmehl 550", **kw):
    data = {"name": name, "tolerance": 20}
    data.update(kw)
    return create_raw_material(conn, data)


def log_rows(conn):
    return [dict(r) for r in conn.execute(
        "SELECT source, entity, entity_id, action, old_values, new_values FROM change_log ORDER BY id")]


# -- R03-1 Nummer ------------------------------------------------------------------

def test_next_number_starts_at_one_and_counts_archived(conn):
    assert next_number(conn) == 1
    first = make(conn, "A")
    assert first["number"] == 1
    second = make(conn, "B")
    archive_raw_material(conn, second["id"])
    assert next_number(conn) == 3        # archivierte Nummer wird nicht wieder vergeben


def test_create_without_number_uses_next_free_number(conn):
    assert make(conn, "A")["number"] == 1
    assert make(conn, "B")["number"] == 2


def test_create_with_manual_number_and_duplicate_number_refused(conn):
    assert make(conn, "A", number=50)["number"] == 50
    assert next_number(conn) == 51
    with pytest.raises(ConflictError) as exc:
        make(conn, "B", number=50)
    assert exc.value.code == "number_taken"


@pytest.mark.parametrize("bad", [0, -1, "abc", 1.5, True])
def test_invalid_number_refused(conn, bad):
    with pytest.raises(ValidationError) as exc:
        make(conn, "A", number=bad)
    assert exc.value.field == "number"


@pytest.mark.parametrize("bad", ["²", "①", "١٢٣", "1²"])
def test_non_ascii_digits_refused_as_validation_error(conn, bad):
    """B1: Ziffern-Sonderzeichen dürfen keinen Serverfehler (500) auslösen."""
    with pytest.raises(ValidationError) as exc:
        make(conn, "A", number=bad)
    assert exc.value.field == "number"
    with pytest.raises(ValidationError) as exc:
        make(conn, "B", unit_size_g=bad, unit_label="Ei")
    assert exc.value.field == "unit_size_g"


def test_number_change_allowed_while_unused_and_locked_after_use(conn):
    rm = make(conn, "A")
    changed = update_raw_material(conn, rm["id"], {"number": 77})
    assert changed["number"] == 77
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm["id"])
    with pytest.raises(ConflictError) as exc:
        update_raw_material(conn, rm["id"], {"number": 78})
    assert exc.value.code == "number_locked"
    assert get_raw_material(conn, rm["id"])["number"] == 77


def test_number_change_to_existing_number_refused(conn):
    make(conn, "A")
    b = make(conn, "B")
    with pytest.raises(ConflictError) as exc:
        update_raw_material(conn, b["id"], {"number": 1})
    assert exc.value.code == "number_taken"


def test_leader_raw_material_of_order_counts_as_used(conn):
    rm = make(conn, "Quark")
    recipe, version = add_recipe(conn, 10)
    add_order(conn, recipe, version_id=version, basis_type="raw_material", basis_value=7500,
              basis_raw_material_id=rm["id"])
    assert usage(conn, rm["id"]) == {"recipes": 0, "orders": 1, "batch_items": 0, "used": True}
    with pytest.raises(ConflictError):
        update_raw_material(conn, rm["id"], {"number": 99})
    with pytest.raises(ConflictError, match="Aufträgen oder Chargen"):
        delete_raw_material(conn, rm["id"])


# -- R03-2 Name ---------------------------------------------------------------------

@pytest.mark.parametrize("other", ["weizenmehl 550", "WEIZENMEHL 550", "  Weizenmehl   550  "])
def test_duplicate_name_refused_ignoring_case_and_spaces(conn, other):
    make(conn, "Weizenmehl 550")
    with pytest.raises(ConflictError) as exc:
        make(conn, other)
    assert exc.value.code == "name_taken" and exc.value.field == "name"


def test_duplicate_name_check_handles_umlauts(conn):
    make(conn, "Äpfel")
    with pytest.raises(ConflictError):
        make(conn, "äpfel")
    make(conn, "Mühlenmehl")
    with pytest.raises(ConflictError):
        make(conn, "MÜHLENMEHL")


def test_name_is_normalized_when_saved(conn):
    assert make(conn, "  Roggen   Schrot ")["name"] == "Roggen Schrot"


def test_name_required_and_limited(conn):
    for bad in ("", "   ", None):
        with pytest.raises(ValidationError) as exc:
            create_raw_material(conn, {"name": bad, "tolerance": 5})
        assert exc.value.field == "name"
    with pytest.raises(ValidationError):
        make(conn, "x" * 101)


def test_archived_names_do_not_block_new_names(conn):
    old = make(conn, "Margarine")
    archive_raw_material(conn, old["id"])
    again = make(conn, "margarine")
    assert again["id"] != old["id"]


def test_rename_to_existing_name_refused_but_case_change_of_self_allowed(conn):
    make(conn, "Zucker")
    salt = make(conn, "Salz")
    with pytest.raises(ConflictError):
        update_raw_material(conn, salt["id"], {"name": "zucker"})
    assert update_raw_material(conn, salt["id"], {"name": "SALZ"})["name"] == "SALZ"


# -- R03-3 ähnliche Namen -------------------------------------------------------------

def test_similar_names_hint(conn):
    make(conn, "Margarine")
    make(conn, "Weizenmehl 550")
    found = similar_names(conn, "Marrgarine")
    assert [f["name"] for f in found] == ["Margarine"]
    assert similar_names(conn, "Hefe") == []
    assert similar_names(conn, "") == []
    # sperrt nichts
    assert make(conn, "Marrgarine")["name"] == "Marrgarine"


def test_similar_names_ignores_archived_and_self(conn):
    old = make(conn, "Margarine")
    assert similar_names(conn, "Margarine", exclude_id=old["id"]) == []
    archive_raw_material(conn, old["id"])
    assert similar_names(conn, "Margarine") == []


# -- R03-4 Kurzname -------------------------------------------------------------------

def test_display_name_not_unique_and_station_name(conn):
    a = make(conn, "Backmargarine A", display_name="Margarine")
    b = make(conn, "Ziehmargarine B", display_name="Margarine")
    plain = make(conn, "Salz")
    assert a["station_name"] == b["station_name"] == "Margarine"
    assert a["name"] == "Backmargarine A"          # voller Name bleibt erhalten
    assert plain["display_name"] is None and plain["station_name"] == "Salz"


def test_display_name_can_be_removed(conn):
    rm = make(conn, "Backmargarine A", display_name="Margarine")
    cleared = update_raw_material(conn, rm["id"], {"display_name": ""})
    assert cleared["display_name"] is None
    assert cleared["station_name"] == "Backmargarine A"


# -- R03-5 Toleranz --------------------------------------------------------------------

def test_tolerance_is_required_and_has_no_default(conn):
    for data in ({"name": "A"}, {"name": "A", "tolerance": None}, {"name": "A", "tolerance": ""},
                 {"name": "A", "tolerance": "  "}):
        with pytest.raises(ValidationError) as exc:
            create_raw_material(conn, data)
        assert exc.value.field == "tolerance"
    assert list_raw_materials(conn) == []


def test_tolerance_in_grams_and_zero_is_hand_addition(conn):
    assert make(conn, "A", tolerance=20)["tolerance"] == 20
    zero = make(conn, "B", tolerance=0)
    assert zero["tolerance"] == 0 and zero["tolerance_unit"] == "g"
    assert make(conn, "C", tolerance="15")["tolerance"] == 15


@pytest.mark.parametrize("bad", [2.5, "2,5", -1, "abc", 2_000_000, True])
def test_invalid_tolerance_in_grams(conn, bad):
    with pytest.raises(ValidationError) as exc:
        make(conn, "A", tolerance=bad)
    assert exc.value.field == "tolerance"


def test_tolerance_in_percent_with_tenths(conn):
    rm = make(conn, "A", tolerance_unit="percent", tolerance="2,5")
    assert rm["tolerance"] == 2.5
    stored = conn.execute("SELECT tolerance_unit, tolerance_value FROM raw_material WHERE id = ?",
                          (rm["id"],)).fetchone()
    assert tuple(stored) == ("percent", 25)            # Zehntelprozent (K2)
    assert make(conn, "B", tolerance_unit="percent", tolerance=2.5)["tolerance"] == 2.5
    assert make(conn, "C", tolerance_unit="percent", tolerance=100)["tolerance"] == 100


@pytest.mark.parametrize("bad", [2.55, "0,05", 100.1, 101, -1])
def test_invalid_tolerance_in_percent(conn, bad):
    with pytest.raises(ValidationError) as exc:
        make(conn, "A", tolerance_unit="percent", tolerance=bad)
    assert exc.value.field == "tolerance"


def test_unknown_unit_and_type_refused(conn):
    with pytest.raises(ValidationError) as exc:
        make(conn, "A", tolerance_unit="kg")
    assert exc.value.field == "tolerance_unit"
    with pytest.raises(ValidationError) as exc:
        make(conn, "B", type="liquid")
    assert exc.value.field == "type"


def test_changing_unit_requires_new_tolerance_value(conn):
    rm = make(conn, "A", tolerance=20)
    with pytest.raises(ValidationError) as exc:
        update_raw_material(conn, rm["id"], {"tolerance_unit": "percent"})
    assert exc.value.field == "tolerance"
    changed = update_raw_material(conn, rm["id"], {"tolerance_unit": "percent", "tolerance": "1,5"})
    assert (changed["tolerance_unit"], changed["tolerance"]) == ("percent", 1.5)


# -- R03-6 Gebinde/Stück -----------------------------------------------------------------

def test_unit_size_and_label_belong_together(conn):
    egg = make(conn, "Ei", unit_size_g=55, unit_label="Ei")
    assert (egg["unit_size_g"], egg["unit_label"]) == (55, "Ei")
    with pytest.raises(ValidationError):
        make(conn, "A", unit_size_g=55)
    with pytest.raises(ValidationError):
        make(conn, "B", unit_label="Sack")
    with pytest.raises(ValidationError):
        make(conn, "C", unit_size_g=0, unit_label="Sack")
    with pytest.raises(ValidationError):
        make(conn, "D", unit_size_g=-5, unit_label="Sack")


def test_unit_can_be_removed_together(conn):
    egg = make(conn, "Ei", unit_size_g=55, unit_label="Ei")
    plain = update_raw_material(conn, egg["id"], {"unit_size_g": None, "unit_label": None})
    assert plain["unit_size_g"] is None and plain["unit_label"] is None
    with pytest.raises(ValidationError):
        update_raw_material(conn, egg["id"], {"unit_size_g": 55})


# -- R03-7 Typwechsel ----------------------------------------------------------------------

def test_type_change_unused_needs_no_confirmation(conn):
    rm = make(conn, "Roggenschrot")
    assert update_raw_material(conn, rm["id"], {"type": "flour"})["type"] == "flour"


def test_type_change_used_needs_confirmation_and_names_affected_recipes(conn):
    rm = make(conn, "Roggenschrot", type="flour")
    for number in (10, 11):
        _, version = add_recipe(conn, number)
        add_item(conn, version, 1, rm["id"])
    with pytest.raises(ConflictError) as exc:
        update_raw_material(conn, rm["id"], {"type": "standard"})
    assert exc.value.code == "type_change_confirmation_required"
    assert exc.value.extra["affected_recipes"] == 2
    assert "2 Rezepte" in exc.value.message
    assert get_raw_material(conn, rm["id"])["type"] == "flour"      # nichts geändert

    done = update_raw_material(conn, rm["id"], {"type": "standard"}, confirm_type_change=True)
    assert done["type"] == "standard"


def test_other_changes_of_used_raw_material_need_no_confirmation(conn):
    rm = make(conn, "Roggenschrot", type="flour")
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm["id"])
    assert update_raw_material(conn, rm["id"], {"tolerance": 30})["tolerance"] == 30


# -- R03-8 Herkunft ---------------------------------------------------------------------------

def test_source_is_always_own_and_cannot_be_set_by_input(conn):
    rm = make(conn, "A", source="baeko", archived=True)
    assert rm["source"] == "own" and rm["archived"] is False
    assert update_raw_material(conn, rm["id"], {"source": "baeko"})["source"] == "own"


# -- R03-9/10 Archivieren und Wiederherstellen --------------------------------------------------

def test_archive_hides_from_list_and_keeps_recipes(conn):
    rm = make(conn, "Salz")
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm["id"])
    assert archive_raw_material(conn, rm["id"])["archived"] is True
    assert list_raw_materials(conn) == []
    assert [r["name"] for r in list_raw_materials(conn, include_archived=True)] == ["Salz"]
    assert usage(conn, rm["id"])["recipes"] == 1                  # Rezept bleibt unverändert
    with pytest.raises(ConflictError) as exc:
        archive_raw_material(conn, rm["id"])
    assert exc.value.code == "already_archived"


def test_restore(conn):
    rm = make(conn, "Salz")
    archive_raw_material(conn, rm["id"])
    assert restore_raw_material(conn, rm["id"])["archived"] is False
    with pytest.raises(ConflictError) as exc:
        restore_raw_material(conn, rm["id"])
    assert exc.value.code == "not_archived"


def test_restore_refused_when_active_raw_material_has_same_name(conn):
    old = make(conn, "Margarine")
    archive_raw_material(conn, old["id"])
    make(conn, "margarine")
    with pytest.raises(ConflictError) as exc:
        restore_raw_material(conn, old["id"])
    assert exc.value.code == "name_taken"
    assert get_raw_material(conn, old["id"])["archived"] is True


# -- R03-11 Löschen --------------------------------------------------------------------------------

def test_delete_unused(conn):
    rm = make(conn, "Salz")
    delete_raw_material(conn, rm["id"])
    with pytest.raises(NotFoundError):
        get_raw_material(conn, rm["id"])


def test_delete_used_refused_with_hint_to_archive(conn):
    rm = make(conn, "Salz")
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm["id"])
    with pytest.raises(ConflictError, match="wird in 1 Rezept verwendet – bitte archivieren") as exc:
        delete_raw_material(conn, rm["id"])
    assert exc.value.code == "in_use"
    assert get_raw_material(conn, rm["id"])["name"] == "Salz"


def test_delete_message_uses_plural(conn):
    rm = make(conn, "Salz")
    for number in (10, 11):
        _, version = add_recipe(conn, number)
        add_item(conn, version, 1, rm["id"])
    with pytest.raises(ConflictError, match="2 Rezepten"):
        delete_raw_material(conn, rm["id"])


def test_unknown_id(conn):
    for call in (lambda: get_raw_material(conn, 99), lambda: update_raw_material(conn, 99, {"name": "x"}),
                 lambda: archive_raw_material(conn, 99), lambda: restore_raw_material(conn, 99),
                 lambda: delete_raw_material(conn, 99)):
        with pytest.raises(NotFoundError):
            call()


# -- R03-12 Protokoll ----------------------------------------------------------------------------------

def test_every_change_is_logged(conn):
    rm = make(conn, "Salz", tolerance=5)
    update_raw_material(conn, rm["id"], {"tolerance": 8, "display_name": "Salz fein"})
    archive_raw_material(conn, rm["id"])
    restore_raw_material(conn, rm["id"])
    delete_raw_material(conn, rm["id"])

    rows = log_rows(conn)
    assert [r["action"] for r in rows] == ["create", "update", "archive", "restore", "delete"]
    assert all(r["source"] == "admin" and r["entity"] == "raw_material" and r["entity_id"] == rm["id"]
               for r in rows)
    created = json.loads(rows[0]["new_values"])
    assert created["name"] == "Salz" and created["source"] == "own" and rows[0]["old_values"] is None
    assert json.loads(rows[1]["old_values"]) == {"tolerance_value": 5, "display_name": None}
    assert json.loads(rows[1]["new_values"]) == {"tolerance_value": 8, "display_name": "Salz fein"}
    assert json.loads(rows[4]["old_values"])["name"] == "Salz" and rows[4]["new_values"] is None


def test_unchanged_update_writes_no_log_and_failed_change_writes_nothing(conn):
    rm = make(conn, "Salz")
    before = len(log_rows(conn))
    update_raw_material(conn, rm["id"], {"name": "Salz", "tolerance": 20})
    with pytest.raises(ConflictError):
        make(conn, "salz")
    assert len(log_rows(conn)) == before


def test_log_names_import_as_source_when_given(conn):
    create_raw_material(conn, {"name": "Salz", "tolerance": 5}, source="import")
    assert log_rows(conn)[0]["source"] == "import"


# -- Liste, Suche, Anzeige -----------------------------------------------------------------------------

def test_list_sorted_by_number_and_search(conn):
    make(conn, "Weizenmehl 550", number=20)
    make(conn, "Backmargarine A", number=5, display_name="Margarine")
    make(conn, "Äpfel getrocknet", number=12)
    assert [r["number"] for r in list_raw_materials(conn)] == [5, 12, 20]
    assert [r["name"] for r in list_raw_materials(conn, search="margarine")] == ["Backmargarine A"]
    assert [r["name"] for r in list_raw_materials(conn, search="MEHL")] == ["Weizenmehl 550"]
    assert [r["name"] for r in list_raw_materials(conn, search="äpfel")] == ["Äpfel getrocknet"]
    assert [r["name"] for r in list_raw_materials(conn, search="12")] == ["Äpfel getrocknet"]
    assert list_raw_materials(conn, search="gibtesnicht") == []
    assert len(list_raw_materials(conn, search="  ")) == 3


def test_get_includes_usage(conn):
    rm = make(conn, "Salz")
    assert get_raw_material(conn, rm["id"])["usage"] == {"recipes": 0, "orders": 0, "batch_items": 0,
                                                         "used": False}


# -- CSV-Export (M03-8) -------------------------------------------------------------------------------------

def test_csv_export_format(conn):
    make(conn, "Weizenmehl 550", number=1, type="flour", tolerance=20)
    egg = make(conn, "Ei; frisch", number=2, tolerance_unit="percent", tolerance="2,5",
               unit_size_g=55, unit_label="Ei", display_name="Eier")
    archive_raw_material(conn, egg["id"])
    data = build_csv(list_raw_materials(conn, include_archived=True))

    assert data.startswith(b"\xef\xbb\xbf")                       # UTF-8 mit BOM
    lines = data.decode("utf-8-sig").split("\r\n")
    assert lines[0] == ("Nummer;Name;Kurzname;Typ;Toleranz;Toleranzeinheit;Gebindegröße g;"
                        "Gebindebezeichnung;Herkunft;archiviert;geändert am")
    first = lines[1].split(";")
    assert first[:10] == ["1", "Weizenmehl 550", "", "Mehl", "20", "g", "", "", "eigen", "nein"]
    assert lines[2].startswith('2;"Ei; frisch";Eier;Standard;2,5;%;55;Ei;eigen;ja;')   # Semikolon im Namen in Anführungszeichen
    assert lines[3] == ""                                           # Datei endet mit Zeilenumbruch


def test_csv_export_of_empty_list_has_only_header():
    lines = build_csv([]).decode("utf-8-sig").split("\r\n")
    assert len(lines) == 2 and lines[1] == ""


# -- Verbindung je Anfrage (K03-1, Befund B6) ------------------------------------------------------------------

def test_parallel_writes_with_own_connections(db_path):
    """Mehrere gleichzeitige Speichervorgänge mit je eigener Verbindung stören sich nicht."""
    init_database(db_path).close()
    errors, results = [], []

    def work(index):
        local = connect(db_path)
        try:
            for step in range(5):
                results.append(create_raw_material(
                    local, {"name": f"Rohstoff {index}-{step}", "tolerance": 5})["number"])
        except Exception as exc:       # noqa: BLE001 – der Test soll jeden Fehler sehen
            errors.append(exc)
        finally:
            local.close()

    threads = [threading.Thread(target=work, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert sorted(results) == list(range(1, 31))                  # 30 Nummern, keine doppelt
    check = connect(db_path)
    assert check.execute("SELECT count(*) FROM raw_material").fetchone()[0] == 30
    assert check.execute("SELECT count(*) FROM change_log WHERE action = 'create'").fetchone()[0] == 30
    check.close()


def test_parallel_creation_of_same_name_allows_only_one(db_path):
    init_database(db_path).close()
    outcomes = []

    def work():
        local = connect(db_path)
        try:
            create_raw_material(local, {"name": "Margarine", "tolerance": 5})
            outcomes.append("ok")
        except ConflictError:
            outcomes.append("conflict")
        finally:
            local.close()

    threads = [threading.Thread(target=work) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["conflict"] * 4 + ["ok"]
