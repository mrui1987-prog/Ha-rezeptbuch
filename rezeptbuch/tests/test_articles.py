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
