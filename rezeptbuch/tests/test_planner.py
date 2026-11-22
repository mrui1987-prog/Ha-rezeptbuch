"""Planer P-B (docs/planer.md 6–11): Plan, Rechenweg, Vorschau, Anlegen, Übertrag, Abbuchen."""

from __future__ import annotations

from fractions import Fraction

import pytest

from app.errors import ConflictError, ValidationError
from app.planner import service as plan
from app.production.orders import get_order
from app.recipes import service as rs
from conftest import add_raw_material

FR, SA = "2026-11-27", "2026-11-28"


def recipe(conn, number, name, raw_id, *, limit=None, pieces=(), preproduce=False, surcharge=None):
    r = rs.create_recipe(conn, {"number": number, "name": name,
                                "items": [{"type": "raw_material", "raw_material_id": raw_id, "amount_g": 1000}]})
    if pieces:
        rs.set_piece_weights(conn, r["id"], [{"label": l, "weight_g": g} for l, g in pieces],
                             revision=rs.get_recipe(conn, r["id"])["revision"])
    if limit:
        rs.set_batch_sizes(conn, r["id"], [{"label": "voll", "kind": "weight", "value": limit, "is_limit": True}],
                           revision=rs.get_recipe(conn, r["id"])["revision"])
    rs.set_planning(conn, r["id"], {"preproduce": preproduce, "weigh_surcharge": surcharge})
    rs.unlock_recipe(conn, r["id"], confirm=True)
    return r["id"]


def article(conn, no, name, lines, per_whole=None):
    aid = conn.execute("INSERT INTO sales_article (register_no, name, register_group, pieces_per_whole) "
                       "VALUES (?, ?, 12, ?)", (no, name, per_whole)).lastrowid
    for i, ln in enumerate(lines, start=1):
        conn.execute("INSERT INTO sales_article_line (article_id, position, kind, recipe_id, piece_weight_id, "
                     "raw_material_id, amount_g, amount_pieces) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (aid, i, ln.get("kind", "recipe"), ln.get("recipe_id"), ln.get("piece_weight_id"),
                      ln.get("raw_material_id"), ln.get("amount_g"), ln.get("amount_pieces")))
    return aid


@pytest.fixture
def world(conn):
    mehl = add_raw_material(conn, 1, "Mehl")
    butter = add_raw_material(conn, 2, "Butter", unit_size_g=250, unit_label="Stück")
    conn.execute("UPDATE raw_material SET stock_g = 10000 WHERE id = ?", (butter,))
    hefe = recipe(conn, 10, "Hefeteig", mehl, limit=5000, surcharge="1,2")
    kirsch = recipe(conn, 11, "Kirschfüllung", mehl, limit=5000, preproduce=True)
    streusel = recipe(conn, 12, "Streusel", mehl)                       # ohne Obergrenze
    bro = recipe(conn, 13, "Brötchenteig", mehl, limit=10000, pieces=[("Brötchen", 55)])
    pw = rs.get_recipe(conn, bro)["piece_weights"][0]["id"]
    w = {"hefe": hefe, "kirsch": kirsch, "streusel": streusel, "bro": bro, "pw": pw, "butter": butter}
    w["streusel_kuchen"] = article(conn, 100, "Kirschstreusel", [
        {"recipe_id": hefe, "amount_g": 1200}, {"recipe_id": kirsch, "amount_g": 1500},
        {"recipe_id": streusel, "amount_g": 600}, {"kind": "raw", "raw_material_id": butter, "amount_pieces": 1}],
        per_whole=12)
    w["tasche"] = article(conn, 101, "Kirsch-Nusstasche", [{"recipe_id": kirsch, "amount_g": 30}])
    w["broetchen"] = article(conn, 102, "Brötchen", [{"recipe_id": bro, "piece_weight_id": pw}])
    w["zopf"] = article(conn, 103, "Zopf", [{"recipe_id": hefe, "amount_g": 500}])
    return w


