"""Tests: Tabellen, Schlüssel und Prüfregeln (Modul 02, docs/datenmodell.md Abschnitt 4)."""

import pytest

from conftest import add_item, add_order, add_raw_material, add_recipe, add_version, raises_db_error


# --- Rohstoffe --------------------------------------------------------------

def test_raw_material_number_unique_and_positive(conn):
    add_raw_material(conn, 100)
    with raises_db_error("UNIQUE"):
        add_raw_material(conn, 100, name="Doppelt")
    with raises_db_error("CHECK"):
        add_raw_material(conn, 0)


def test_raw_material_only_standard_or_flour(conn):
    add_raw_material(conn, 1, type_="flour")
    with raises_db_error("CHECK"):
        add_raw_material(conn, 2, type_="text")  # Rohstofftyp „Text“ entfällt (K3)


def test_one_tolerance_value_in_gram_or_tenth_percent(conn):
    add_raw_material(conn, 1, tolerance_unit="percent", tolerance_value=25)  # 2,5 %
    add_raw_material(conn, 2, tolerance_unit="g", tolerance_value=0)  # Sollhandzugabe
    with raises_db_error("CHECK"):
        add_raw_material(conn, 3, tolerance_unit="percent", tolerance_value=1001)
    with raises_db_error("CHECK"):
        add_raw_material(conn, 4, tolerance_value=-1)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(raw_material)")}
    assert "tolerance_value" in columns
    assert not {"tolerance_minus", "tolerance_plus"} & columns  # K1


def test_unit_size_needs_label(conn):
    add_raw_material(conn, 1, name="Ei", unit_size_g=55, unit_label="Ei")
    with raises_db_error("CHECK"):
        add_raw_material(conn, 2, unit_size_g=25000)
    with raises_db_error("CHECK"):
        add_raw_material(conn, 3, unit_label="Sack")


def test_used_raw_material_cannot_be_deleted(conn):
    used = add_raw_material(conn, 1)
    unused = add_raw_material(conn, 2)
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, used)
    with raises_db_error("FOREIGN KEY"):
        conn.execute("DELETE FROM raw_material WHERE id = ?", (used,))
    conn.execute("DELETE FROM raw_material WHERE id = ?", (unused,))
    conn.execute("UPDATE raw_material SET archived = 1 WHERE id = ?", (used,))  # M02-9


# --- Rezepte ----------------------------------------------------------------

def test_recipe_number_unique(conn):
    add_recipe(conn, 10)
    with raises_db_error("UNIQUE"):
        add_recipe(conn, 10)


def test_version_numbers_unique_per_recipe(conn):
    recipe, _ = add_recipe(conn, 10)
    add_version(conn, recipe, 2)
    with raises_db_error("UNIQUE"):
        add_version(conn, recipe, 2)


def test_note_display_start_or_end(conn):
    recipe, version = add_recipe(conn, 10)
    row = conn.execute("SELECT note_display FROM recipe_version WHERE id = ?", (version,)).fetchone()
    assert row[0] == "end"
    conn.execute("UPDATE recipe_version SET note = 'Mit Mohn bestreuen', note_display = 'start' WHERE id = ?",
                 (version,))
    with raises_db_error("CHECK"):
        conn.execute("UPDATE recipe_version SET note_display = 'mitte' WHERE id = ?", (version,))


def test_current_version_must_belong_to_recipe(conn):
    recipe_a, version_a = add_recipe(conn, 10)
    recipe_b, version_b = add_recipe(conn, 20)
    with raises_db_error("gehört nicht"):
        conn.execute("UPDATE recipe SET current_version_id = ? WHERE id = ?", (version_b, recipe_a))


