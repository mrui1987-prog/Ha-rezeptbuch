"""Tests: Verkaufsartikel, Stückliste, Vectron-Import, Export, Planungsfelder am Rezept (Modul 10, Teil P-A)."""

import io

import pytest
from openpyxl import Workbook, load_workbook

from app.articles import export, service, vectron
from app.errors import ConflictError, NotFoundError, ValidationError
from app.recipes import service as recipe_service
from conftest import add_raw_material, add_recipe, raises_db_error


def xlsx(rows, header=("Nummer", "Name", "Warengruppe", "Preis 1")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


VECTRON = [
    (1, "Offene Backwaren 7%%", 27, None),
    (3, "# Brot", 0, None),
    (4, "Bauernschnitten 500g", 1, "2,90"),
    (52, "Brötchen", 2, "0,75"),
    (106, None, 0, None),
    (197, "Zimtschnecke", 8, None),
    (198, "Zimtschnecke", 8, "1,95"),
    (287, "Kirschstreusel", 12, "1,95"),
    (365, "Schwarzwälder", 13, "2,70"),
    (532, "Apfelsaftschorle 0,5l", 16, "1,05"),
]


def article_id(conn, number):
    return conn.execute("SELECT id FROM sales_article WHERE register_no = ?", (number,)).fetchone()[0]


@pytest.fixture
def imported(conn):
    vectron.import_articles(conn, xlsx(VECTRON), mode="run")
    return conn


# -- Migration ------------------------------------------------------------------------

def test_line_checks_in_database(conn):
    rid, _ = add_recipe(conn, 1, "Hefeteig")
    aid = conn.execute("INSERT INTO sales_article (register_no, name) VALUES (5, 'X')").lastrowid
    with raises_db_error():   # Rezeptzeile ohne Menge
        conn.execute("INSERT INTO sales_article_line (article_id, position, kind, recipe_id) VALUES (?, 1, 'recipe', ?)",
                     (aid, rid))
    other, _ = add_recipe(conn, 2, "Anderes")
    pid = conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g, sort_order) "
                       "VALUES (?, 'Stück', 60, 1)", (other,)).lastrowid
    with raises_db_error("piece_weight_of_other_recipe"):
        conn.execute("INSERT INTO sales_article_line (article_id, position, kind, recipe_id, piece_weight_id) "
                     "VALUES (?, 1, 'recipe', ?, ?)", (aid, rid, pid))


def test_recipe_planning_columns(conn):
    rid, _ = add_recipe(conn, 1, "Kirschfüllung")
    rec = recipe_service.get_recipe(conn, rid)
    assert rec["preproduce"] is False and rec["weigh_surcharge_tenths"] is None


# -- Vectron-Import --------------------------------------------------------------------

def test_import_check_reports_without_writing(conn):
    report = vectron.import_articles(conn, xlsx(VECTRON), mode="check")
    assert report["imported"] is False
    assert report["counts"]["new"] == 6           # WG 1, 2, 8, 8, 12, 13 – nicht 16 und 27
    assert report["counts"]["skipped_headings"] == 1 and report["counts"]["skipped_group_0"] == 0
    assert {g["group"]: g["selected"] for g in report["groups"]}[16] is False
    assert report["same_names"] == [{"name": "Zimtschnecke", "numbers": [197, 198]}]
    assert conn.execute("SELECT count(*) FROM sales_article").fetchone()[0] == 0


def test_import_run_defaults_and_names(imported):
    conn = imported
    rows = {r["register_no"]: r for r in conn.execute("SELECT * FROM sales_article")}
    assert set(rows) == {4, 52, 197, 198, 287, 365}
    assert rows[287]["pieces_per_whole"] == 12 and rows[365]["pieces_per_whole"] == 14
    assert rows[52]["pieces_per_whole"] is None
    assert rows[4]["in_register"] == 1 and rows[4]["plan_enabled"] == 1


def test_import_more_groups_and_percent(conn):
    vectron.import_articles(conn, xlsx(VECTRON), mode="run", groups="27,16")
    names = {r["register_no"]: r["name"] for r in conn.execute("SELECT * FROM sales_article")}
    assert names == {1: "Offene Backwaren 7%", 532: "Apfelsaftschorle 0,5l"}