def test_multiplier_rules():
    assert plan.multiplier(20, 0, 2, 12) == 4                 # 20 + 24 = 44 Stück → 4 Kuchen (aufgerundet)
    assert plan.multiplier(0, 1, 0, 13) == 1                  # halb bei 13 = 7 Stück → 1 Kuchen
    assert plan.multiplier(3, 1, 0, None) == Fraction(7, 2)  # Zopf: 3 + ½
    assert plan.quantity_text(20, 0, 2) == "20 Stück + 2 ganze"


def test_plan_save_add_and_last_order_no(conn, world):
    plan.save_plan(conn, FR, {"lines": [{"article_id": world["tasche"], "order_no": 2, "pieces": 60},
                                         {"article_id": world["zopf"], "pieces": 0}]})
    got = plan.get_plan(conn, FR)
    assert [(l["name"], l["order_no"], l["pieces"]) for l in got["lines"]] == [("Kirsch-Nusstasche", 2, 60)]
    assert conn.execute("SELECT last_order_no FROM sales_article WHERE id = ?", (world["tasche"],)).fetchone()[0] == 2
    with pytest.raises(ValidationError):
        plan.save_plan(conn, FR, {"lines": [{"article_id": world["zopf"], "wholes": 1}]})   # kein Stück je Ganzes
    with pytest.raises(ConflictError) as exc:
        plan.add_to_plan(conn, FR, {"lines": [{"article_id": world["tasche"], "order_no": 2, "pieces": 10}]})
    assert exc.value.code == "overwrite_question"
    plan.add_to_plan(conn, FR, {"lines": [{"article_id": world["tasche"], "order_no": 2, "pieces": 10},
                                           {"article_id": world["zopf"], "pieces": 1}], "overwrite": True})
    assert {(l["name"], l["pieces"]) for l in plan.get_plan(conn, FR)["lines"]} == {("Kirsch-Nusstasche", 10), ("Zopf", 1)}


def _entry(prev, recipe_id, key=None):
    for e in prev["entries"]:
        if e["recipe_id"] == recipe_id and (key is None or e["key"] == key):
            return e
    raise AssertionError("kein Eintrag")


def example_plan(conn, w):
    plan.save_plan(conn, FR, {"lines": [{"article_id": w["streusel_kuchen"], "order_no": 2, "pieces": 20, "wholes": 2},
                                         {"article_id": w["tasche"], "order_no": 2, "pieces": 60},
                                         {"article_id": w["zopf"], "order_no": 1, "pieces": 13, "halves": 1}]})


def test_example_from_concept(conn, world):
    """docs/planer.md 7: Kirschfüllung Fr · Auftrag 2 = 4 × 1 500 + 60 × 30 = 7 800 g."""
    example_plan(conn, world)
    choices = plan.clean_choices({})
    prev = plan.preview(conn, [FR], choices)
    k = _entry(prev, world["kirsch"])
    assert k["demand_g"] == 7800 and k["mode"] == "up"             # vorproduzierbar → Startwert Aufrunden
    assert k["doughs"] == [5000, 5000]
    for mode, doughs in (("exact", [3900, 3900]), ("down", [5000]), ("drop", [])):
        e = _entry(plan.preview(conn, [FR], plan.clean_choices({"modes": {k["key"]: mode}})), world["kirsch"])
        assert e["doughs"] == doughs
    e = _entry(plan.preview(conn, [FR], plan.clean_choices(
        {"modes": {k["key"]: "exact"}, "surcharge": {k["key"]: {"unit": "%", "value": 12}}})), world["kirsch"])
    assert e["doughs"] == [3947, 3947] and e["surcharge_g"] == 94
    # Streusel ohne Obergrenze: ein Teig, nur Genau/Streichen
    s = _entry(prev, world["streusel"])
    assert s["doughs"] == [2400]
    out = next(b for d in prev["days"] for b in d["recipes"] if b["recipe_id"] == world["streusel"])
    assert out["entries"][0]["modes"] == ["exact", "drop"]
    # Rohstoff Butter 1 Stück je Kuchen → 4 × 250 g
    assert [(r["name"], r["amount_g"]) for r in prev["raw"]] == [("Butter", 1000)]


