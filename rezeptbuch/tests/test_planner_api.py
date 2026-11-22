"""API- und Seitentests Planer P-B (laufen im GitHub-Testlauf)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.db.connection import connect  # noqa: E402
from app.main import app  # noqa: E402
from app.recipes import service as rs  # noqa: E402
from conftest import add_raw_material  # noqa: E402

H = "X-Rezeptbuch-Session"
DAY = "2026-11-27"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REZEPTBUCH_DB", str(tmp_path / "rezeptbuch.db"))
    with TestClient(app) as c:
        c.db_file = tmp_path / "rezeptbuch.db"
        yield c


@pytest.fixture
def auth(client):
    r = client.post("/api/v1/admin/login", json={"pin": "1234"})
    assert r.status_code == 200
    return {H: r.json()["session"]}


def seed(client):
    """Rezept mit Obergrenze 4 000 g, Stückgewicht 80 g, Artikel mit Stückliste."""
    conn = connect(client.db_file)
    try:
        raw = add_raw_material(conn, 1, "Mehl")
        r = rs.create_recipe(conn, {"number": 1, "name": "Hefeteig",
                                    "items": [{"type": "raw_material", "raw_material_id": raw, "amount_g": 1000}]})
        rid = r["id"]
        rs.set_piece_weights(conn, rid, [{"label": "Schnecke", "weight_g": 80}],
                             revision=rs.get_recipe(conn, rid)["revision"])
        rs.set_batch_sizes(conn, rid, [{"label": "voll", "kind": "weight", "value": 4000, "is_limit": True}],
                           revision=rs.get_recipe(conn, rid)["revision"])
        rs.unlock_recipe(conn, rid, confirm=True)
        pw = rs.get_recipe(conn, rid)["piece_weights"][0]["id"]
        aid = conn.execute("INSERT INTO sales_article (register_no, name, register_group) VALUES (101, 'Schnecke', 12)"
                           ).lastrowid
        conn.execute("INSERT INTO sales_article_line (article_id, position, kind, recipe_id, piece_weight_id) "
                     "VALUES (?, 1, 'recipe', ?, ?)", (aid, rid, pw))
        conn.commit()
        return {"recipe": rid, "pw": pw, "article": aid}
    finally:
        conn.close()


def test_page_without_pin_and_base(client):
    res = client.get("/planer")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    assert 'id="t-run"' in res.text and 'src="ui/common.js"' in res.text
    js = client.get("/ui/common.js").text
    assert "|scannen|planer|" in js


def test_admin_tab_and_station_button(client):
    page = client.get("/admin/planer").text
    assert 'id="plan-frame"' in page and 'id="set-presel"' in page and 'id="r-run"' in page
    station = client.get("/station/1").text
    assert 'id="b-planner"' in station and "orders/\" + id + \"/articles" in station


def test_settings_need_pin_for_writing(client, auth):
    assert client.get("/api/v1/settings/planner").json() == {"in_preselection": True}
    assert client.put("/api/v1/admin/settings/planner", json={"in_preselection": False}).status_code == 401
    r = client.put("/api/v1/admin/settings/planner", json={"in_preselection": False}, headers=auth)
    assert r.status_code == 200 and r.json() == {"in_preselection": False}
    assert client.get("/api/v1/settings/planner").json() == {"in_preselection": False}


def test_plan_run_commit_and_articles(client):
    ids = seed(client)
    lines = [{"article_id": ids["article"], "order_no": 1, "pieces": 100}]
    r = client.put(f"/api/v1/plans/{DAY}", json={"lines": lines})
    assert r.status_code == 200 and r.json()["lines"][0]["quantity_text"] == "100 Stück"
    assert client.get(f"/api/v1/plans?date_from={DAY}&date_to={DAY}").json() == [{"date": DAY, "lines": 1}]
    # gleiche Zeile übernehmen → Rückfrage, mit overwrite ok
    r = client.post(f"/api/v1/plans/{DAY}/add", json={"lines": lines})
    assert r.status_code == 409 and r.json()["code"] == "overwrite_question" and r.json()["lines"]
    assert client.post(f"/api/v1/plans/{DAY}/add", json={"lines": lines, "overwrite": True}).status_code == 200

    run = client.post("/api/v1/plan-runs", json={"dates": [DAY]}).json()
    entry = run["days"][0]["recipes"][0]["entries"][0]
    assert entry["demand_g"] == 8000 and entry["doughs"] == [4000, 4000]
    run = client.put(f"/api/v1/plan-runs/{run['id']}",
                     json={"choices": {"surcharge": {entry["key"]: {"unit": "g", "value": 50}}}}).json()
    e = run["days"][0]["recipes"][0]["entries"]
    assert [x["kind"] for x in e] == ["order", "carry"] and e[1]["demand_g"] == 100
    res = client.post(f"/api/v1/plan-runs/{run['id']}/commit", json={})
    assert res.status_code == 200 and res.json()["count"] == 2
    order_id = res.json()["created"][0]
    arts = client.get(f"/api/v1/orders/{order_id}/articles").json()
    assert arts["from_planner"] and arts["dough_count"] == 2 and arts["articles"][0]["quantity_text"] == "100 Stück"
    # zweiter Lauf: schon angelegt → Rückfrage
    run2 = client.post("/api/v1/plan-runs", json={"dates": [DAY]}).json()
    res = client.post(f"/api/v1/plan-runs/{run2['id']}/commit", json={})
    assert res.status_code == 409 and res.json()["code"] == "existing_orders"
    assert client.post(f"/api/v1/plan-runs/{run['id']}/commit", json={}).json()["code"] == "run_done"


def test_piece_weight_delete_asks_and_converts(client, auth):
    ids = seed(client)
    rec = client.get(f"/api/v1/recipes/{ids['recipe']}").json()
    body = {"revision": rec["revision"], "piece_weights": [], "confirm_delete_batch_sizes": True}
    r = client.put(f"/api/v1/admin/recipes/{ids['recipe']}/piece-weights", json=body, headers=auth)
    assert r.status_code == 409 and r.json()["code"] == "piece_weight_in_articles"
    assert r.json()["pieces"][0]["articles"] == ["101 Schnecke"]
    body["article_resolution"] = {str(ids["pw"]): {"action": "grams"}}
    r = client.put(f"/api/v1/admin/recipes/{ids['recipe']}/piece-weights", json=body, headers=auth)
    assert r.status_code == 200
    line = client.get(f"/api/v1/articles/{ids['article']}").json()["lines"][0]
    assert line["piece_weight_id"] is None and line["amount_g"] == 80


def test_replace_needs_pin_and_checks(client, auth):
    ids = seed(client)
    body = {"kind": "recipe", "from_id": ids["recipe"], "to_id": ids["recipe"] + 999, "mode": "check"}
    assert client.post("/api/v1/admin/articles/replace", json=body).status_code == 401
    r = client.post("/api/v1/admin/articles/replace", json=body, headers=auth)
    assert r.status_code == 404