def test_reimport_rename_missing_return(imported):
    conn = imported
    changed = [r for r in VECTRON if r[0] != 52]
    changed = [(n, "Kirschstreusel Blech" if n == 287 else name, g, p) for n, name, g, p in changed]
    report = vectron.import_articles(conn, xlsx(changed), mode="run")
    assert report["counts"]["changed"] == 1 and report["counts"]["missing"] == 1
    row = conn.execute("SELECT * FROM sales_article WHERE register_no = 52").fetchone()
    assert row["in_register"] == 0                 # nie gelöscht
    assert conn.execute("SELECT name FROM sales_article WHERE register_no = 287").fetchone()[0] == "Kirschstreusel Blech"
    report = vectron.import_articles(conn, xlsx(VECTRON), mode="run")
    assert report["counts"]["returned"] == 1
    assert conn.execute("SELECT in_register FROM sales_article WHERE register_no = 52").fetchone()[0] == 1


def test_import_duplicate_numbers_rejected(conn):
    with pytest.raises(ValidationError) as exc:
        vectron.import_articles(conn, xlsx([(4, "A", 1, None), (4, "B", 1, None)]), mode="run")
    assert exc.value.code == "duplicate_numbers"
    assert conn.execute("SELECT count(*) FROM sales_article").fetchone()[0] == 0


def test_import_bad_files(conn):
    with pytest.raises(ValidationError) as exc:
        vectron.import_articles(conn, b"kein excel", mode="check")
    assert exc.value.code == "not_xlsx"
    with pytest.raises(ValidationError) as exc:
        vectron.import_articles(conn, xlsx([(1, "A")], header=("Nr", "Bezeichnung")), mode="check")
    assert exc.value.code == "columns_missing"


# -- Artikel und Stückliste --------------------------------------------------------------

def test_update_article_fields(imported):
    conn = imported
    aid = article_id(conn, 197)
    art = service.update_article(conn, aid, {"plan_enabled": False, "note": "Leiche", "pieces_per_whole": ""})
    assert art["plan_enabled"] is False and art["note"] == "Leiche" and art["pieces_per_whole"] is None
    with pytest.raises(ValidationError):
        service.update_article(conn, aid, {"pieces_per_whole": 0})
    with pytest.raises(ValidationError):
        service.update_article(conn, aid, {"note": "=SUMME(A1)"})
    with pytest.raises(NotFoundError):
        service.update_article(conn, 99999, {})


def test_lines_recipe_raw_and_sums(imported):
    conn = imported
    hefe, _ = add_recipe(conn, 10, "Hefeteig")
    fuell, _ = add_recipe(conn, 11, "Kirschfüllung")
    pid = conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g, sort_order) "
                       "VALUES (?, 'Kuchen', 1200, 1)", (hefe,)).lastrowid
    zucker = add_raw_material(conn, 1, "Puderzucker")
    deko = add_raw_material(conn, 2, "Deko-Kirsche", unit_size_g=5, unit_label="Stück")
    aid = article_id(conn, 287)
    art = service.set_lines(conn, aid, [
        {"kind": "recipe", "recipe_id": hefe, "piece_weight_id": pid},
        {"kind": "recipe", "recipe_id": fuell, "amount_g": "1500"},
        {"kind": "raw", "raw_material_id": zucker, "amount_g": 20},
        {"kind": "raw", "raw_material_id": deko, "amount_pieces": 12},
    ])
    assert [ln["grams"] for ln in art["lines"]] == [1200, 1500, 20, 60]
    assert art["sum_g"] == 2780 and art["sum_complete"] is True and art["per"] == "Ganzes"
    assert art["lines"][0]["piece_weight_label"] == "Kuchen"
    # Stückgewicht, das in einer Stückliste steht, lässt sich nicht löschen
    with pytest.raises(ConflictError) as exc:
        recipe_service.set_piece_weights(conn, hefe, [])
    assert exc.value.code == "piece_weight_in_articles"
    # Kopieren
    other = article_id(conn, 365)
    copied = service.copy_lines(conn, other, aid)
    assert len(copied["lines"]) == 4
    listed = {a["register_no"]: a for a in service.list_articles(conn)}
    assert listed[287]["line_count"] == 4 and listed[52]["line_count"] == 0
    assert [a["register_no"] for a in service.list_articles(conn, without_lines=True)] == [4, 52, 197, 198]
    assert [a["register_no"] for a in service.list_articles(conn, search="kirsch")] == [287]
    assert [a["register_no"] for a in service.list_articles(conn, search="365")] == [365]