def test_carryover_and_merge(conn, world):
    """Hefeteig 9 950 g + 1,2 % = 10 070 g > 2 × 5 000 g → Übertrag 70 g, Auftrag 2 rückt nach."""
    hefe_only = article(conn, 110, "Hefe-Test", [{"recipe_id": world["hefe"], "amount_g": 9950}])
    zwei = article(conn, 111, "Hefe-Test 2", [{"recipe_id": world["hefe"], "amount_g": 4800}])
    plan.save_plan(conn, FR, {"lines": [{"article_id": hefe_only, "order_no": 1, "pieces": 1},
                                         {"article_id": zwei, "order_no": 2, "pieces": 1}]})
    prev = plan.preview(conn, [FR], plan.clean_choices({}))
    hefe = [e for e in prev["entries"] if e["recipe_id"] == world["hefe"]]
    assert [(e["kind"], e["doughs"]) for e in hefe] == [("order", [5000, 5000]), ("carry", [70]),
                                                         ("order", [4858])]
    assert "Übertrag von 70 g" in hefe[0]["hint"]
    carry = hefe[1]
    assert carry["next_key"] == hefe[2]["key"]
    merged = plan.preview(conn, [FR], plan.clean_choices({"carry_into": {carry["key"]: hefe[2]["key"]}}))
    hefe = [e for e in merged["entries"] if e["recipe_id"] == world["hefe"]]
    assert [(e["kind"], e["target_g"]) for e in hefe] == [("order", 10000), ("order", 4800 + 58 + 70)]


def test_merge_over_days_and_commit(conn, world):
    example_plan(conn, world)
    plan.save_plan(conn, SA, {"lines": [{"article_id": world["tasche"], "order_no": 1, "pieces": 100}]})
    run = plan.create_run(conn, {"dates": [FR, SA]})
    keys = sorted(e["key"] for d in run["days"] for b in d["recipes"] if b["recipe_id"] == world["kirsch"]
                  for e in b["entries"])
    assert len(keys) == 2
    run = plan.update_run(conn, run["id"], {"choices": {"merges": [keys], "modes": {"+".join(sorted(
        keys, key=lambda k: (k.split('|')[1], k.split('|')[2]))): "exact"}}})
    block = next(b for d in run["days"] for b in d["recipes"] if b["recipe_id"] == world["kirsch"])
    e = block["entries"][0]
    assert e["merged"] and e["production_date"] == FR and e["demand_g"] == 7800 + 3000
    assert e["doughs"] == [3600, 3600, 3600]
    result = plan.commit_run(conn, run["id"], {})
    assert result["count"] >= 4
    with pytest.raises(ConflictError):
        plan.commit_run(conn, run["id"], {})                       # schon angelegt
    orders = {get_order(conn, oid)["recipe"]["id"]: get_order(conn, oid) for oid in result["created"]}
    k = orders[world["kirsch"]]
    assert k["planned_date"] == FR and [d["target_g"] for d in k["doughs"]] == [3600, 3600, 3600]
    arts = plan.order_articles(conn, k["id"])
    assert {(a["name"], a["plan_date"], a["amount_g"]) for a in arts["articles"]} == {
        ("Kirschstreusel", FR, 6000), ("Kirsch-Nusstasche", FR, 1800), ("Kirsch-Nusstasche", SA, 3000)}
    # Zuschlag nur zur Anzeige gespeichert; Hefeteig hat 1,2 % Vorgabe
    h = orders[world["hefe"]]
    assert conn.execute("SELECT surcharge_tenths FROM production_order WHERE id = ?", (h["id"],)).fetchone()[0] == 12


def test_pieces_basis(conn, world):
    plan.save_plan(conn, FR, {"lines": [{"article_id": world["broetchen"], "pieces": 120}]})
    run = plan.create_run(conn, {"dates": [FR]})
    res = plan.commit_run(conn, run["id"], {})
    o = get_order(conn, res["created"][0])
    assert o["basis_type"] == "pieces" and o["target_g"] == 6600