def test_item_is_raw_material_or_sub_recipe(conn):
    rm = add_raw_material(conn, 1)
    sub, _ = add_recipe(conn, 99, "Sauerteig")
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm)
    add_item(conn, version, 2, sub_recipe_id=sub, amount_g=2000)
    with raises_db_error("CHECK"):
        conn.execute(
            "INSERT INTO recipe_item (recipe_version_id, position, item_type, raw_material_id, sub_recipe_id, amount_g) "
            "VALUES (?, 3, 'raw_material', ?, ?, 100)", (version, rm, sub))
    with raises_db_error("CHECK"):
        conn.execute(
            "INSERT INTO recipe_item (recipe_version_id, position, item_type, amount_g) "
            "VALUES (?, 4, 'text', 100)", (version,))  # keine Textzeilen (K3)


def test_item_amount_zero_means_hand_addition(conn):
    """Zutat ohne Menge wird mit 0 g angelegt: Handzugabe nach Bedarf (M02-15)."""
    vanille = add_raw_material(conn, 1, name="Vanille/Zitrone")
    sub, _ = add_recipe(conn, 99, "Sauerteig")
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, vanille, amount_g=0)
    with raises_db_error("CHECK"):
        add_item(conn, version, 2, vanille, amount_g=-5)
    with raises_db_error("CHECK"):
        add_item(conn, version, 3, sub_recipe_id=sub, amount_g=0)  # Unterrezept braucht Menge


def test_item_review_marker(conn):
    """Beim Import umgerechnete Mengen werden mit „*“ markiert (M02-16)."""
    oil = add_raw_material(conn, 1, name="Öl")
    _, version = add_recipe(conn, 10)
    item = add_item(conn, version, 1, oil, amount_g=368)
    assert conn.execute("SELECT needs_review FROM recipe_item WHERE id = ?", (item,)).fetchone()[0] == 0
    conn.execute("UPDATE recipe_item SET needs_review = 1 WHERE id = ?", (item,))
    with raises_db_error("CHECK"):
        conn.execute("UPDATE recipe_item SET needs_review = 2 WHERE id = ?", (item,))


def test_item_tolerance_override_needs_unit_and_value(conn):
    rm = add_raw_material(conn, 1)
    _, version = add_recipe(conn, 10)
    conn.execute(
        "INSERT INTO recipe_item (recipe_version_id, position, item_type, raw_material_id, amount_g, "
        "tolerance_unit, tolerance_value) VALUES (?, 1, 'raw_material', ?, 500, 'g', 5)", (version, rm))
    with raises_db_error("CHECK"):
        conn.execute(
            "INSERT INTO recipe_item (recipe_version_id, position, item_type, raw_material_id, amount_g, "
            "tolerance_value) VALUES (?, 2, 'raw_material', ?, 500, 5)", (version, rm))


def test_positions_unique_per_version(conn):
    rm = add_raw_material(conn, 1)
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm)
    with raises_db_error("UNIQUE"):
        add_item(conn, version, 1, rm)


def test_recipe_cannot_contain_itself(conn):
    recipe, version = add_recipe(conn, 10)
    with raises_db_error("selbst"):
        add_item(conn, version, 1, sub_recipe_id=recipe)


def test_step_must_exist(conn):
    rm = add_raw_material(conn, 1)
    _, version = add_recipe(conn, 10)
    conn.execute("INSERT INTO recipe_version_step (recipe_version_id, step_no, name) VALUES (?, 1, 'Vorteig')",
                 (version,))
    conn.execute("INSERT INTO recipe_item (recipe_version_id, position, item_type, raw_material_id, amount_g, step_no) "
                 "VALUES (?, 1, 'raw_material', ?, 100, 1)", (version, rm))
    with raises_db_error("FOREIGN KEY"):
        conn.execute("INSERT INTO recipe_item (recipe_version_id, position, item_type, raw_material_id, amount_g, "
                     "step_no) VALUES (?, 2, 'raw_material', ?, 100, 2)", (version, rm))