def test_line_validation(imported):
    conn = imported
    aid = article_id(conn, 52)
    rid, _ = add_recipe(conn, 10, "Brötchenteig")
    other, _ = add_recipe(conn, 11, "Anderes")
    pid = conn.execute("INSERT INTO recipe_piece_weight (recipe_id, label, weight_g, sort_order) "
                       "VALUES (?, 'Stück', 60, 1)", (other,)).lastrowid
    raw = add_raw_material(conn, 1, "Salz")
    bad = [
        [{"kind": "artikel", "article_id": 1}],
        [{"kind": "recipe", "recipe_id": 999, "amount_g": 60}],
        [{"kind": "recipe", "recipe_id": rid}],
        [{"kind": "recipe", "recipe_id": rid, "piece_weight_id": pid}],
        [{"kind": "raw", "raw_material_id": raw}],
        [{"kind": "raw", "raw_material_id": raw, "amount_g": 5, "amount_pieces": 1}],
        [{"kind": "recipe", "recipe_id": rid, "amount_g": 0}],
    ]
    for lines in bad:
        with pytest.raises(ValidationError):
            service.set_lines(conn, aid, lines)
    assert service.get_article(conn, aid)["lines"] == []


def test_archived_reference_kept_but_not_added(imported):
    conn = imported
    aid = article_id(conn, 52)
    rid, _ = add_recipe(conn, 10, "Brötchenteig")
    service.set_lines(conn, aid, [{"kind": "recipe", "recipe_id": rid, "amount_g": 60}])
    conn.execute("UPDATE recipe SET archived = 1 WHERE id = ?", (rid,))
    art = service.get_article(conn, aid)
    assert art["warnings"] == ["Zeile 1: Rezept archiviert"]
    service.set_lines(conn, aid, [{"kind": "recipe", "recipe_id": rid, "amount_g": 65}])   # bleibt erlaubt
    other = article_id(conn, 4)
    with pytest.raises(ValidationError) as exc:
        service.set_lines(conn, other, [{"kind": "recipe", "recipe_id": rid, "amount_g": 60}])
    assert exc.value.code == "recipe_archived"
    assert [a["has_warning"] for a in service.list_articles(conn, search="Brötchen")] == [True]


def test_bulk_actions(imported):
    conn = imported
    ids = [article_id(conn, n) for n in (197, 198)]
    assert service.bulk(conn, {"ids": ids, "action": "plan_disable"}) == {"changed": 2}
    assert service.bulk(conn, {"ids": ids, "action": "plan_disable"}) == {"changed": 0}
    assert [a["register_no"] for a in service.list_articles(conn, not_planned=True)] == [197, 198]
    service.bulk(conn, {"ids": ids, "action": "pieces_per_whole", "value": 4})
    assert {a["pieces_per_whole"] for a in service.list_articles(conn, not_planned=True)} == {4}
    with pytest.raises(ValidationError):
        service.bulk(conn, {"ids": [], "action": "plan_enable"})


def test_export_workbook(imported):
    conn = imported
    rid, _ = add_recipe(conn, 10, "Hefeteig")
    service.set_lines(conn, article_id(conn, 287), [{"kind": "recipe", "recipe_id": rid, "amount_g": 1200}])
    wb = load_workbook(io.BytesIO(export.build_workbook(conn)))
    assert wb.sheetnames == ["Artikel", "Stückliste"]
    lines = list(wb["Stückliste"].iter_rows(min_row=2, values_only=True))
    assert lines[0][:7] == (287, "Kirschstreusel", 1, "Rezept", 10, "Hefeteig", 1200)


# -- Planungsfelder am Rezept ----------------------------------------------------------------

def test_recipe_planning(conn):
    rid, _ = add_recipe(conn, 1, "Kirschfüllung")
    rev = recipe_service.get_recipe(conn, rid)["revision"]
    rec = recipe_service.set_planning(conn, rid, {"preproduce": True, "weigh_surcharge": "1,2"})
    assert rec["preproduce"] is True and rec["weigh_surcharge_tenths"] == 12 and rec["revision"] == rev
    rec = recipe_service.set_planning(conn, rid, {"weigh_surcharge": ""})
    assert rec["weigh_surcharge_tenths"] is None and rec["preproduce"] is True
    for bad in ("1,25", "abc", "25", -1):
        with pytest.raises(ValidationError):
            recipe_service.set_planning(conn, rid, {"weigh_surcharge": bad})
    with pytest.raises(ValidationError):
        recipe_service.set_planning(conn, rid, {"preproduce": "ja"})