def test_existing_replace_and_delta(conn, world):
    plan.save_plan(conn, FR, {"lines": [{"article_id": world["tasche"], "order_no": 1, "pieces": 100}]})
    first = plan.commit_run(conn, plan.create_run(conn, {"dates": [FR]})["id"], {})
    plan.save_plan(conn, FR, {"lines": [{"article_id": world["tasche"], "order_no": 1, "pieces": 150}]})
    run = plan.create_run(conn, {"dates": [FR]})
    assert run["has_existing"]
    with pytest.raises(ConflictError) as exc:
        plan.commit_run(conn, run["id"], {})
    assert exc.value.code == "existing_orders"
    delta = plan.commit_run(conn, run["id"], {"mode": "delta"})
    added = get_order(conn, delta["created"][0])
    assert added["target_g"] == 5000 and delta["removed"] == []      # Mehrbedarf 1 500 g → Aufrunden (vorproduzierbar)
    run2 = plan.create_run(conn, {"dates": [FR], "choices": {}})
    rep = plan.commit_run(conn, run2["id"], {"mode": "replace"})
    assert set(rep["removed"]) == set(first["created"]) | set(delta["created"])
    assert conn.execute("SELECT count(*) FROM production_order").fetchone()[0] == len(rep["created"])


def test_errors_block_commit(conn, world):
    conn.execute("UPDATE recipe SET locked = 1 WHERE id = ?", (world["kirsch"],))
    plan.save_plan(conn, FR, {"lines": [{"article_id": world["tasche"], "pieces": 10}]})
    run = plan.create_run(conn, {"dates": [FR]})
    assert run["errors"] and "gesperrt" in run["errors"][0]["message"]
    with pytest.raises(ConflictError) as exc:
        plan.commit_run(conn, run["id"], {})
    assert exc.value.code == "plan_errors"


def test_stock_booking(conn, world, monkeypatch):
    monkeypatch.setattr(plan, "local_today", lambda: FR)
    plan.save_plan(conn, FR, {"lines": [{"article_id": world["streusel_kuchen"], "wholes": 4}]})
    res = plan.book_stock(conn, FR, {})
    assert res["booked"] == [{"number": 2, "name": "Butter", "amount_g": 1000}]
    stock = lambda: conn.execute("SELECT stock_g FROM raw_material WHERE id = ?", (world["butter"],)).fetchone()[0]
    assert stock() == 9000
    assert plan.book_stock(conn, FR, {})["booked"] == []              # nichts Neues
    plan.save_plan(conn, FR, {"lines": [{"article_id": world["streusel_kuchen"], "wholes": 2}]})
    with pytest.raises(ConflictError) as exc:
        plan.book_stock(conn, FR, {})
    assert exc.value.code == "return_question"
    plan.book_stock(conn, FR, {"return": True})
    assert stock() == 9500
    kinds = [r[0] for r in conn.execute("SELECT kind FROM stock_movement ORDER BY id")]
    assert kinds == ["planner", "planner_return", "planner"]
    with pytest.raises(ConflictError):
        plan.book_stock(conn, "2099-01-01", {})


def test_settings(conn):
    assert plan.get_settings(conn) == {"in_preselection": True}
    assert plan.save_settings(conn, {"in_preselection": False}) == {"in_preselection": False}


# -- K10-P24: Stückgewicht löschen mit Wahl --------------------------------------------

def test_piece_weight_delete_resolutions(conn, world):
    bro = world["bro"]
    rev = lambda: rs.get_recipe(conn, bro)["revision"]
    rs.set_piece_weights(conn, bro, [{"id": world["pw"], "label": "Brötchen", "weight_g": 55},
                                     {"label": "Laugen", "weight_g": 70}], revision=rev())
    laugen = next(p["id"] for p in rs.get_recipe(conn, bro)["piece_weights"] if p["label"] == "Laugen")
    keep_only_laugen = [{"id": laugen, "label": "Laugen", "weight_g": 70}]
    with pytest.raises(ConflictError) as exc:
        rs.set_piece_weights(conn, bro, keep_only_laugen, revision=rev())
    assert exc.value.code == "piece_weight_in_articles"
    assert exc.value.extra["pieces"][0]["articles"] == ["102 Brötchen"]
    assert [o["id"] for o in exc.value.extra["options"]] == [laugen]
    with pytest.raises(ValidationError):
        rs.set_piece_weights(conn, bro, keep_only_laugen, revision=rev(),
                             article_resolution={str(world["pw"]): {"action": "replace", "replace_with": 999}})
    rs.set_piece_weights(conn, bro, keep_only_laugen, revision=rev(),
                         article_resolution={str(world["pw"]): {"action": "replace", "replace_with": laugen}})
    line = conn.execute("SELECT piece_weight_id, amount_g FROM sales_article_line WHERE article_id = ?",
                        (world["broetchen"],)).fetchone()
    assert tuple(line) == (laugen, None)
    rs.set_piece_weights(conn, bro, [], revision=rev(),
                         article_resolution={str(laugen): {"action": "grams"}})
    line = conn.execute("SELECT piece_weight_id, amount_g FROM sales_article_line WHERE article_id = ?",
                        (world["broetchen"],)).fetchone()
    assert tuple(line) == (None, 70)