def test_unused_recipe_can_be_deleted_completely(conn):
    rm = add_raw_material(conn, 1)
    recipe, version = add_recipe(conn, 10)
    conn.execute("INSERT INTO recipe_version_step (recipe_version_id, step_no, name) VALUES (?, 1, 'Teig')",
                 (version,))
    conn.execute("INSERT INTO recipe_item (recipe_version_id, position, item_type, raw_material_id, amount_g, step_no) "
                 "VALUES (?, 1, 'raw_material', ?, 100, 1)", (version, rm))
    conn.execute("INSERT INTO recipe_batch_size (recipe_id, label, kind, value) VALUES (?, 'Groß', 'weight', 25000)",
                 (recipe,))
    conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g) VALUES (?, 'Stück', 65)", (recipe,))
    conn.execute("DELETE FROM recipe WHERE id = ?", (recipe,))
    for table in ("recipe_version", "recipe_item", "recipe_version_step", "recipe_batch_size", "recipe_piece_weight"):
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_recipe_used_as_sub_recipe_cannot_be_deleted(conn):
    sub, _ = add_recipe(conn, 99, "Sauerteig")
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, sub_recipe_id=sub)
    with raises_db_error("FOREIGN KEY"):
        conn.execute("DELETE FROM recipe WHERE id = ?", (sub,))


def test_several_piece_weights_per_recipe(conn):
    recipe, _ = add_recipe(conn, 10, "Brötchenteig")
    for i, (label, weight) in enumerate([("Stück", 65), ("Ballen", 1550), ("Ballen Hörnchen", 2800),
                                         ("Hörnchen", 93), ("Kleines Flitt", 400), ("Große Flitt", 600)]):
        conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g, sort_order) VALUES (?, ?, ?, ?)",
                     (recipe, label, weight, i))
    assert conn.execute("SELECT count(*) FROM recipe_piece_weight WHERE recipe_id = ?", (recipe,)).fetchone()[0] == 6
    with raises_db_error("UNIQUE"):
        conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g) VALUES (?, 'Stück', 70)", (recipe,))
    with raises_db_error("CHECK"):
        conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g) VALUES (?, 'Null', 0)", (recipe,))


def test_batch_sizes_weight_or_pieces(conn):
    recipe, _ = add_recipe(conn, 10)
    other, _ = add_recipe(conn, 20)
    piece = conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g) VALUES (?, 'Stück', 65)",
                         (recipe,)).lastrowid
    foreign = conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g) VALUES (?, 'Stück', 80)",
                           (other,)).lastrowid
    conn.execute("INSERT INTO recipe_batch_size (recipe_id, label, kind, value) VALUES (?, 'Großer Teig', 'weight', 25000)",
                 (recipe,))
    conn.execute("INSERT INTO recipe_batch_size (recipe_id, label, kind, value, piece_weight_id) "
                 "VALUES (?, '60 Stück', 'pieces', 60, ?)", (recipe, piece))
    with raises_db_error("CHECK"):  # Stückzahl ohne Stückgewicht
        conn.execute("INSERT INTO recipe_batch_size (recipe_id, label, kind, value) VALUES (?, 'x', 'pieces', 60)",
                     (recipe,))
    with raises_db_error("nicht zu diesem Rezept"):
        conn.execute("INSERT INTO recipe_batch_size (recipe_id, label, kind, value, piece_weight_id) "
                     "VALUES (?, 'y', 'pieces', 60, ?)", (recipe, foreign))
    with raises_db_error("CHECK"):
        conn.execute("INSERT INTO recipe_batch_size (recipe_id, label, kind, value) VALUES (?, 'x', 'liter', 1)",
                     (recipe,))


def test_knead_times_slow_and_fast(conn):
    _, version = add_recipe(conn, 10)
    conn.execute("UPDATE recipe_version SET knead_slow_min = 5, knead_fast_min = 6 WHERE id = ?", (version,))
    with raises_db_error("CHECK"):
        conn.execute("UPDATE recipe_version SET knead_fast_min = -1 WHERE id = ?", (version,))