# -- H1: P-B-Tabellen in Migration 0010 (Michael 21.11.2026, 07:08) ---------------------

def test_upgrade_keeps_stock_movements(tmp_path):
    import shutil

    from app.db import MIGRATIONS_DIR, init_database

    old_dir = tmp_path / "bis9"
    old_dir.mkdir()
    for f in MIGRATIONS_DIR.glob("*.sql"):
        if int(f.name[:4]) <= 9:
            shutil.copy(f, old_dir / f.name)
    db = tmp_path / "alt.db"
    conn = init_database(db, migrations_dir=old_dir)
    rm = add_raw_material(conn, 7, "Butter")
    conn.execute("INSERT INTO stock_movement (raw_material_id, kind, delta_g, stock_after_g, note) "
                 "VALUES (?, 'receipt', 5000, 5000, 'alt')", (rm,))
    conn.close()
    conn = init_database(db)
    rows = [tuple(r) for r in conn.execute("SELECT raw_material_id, kind, delta_g, note FROM stock_movement")]
    assert rows == [(rm, "receipt", 5000, "alt")]
    conn.execute("INSERT INTO stock_movement (raw_material_id, kind, delta_g, stock_after_g) "
                 "VALUES (?, 'planner', -200, 4800)", (rm,))
    conn.execute("INSERT INTO stock_movement (raw_material_id, kind, delta_g, stock_after_g) "
                 "VALUES (?, 'planner_return', 200, 5000)", (rm,))
    with raises_db_error():
        conn.execute("INSERT INTO stock_movement (raw_material_id, kind) VALUES (?, 'unbekannt')", (rm,))
    idx = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'stock_movement'")}
    assert {"idx_stock_movement_raw_material", "idx_stock_movement_batch"} <= idx
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_plan_tables_checks(conn):
    aid = conn.execute("INSERT INTO sales_article (register_no, name) VALUES (5, 'X')").lastrowid
    pid = conn.execute("INSERT INTO sales_plan (plan_date) VALUES ('2026-11-27')").lastrowid
    conn.execute("INSERT INTO sales_plan_line (plan_id, article_id, order_no, pieces) VALUES (?, ?, 1, 20)", (pid, aid))
    conn.execute("INSERT INTO sales_plan_line (plan_id, article_id, order_no, wholes) VALUES (?, ?, 2, 2)", (pid, aid))
    with raises_db_error():   # ohne Menge
        conn.execute("INSERT INTO sales_plan_line (plan_id, article_id, order_no) VALUES (?, ?, 3)", (pid, aid))
    with raises_db_error():   # gleicher Artikel, gleicher Auftrag
        conn.execute("INSERT INTO sales_plan_line (plan_id, article_id, order_no, pieces) VALUES (?, ?, 1, 5)", (pid, aid))
    with raises_db_error():   # kein Datum
        conn.execute("INSERT INTO sales_plan (plan_date) VALUES ('morgen')")
    with raises_db_error():
        conn.execute("INSERT INTO plan_run (dates, status) VALUES ('[]', 'irgendwas')")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(production_order)")}
    assert {"surcharge_tenths", "surcharge_g", "carryover_of_order_id"} <= cols


# -- H2: Planungsfelder in Rezept-Export und Vorlagen-Import --------------------------

def _planning_recipes(conn):
    a = recipe_service.create_recipe(conn, {"name": "Kirschfüllung"})
    b = recipe_service.create_recipe(conn, {"name": "Hefeteig"})
    recipe_service.set_planning(conn, a["id"], {"preproduce": True, "weigh_surcharge": "1,2"})
    recipe_service.set_planning(conn, b["id"], {"weigh_surcharge": "2"})
    return a["id"], b["id"]


