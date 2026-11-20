"""API-Tests Modul 04 Teil C1 (laufen im GitHub-Testlauf): Händler, Bezugsquellen, Massenpflege, Lese-API."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

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


def new_rm(client, auth, name, price=None):
    body = {"name": name, "tolerance_unit": "g", "tolerance": "20"}
    if price:
        body["price_per_kg"] = price
    r = client.post("/api/v1/admin/raw-materials", headers=auth, json=body)
    assert r.status_code == 201
    return r.json()["id"]


def test_dealers_pin_and_read_without_pin(client, auth):
    assert client.post("/api/v1/admin/dealers", json={"name": "BÄKO"}).status_code == 401
    r = client.post("/api/v1/admin/dealers", headers=auth, json={"name": "BÄKO"})
    assert r.status_code == 201
    d = r.json()["id"]
    assert client.post("/api/v1/admin/dealers", headers=auth, json={"name": "bäko"}).status_code == 409
    assert [x["name"] for x in client.get("/api/v1/dealers").json()] == ["BÄKO"]
    assert client.patch(f"/api/v1/admin/dealers/{d}", headers=auth, json={"name": "BÄKO Saar-Pfalz"}).status_code == 200
    assert client.post(f"/api/v1/admin/dealers/{d}/archive", headers=auth).json()["archived"] is True
    assert client.get("/api/v1/dealers").json() == []
    assert client.post(f"/api/v1/admin/dealers/{d}/restore", headers=auth).status_code == 200
    assert client.delete(f"/api/v1/admin/dealers/{d}", headers=auth).status_code == 204


def test_sources_and_price(client, auth):
    rm = new_rm(client, auth, "Milch", price="1,00")
    d1 = client.post("/api/v1/admin/dealers", headers=auth, json={"name": "BÄKO"}).json()["id"]
    d2 = client.post("/api/v1/admin/dealers", headers=auth, json={"name": "Metro"}).json()["id"]
    url = f"/api/v1/admin/raw-materials/{rm}/sources"
    assert client.post(url, json={"dealer_id": d1}).status_code == 401
    r = client.post(url, headers=auth, json={"dealer_id": d1, "article_no": "501156", "grams_per_unit": "1030",
                                            "unit_code": "L"})
    assert r.status_code == 201
    first = r.json()["sources"][0]
    assert first["is_active"] and first["price_cents_per_kg"] == 100
    r = client.post(url, headers=auth, json={"dealer_id": d2, "price_per_kg": "0,95"})
    metro = next(s for s in r.json()["sources"] if s["dealer_id"] == d2)
    assert client.post(f"{url}/{metro['id']}/activate", headers=auth).status_code == 200
    item = client.get(f"/api/v1/raw-materials/{rm}").json()
    assert item["price_cents_per_kg"] == 95 and item["active_source"]["dealer_name"] == "Metro"
    assert item["source"] == "own" and item["datenlink_id"] is None
    assert len(client.get(f"/api/v1/raw-materials/{rm}/sources").json()) == 2
    r = client.delete(f"{url}/{metro['id']}", headers=auth)
    assert r.status_code == 409 and r.json()["code"] == "active_source"
    r = client.patch(f"{url}/{metro['id']}", headers=auth, json={"note": "nur im Winter"})
    assert r.status_code == 200


def test_bulk_dry_run(client, auth):
    a = new_rm(client, auth, "A", price="2,00")
    b = new_rm(client, auth, "B")
    d = client.post("/api/v1/admin/dealers", headers=auth, json={"name": "BÄKO"}).json()["id"]
    url = "/api/v1/admin/raw-materials/bulk-active-source"
    body = {"raw_material_ids": [a, b], "dealer_id": d, "dry_run": True}
    assert client.post(url, json=body).status_code == 401
    r = client.post(url, headers=auth, json=body)
    assert r.status_code == 200 and r.json()["changed"] == 2
    assert client.get(f"/api/v1/raw-materials/{a}/sources").json() == []
    body["dry_run"] = False
    assert client.post(url, headers=auth, json=body).json()["changed"] == 2
    assert client.get(f"/api/v1/raw-materials/{a}").json()["active_source"]["dealer_name"] == "BÄKO"


def test_csv_export_has_source_columns(client, auth):
    rm = new_rm(client, auth, "Mehl", price="0,60")
    d = client.post("/api/v1/admin/dealers", headers=auth, json={"name": "BÄKO"}).json()["id"]
    client.post(f"/api/v1/admin/raw-materials/{rm}/sources", headers=auth, json={"dealer_id": d, "article_no": "1"})
    csv = client.get("/api/v1/admin/raw-materials/export.csv", headers=auth).content.decode("utf-8-sig")
    head, line = csv.split("\r\n")[:2]
    assert head.endswith("Händler (aktiv);Artikelnummer (aktiv);datenlink-ID")
    assert line.endswith("BÄKO;1;")
