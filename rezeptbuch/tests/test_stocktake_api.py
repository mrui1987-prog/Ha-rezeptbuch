"""API-Tests Inventur Teil I1 (laufen im GitHub-Testlauf)."""

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


def make(client, auth, **kw):
    data = {"name": "Weizenmehl 550", "type": "standard", "tolerance_unit": "g", "tolerance": "5",
            "unit_size_g": 25000, "unit_label": "Sack"}
    data.update(kw)
    r = client.post("/api/v1/admin/raw-materials", json=data, headers=auth)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    client.post(f"/api/v1/raw-materials/{rid}/stock/receipt", json={"amount_kg": "100"})
    return rid


def test_pin_rules(client, auth):
    assert client.post("/api/v1/admin/stocktakes", json={"name": "Inventur"}).status_code == 401
    assert client.get("/api/v1/stocktakes/open").json() == {"stocktake": None}
    rm = make(client, auth)
    r = client.post("/api/v1/admin/stocktakes", json={"name": "Inventur", "stichtag": "2026-12-31"}, headers=auth)
    assert r.status_code == 201
    sid = r.json()["id"]
    assert client.post("/api/v1/admin/stocktakes", json={"name": "x"}, headers=auth).json()["code"] == "stocktake_open"
    # Zählen ohne PIN
    r = client.post("/api/v1/stocktakes/open/counts", json={"raw_material_id": rm, "packs": 3, "source": "scan",
                                                            "device_id": "tablet"})
    assert r.status_code == 201 and r.json()["item"]["counted"] == 75000
    assert client.get(f"/api/v1/admin/stocktakes/{sid}").status_code == 401
    assert client.post(f"/api/v1/admin/stocktakes/{sid}/close", json={"confirm": True}).status_code == 401
    assert client.get(f"/api/v1/admin/stocktakes/{sid}/countlist").status_code == 401
    pv = client.get(f"/api/v1/admin/stocktakes/{sid}", headers=auth).json()
    assert pv["lines"][0]["book_before"] == 100000 and pv["lines"][0]["diff"] == -25000
    assert client.get(f"/api/v1/admin/stocktakes/{sid}/countlist", headers=auth).json()["groups"][0]["location"] \
        == "ohne Lagerort"


def test_full_flow_with_export(client, auth):
    a = make(client, auth)
    b = make(client, auth, name="Roggenmehl")
    sid = client.post("/api/v1/admin/stocktakes", json={"name": "Jahresinventur 2026"}, headers=auth).json()["id"]
    cid = client.post("/api/v1/stocktakes/open/counts", json={"raw_material_id": a, "amount_kg": "1"}).json()["count_id"]
    assert client.delete(f"/api/v1/stocktakes/open/counts/{cid}").json()["item"]["counted"] is None
    client.post("/api/v1/stocktakes/open/counts", json={"raw_material_id": a, "packs": 2, "rest_kg": "5"})
    pv = client.get(f"/api/v1/admin/stocktakes/{sid}?zero_ids={b}", headers=auth).json()
    assert [ln["action"] for ln in pv["lines"]] == ["set", "zero"]
    assert client.post(f"/api/v1/admin/stocktakes/{sid}/close", json={}, headers=auth).status_code == 400
    r = client.post(f"/api/v1/admin/stocktakes/{sid}/close", json={"confirm": True, "zero_ids": [b]}, headers=auth)
    assert r.status_code == 200 and r.json()["stocktake"]["status"] == "closed"
    assert client.get(f"/api/v1/raw-materials/{a}").json()["stock_g"] == 55000
    assert client.get(f"/api/v1/raw-materials/{b}").json()["stock_g"] == 0
    r = client.get(f"/api/v1/admin/stocktakes/{sid}.xlsx", headers=auth)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert "Inventur_" in r.headers["content-disposition"]
    assert client.get("/api/v1/admin/stocktakes", headers=auth).json()[0]["status"] == "closed"
    assert client.get("/api/v1/stocktakes/open").json() == {"stocktake": None}


def test_cancel(client, auth):
    make(client, auth)
    sid = client.post("/api/v1/admin/stocktakes", json={"name": "Probe"}, headers=auth).json()["id"]
    assert client.post(f"/api/v1/admin/stocktakes/{sid}/cancel", headers=auth).json()["status"] == "cancelled"
    assert client.post("/api/v1/stocktakes/open/counts", json={"raw_material_id": 1, "amount_kg": "1"}).json()["code"] \
        == "no_open_stocktake"