def test_export_has_planning_columns(conn):
    from app.exports import build_workbook

    _planning_recipes(conn)
    ws = load_workbook(io.BytesIO(build_workbook(conn)))["Rezepte"]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    assert rows[0][-2].startswith("Darf vorproduziert werden") and rows[0][-1].startswith("Abwiegezuschlag")
    by_name = {r[2]: r[-2:] for r in rows[1:]}
    assert by_name == {"Kirschfüllung": ["ja", "1,2"], "Hefeteig": ["nein", "2"]}


def test_planning_roundtrip_and_update(conn, tmp_path):
    from app.db import init_database
    from app.exports import build_workbook
    from app.imports.recipe_template import import_recipe_template

    a, b = _planning_recipes(conn)
    data = build_workbook(conn)
    target = init_database(tmp_path / "leer.db")
    assert import_recipe_template(target, data, mode="run")["ok"]
    got = {r["name"]: (r["preproduce"], r["weigh_surcharge_tenths"])
           for r in (recipe_service.get_recipe(target, x["id"])
                     for x in recipe_service.list_recipes(target, include_locked=True))}
    assert got == {"Kirschfüllung": (True, 12), "Hefeteig": (False, 20)}
    target.close()

    # gleiche Datei in dieselbe Datenbank: nichts geändert
    report = import_recipe_template(conn, data, mode="run")
    assert report["ok"] and not any("Planung" in h["message"] for h in report["hints"])

    # Datei mit geänderten Werten: Planung geändert, ohne neue Version
    wb = load_workbook(io.BytesIO(data))
    ws = wb["Rezepte"]
    for row in ws.iter_rows(min_row=2):
        if row[2].value == "Hefeteig":
            row[-2].value, row[-1].value = "ja", 0.5
        if row[2].value == "Kirschfüllung":
            row[-2].value, row[-1].value = None, None            # leer = unverändert
    out = io.BytesIO()
    wb.save(out)
    version_before = recipe_service.get_recipe(conn, b)["version_no"]
    report = import_recipe_template(conn, out.getvalue(), mode="run")
    assert report["ok"] and any("Planung" in h["message"] for h in report["hints"])
    hb = recipe_service.get_recipe(conn, b)
    assert (hb["preproduce"], hb["weigh_surcharge_tenths"], hb["version_no"]) == (True, 5, version_before)
    ha = recipe_service.get_recipe(conn, a)
    assert (ha["preproduce"], ha["weigh_surcharge_tenths"]) == (True, 12)


def test_planning_import_errors(conn):
    from app.exports import build_workbook
    from app.imports.recipe_template import import_recipe_template

    _planning_recipes(conn)
    wb = load_workbook(io.BytesIO(build_workbook(conn)))
    ws = wb["Rezepte"]
    ws.cell(row=2, column=ws.max_column - 1).value = "vielleicht"
    ws.cell(row=3, column=ws.max_column).value = "1,25"
    out = io.BytesIO()
    wb.save(out)
    report = import_recipe_template(conn, out.getvalue(), mode="check")
    assert not report["ok"]
    texts = " ".join(e["message"] for e in report["errors"])
    assert "„ja“ oder „nein“" in texts and "Nachkommastelle" in texts


def test_old_file_without_planning_columns_keeps_values(conn):
    from app.exports import build_workbook
    from app.imports.recipe_template import import_recipe_template

    a, _ = _planning_recipes(conn)
    wb = load_workbook(io.BytesIO(build_workbook(conn)))
    ws = wb["Rezepte"]
    ws.delete_cols(ws.max_column - 1, 2)
    out = io.BytesIO()
    wb.save(out)
    assert import_recipe_template(conn, out.getvalue(), mode="run")["ok"]
    r = recipe_service.get_recipe(conn, a)
    assert (r["preproduce"], r["weigh_surcharge_tenths"]) == (True, 12)


def test_file_without_usable_articles_changes_nothing(imported):
    """Falsche Datei (Michael 24.11.2026): 0 Artikel → Abbruch, niemand wird „nicht mehr in der Kasse“."""
    before = imported.execute("SELECT count(*) FROM sales_article WHERE in_register = 1").fetchone()[0]
    with pytest.raises(ValidationError) as exc:
        vectron.import_articles(imported, xlsx([(1, "Taste A", "Funktion", "x")], header=("Nummer", "Name", "Funktion", "Code")), mode="run")
    assert exc.value.code == "no_articles"
    assert imported.execute("SELECT count(*) FROM sales_article WHERE in_register = 1").fetchone()[0] == before