def test_piece_weight_delete_remove_lines(conn, world):
    rs.set_piece_weights(conn, world["bro"], [], revision=rs.get_recipe(conn, world["bro"])["revision"],
                         article_resolution={world["pw"]: {"action": "remove"}})
    assert conn.execute("SELECT count(*) FROM sales_article_line WHERE article_id = ?",
                        (world["broetchen"],)).fetchone()[0] == 0


# -- K10-P25: Sammelaktion „Austauschen“ -----------------------------------------------

def test_replace_recipe_raw_piece_weight(conn, world):
    from app.articles import service as art
    mehl2 = add_raw_material(conn, 3, "Mehl neu")
    neu = recipe(conn, 20, "Kirschfüllung echt", mehl2, pieces=[("Portion", 40)])
    rep = art.replace_in_lines(conn, {"kind": "recipe", "from_id": world["kirsch"], "to_id": neu, "factor": "1,5"})
    assert rep["lines"] == 2 and rep["done"] is False
    assert rep["articles"] == ["100 Kirschstreusel", "101 Kirsch-Nusstasche"]
    rep = art.replace_in_lines(conn, {"kind": "recipe", "from_id": world["kirsch"], "to_id": neu, "factor": "1,5",
                                      "article_ids": [world["tasche"]], "mode": "run"})
    assert rep["done"] and rep["lines"] == 1
    assert conn.execute("SELECT recipe_id, amount_g FROM sales_article_line WHERE article_id = ?",
                        (world["tasche"],)).fetchone()[:] == (neu, 45)
    # Rohstoff Stück × Faktor
    art.replace_in_lines(conn, {"kind": "raw", "from_id": world["butter"], "to_id": mehl2, "factor": "2",
                                "mode": "run"})
    assert conn.execute("SELECT raw_material_id, amount_pieces FROM sales_article_line WHERE kind = 'raw'"
                        ).fetchone()[:] == (mehl2, 2)
    # Stückgewicht → Stückgewicht eines anderen Rezepts; Rezept wechselt mit
    portion = rs.get_recipe(conn, neu)["piece_weights"][0]["id"]
    rep = art.replace_in_lines(conn, {"kind": "piece_weight", "from_id": world["pw"], "to_id": portion,
                                      "factor": "3", "mode": "run"})
    assert rep["hints"] and conn.execute("SELECT recipe_id, piece_weight_id FROM sales_article_line WHERE article_id = ?",
                                         (world["broetchen"],)).fetchone()[:] == (neu, portion)
    # Rezept mit Stückgewicht-Zeile → Gramm
    rep = art.replace_in_lines(conn, {"kind": "recipe", "from_id": neu, "to_id": world["hefe"], "mode": "run",
                                      "article_ids": [world["broetchen"]]})
    assert "Gramm" in rep["hints"][0]
    assert conn.execute("SELECT recipe_id, piece_weight_id, amount_g FROM sales_article_line WHERE article_id = ?",
                        (world["broetchen"],)).fetchone()[:] == (world["hefe"], None, 40)
    with pytest.raises(ValidationError):
        art.replace_in_lines(conn, {"kind": "recipe", "from_id": 1, "to_id": 1})
    with pytest.raises(ValidationError):
        art.parse_factor("0,001")
