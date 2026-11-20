"""API-Tests Planer Teil P-A (laufen im GitHub-Testlauf): Verkaufsartikel, Import, Stückliste, Export, Planungsfelder."""

import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from app.main import app  # noqa: E402

H = "X-Rezeptbuch-Session"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REZEPTBUCH_DB", str(tmp_path / "rezeptbuch.db"))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth(client):
    r = client.post("/api/v1/admin/login", json={"pin": "1234"})
    assert r.status_code == 200
    return {H: r.json()["session"]}


def xlsx():
    wb = Workbook()
    ws = wb.active
    ws.append(["Nummer", "Name", "Warengruppe"])
    for row in [(3, "# Brot", 0), (52, "Brötchen", 2), (287, "Kirschstreusel", 12), (532, "Cola", 16)]:
        ws.append(list(row))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def test_import_needs_pin_and_works(client, auth):
    url = "/api/v1/admin/articles/import"
    assert client.post(url, content=xlsx()).status_code == 401
    r = client.post(url + "?mode=check", headers=auth, content=xlsx())
    assert r.status_code == 200 and r.json()["counts"]["new"] == 2 and r.json()["imported"] is False
    r = client.post(url + "?mode=run&groups=2,12,16", headers=auth, content=xlsx())
    assert r.json()["imported"] is True and r.json()["counts"]["new"] == 3
    listed = client.get("/api/v1/articles").json()          # Lesen ohne PIN
    assert [a["register_no"] for a in listed] == [52, 287, 532]
    assert {g["group"] for g in client.get("/api/v1/articles/groups").json()} == {2, 12, 16}


def test_article_lines_update_bulk_export(client, auth):
    client.post("/api/v1/admin/articles/import?mode=run", headers=auth, content=xlsx())
    art = {a["register_no"]: a for a in client.get("/api/v1/articles").json()}
    kid, bid = art[287]["id"], art[52]["id"]
    rec = client.post("/api/v1/admin/recipes", headers=auth, json={
        "name": "Hefeteig", "items": [], "steps": []})
    assert rec.status_code == 201, rec.text
    rid = rec.json()["id"]
    url = f"/api/v1/admin/articles/{kid}/lines"
    assert client.put(url, json={"lines": []}).status_code == 401
    r = client.put(url, headers=auth, json={"lines": [{"kind": "recipe", "recipe_id": rid, "amount_g": 1200}]})
    assert r.status_code == 200 and r.json()["sum_g"] == 1200
    assert client.put(url, headers=auth, json={"lines": [{"kind": "recipe", "recipe_id": rid}]}).status_code == 400
    r = client.patch(f"/api/v1/admin/articles/{kid}", headers=auth, json={"pieces_per_whole": 12, "note": "Blech"})
    assert r.json()["note"] == "Blech"
    r = client.post(f"/api/v1/admin/articles/{bid}/copy-lines", headers=auth, json={"from_article_id": kid})
    assert len(r.json()["lines"]) == 1
    r = client.post("/api/v1/admin/articles/bulk", headers=auth, json={"ids": [bid], "action": "plan_disable"})
    assert r.json() == {"changed": 1}
    assert client.get(f"/api/v1/articles/{bid}").json()["plan_enabled"] is False
    r = client.get("/api/v1/admin/articles/export.xlsx", headers=auth)
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_recipe_planning_endpoint(client, auth):
    rid = client.post("/api/v1/admin/recipes", headers=auth, json={"name": "Kirschfüllung", "items": [],
                                                                   "steps": []}).json()["id"]
    url = f"/api/v1/admin/recipes/{rid}/planning"
    assert client.put(url, json={"preproduce": True}).status_code == 401
    r = client.put(url, headers=auth, json={"preproduce": True, "weigh_surcharge": "1,2"})
    assert r.status_code == 200 and r.json()["preproduce"] is True and r.json()["weigh_surcharge_tenths"] == 12
    assert client.put(url, headers=auth, json={"weigh_surcharge": "x"}).status_code == 400


def test_planner_page_and_tabs(client):
    for path in ("/admin/planer", "/admin/planer/artikel"):
        r = client.get(path)
        assert r.status_code == 200
        assert "HA-Rezeptbuch – Planer" in r.text and "api/v1/" in r.text
    for path in ("/admin", "/admin/rezepte", "/admin/berechnung", "/admin/waagen", "/admin/ablauf"):
        assert 'admin/planer' in client.get(path).text
    assert "va-check" in client.get("/admin/rezepte").text           # Vectron-Import im Reiter Import/Export