def test_order_with_several_piece_weights(conn):
    recipe, _ = add_recipe(conn, 10, "Brötchenteig")
    stueck = conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g) VALUES (?, 'Stück', 65)",
                          (recipe,)).lastrowid
    flitt = conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g) VALUES (?, 'Kleines Flitt', 400)",
                         (recipe,)).lastrowid
    # 100 Stück à 65 g + 5 kleine Flitt à 400 g = 8 500 g Gesamtteig
    order = add_order(conn, recipe, basis_type="pieces", basis_value=8500, basis_input_unit="pcs")
    conn.execute("INSERT INTO order_piece (order_id, piece_weight_id, label, weight_g, piece_count) "
                 "VALUES (?, ?, 'Stück', 65, 100)", (order, stueck))
    conn.execute("INSERT INTO order_piece (order_id, piece_weight_id, label, weight_g, piece_count) "
                 "VALUES (?, ?, 'Kleines Flitt', 400, 5)", (order, flitt))
    total = conn.execute("SELECT sum(weight_g * piece_count) FROM order_piece WHERE order_id = ?", (order,)).fetchone()[0]
    assert total == 8500
    # Stückgewicht im Rezept später gelöscht: Auftrag behält Bezeichnung und Gewicht
    conn.execute("DELETE FROM recipe_piece_weight WHERE id = ?", (flitt,))
    row = conn.execute("SELECT piece_weight_id, label, weight_g FROM order_piece WHERE label = 'Kleines Flitt'").fetchone()
    assert tuple(row) == (None, "Kleines Flitt", 400)
    with raises_db_error("CHECK"):
        conn.execute("INSERT INTO order_piece (order_id, label, weight_g, piece_count) VALUES (?, 'x', 65, 0)", (order,))


# --- Aufträge ---------------------------------------------------------------

@pytest.mark.parametrize("basis_type", ["total", "pieces", "batch_size", "flour_total"])
def test_order_basis_types(conn, basis_type):
    recipe, _ = add_recipe(conn, 10)
    add_order(conn, recipe, basis_type=basis_type)


def test_lead_raw_material_needs_raw_material(conn):
    rm = add_raw_material(conn, 1, name="Quark")
    recipe, _ = add_recipe(conn, 10)
    add_order(conn, recipe, basis_type="raw_material", basis_value=7500, basis_raw_material_id=rm)
    with raises_db_error("CHECK"):
        add_order(conn, recipe, basis_type="raw_material", basis_value=7500)
    with raises_db_error("CHECK"):
        add_order(conn, recipe, basis_type="total", basis_raw_material_id=rm)


def test_liter_input_only_for_lead_raw_material(conn):
    water = add_raw_material(conn, 1, name="Wasser")
    recipe, _ = add_recipe(conn, 10)
    # 10 Liter Wasser = 10 000 g (M02-1e)
    add_order(conn, recipe, basis_type="raw_material", basis_value=10000,
              basis_raw_material_id=water, basis_input_unit="l")
    with raises_db_error("CHECK"):
        add_order(conn, recipe, basis_type="total", basis_input_unit="l")


def test_order_dough_count_at_least_one(conn):
    recipe, _ = add_recipe(conn, 10)
    with raises_db_error("CHECK"):
        add_order(conn, recipe, dough_count=0)


def test_started_order_needs_version(conn):
    recipe, _ = add_recipe(conn, 10)
    with raises_db_error("CHECK"):
        add_order(conn, recipe, status="in_progress")


def test_sub_order_needs_parent_position(conn):
    recipe, _ = add_recipe(conn, 10)
    parent = add_order(conn, recipe)
    add_order(conn, recipe, parent_order_id=parent, parent_item_position=2)
    with raises_db_error("CHECK"):
        add_order(conn, recipe, parent_order_id=parent)


# --- Änderungsprotokoll -----------------------------------------------------

def test_change_log_sources_and_json(conn):
    conn.execute("INSERT INTO change_log (source, entity, entity_id, action, old_values, new_values) "
                 "VALUES ('admin', 'raw_material', 1, 'update', '{\"name\": \"alt\"}', '{\"name\": \"neu\"}')")
    with raises_db_error("CHECK"):
        conn.execute("INSERT INTO change_log (source, entity, entity_id, action) VALUES ('michael', 'x', 1, 'update')")
    with raises_db_error("CHECK"):
        conn.execute("INSERT INTO change_log (source, entity, entity_id, action, new_values) "
                     "VALUES ('admin', 'x', 1, 'update', 'kein json')")
