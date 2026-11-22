"""API-Tests Strichcode-Scanner Teil S1 (laufen im GitHub-Testlauf)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

H = "X-Rezeptbuch-Session"
DEV = {"device_id": "tablet-1"}


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
    data = {"name": "Weizenmehl 550", "type": "standard", "tolerance_unit": "g", "tolerance": "5"}
    data.update(kw)
    r = client.post("/api/v1/admin/raw-materials", json=data, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_scan_flow(client, auth):
    rm = make(client, auth)
    r = client.get("/api/v1/barcodes/lookup", params={"code": "4006381333931", "format": "ean_13"})
    assert r.json()["status"] == "unknown"
    r = client.post("/api/v1/barcodes", json={"code": "4006381333931", "format": "ean_13", "raw_material_id": rm,
                                             "pack_g": 25000, "pack_label": "Sack"})
    assert r.status_code == 201 and r.json()["raw_material"]["pack_label"] == "Sack"
    # +1 ohne Beleg geht nicht, ohne Führung fragt es nach
    r = client.post(f"/api/v1/raw-materials/{rm}/scan/receipt", json=DEV)
    assert r.status_code == 409 and r.json()["code"] == "not_tracked"
    r = client.post(f"/api/v1/raw-materials/{rm}/scan/receipt", json=dict(DEV, start_tracking=True))
    assert r.status_code == 400 and r.json()["code"] == "purchase_required"
    p = client.post("/api/v1/purchases", json=dict(DEV, label="Metro")).json()["id"]
    r = client.post(f"/api/v1/raw-materials/{rm}/scan/receipt", json=dict(DEV, start_tracking=True, purchase_id=p))
    assert r.status_code == 200 and r.json()["stock_g"] == 25000
    mid = r.json()["movement_id"]
    r = client.post(f"/api/v1/raw-materials/{rm}/scan/loss", json=dict(DEV, reason="breakage"))
    assert r.json()["stock_g"] == 0
    assert client.post(f"/api/v1/stock/movements/{r.json()['movement_id']}/undo", json=DEV).json()["stock_g"] == 25000
    assert client.post(f"/api/v1/stock/movements/{mid}/undo", json={"device_id": "iphone"}).status_code == 409
    assert client.get("/api/v1/purchases").json()[0]["bookings"] == 1


def test_pin_paths(client, auth):
    rm = make(client, auth, unit_size_g=25000, unit_label="Sack")
    other = make(client, auth, name="Roggenmehl")
    client.post("/api/v1/barcodes", json={"code": "ABC", "raw_material_id": rm})
    assert client.post(f"/api/v1/admin/raw-materials/{rm}/scan/correction", json=DEV).status_code == 401
    assert client.post("/api/v1/admin/barcodes/reassign", json={"code": "ABC", "raw_material_id": other}).status_code == 401
    r = client.post("/api/v1/admin/barcodes/reassign", json={"code": "ABC", "raw_material_id": other}, headers=auth)
    assert r.json()["raw_material"]["id"] == other
    r = client.post(f"/api/v1/admin/raw-materials/{rm}/stock/inventory",
                    json=dict(DEV, packs=3, rest_kg="12,5", source="scan"), headers=auth)
    assert r.json()["stock_g"] == 87500 and r.json()["movement_id"]
    r = client.post(f"/api/v1/admin/raw-materials/{rm}/scan/correction", json=DEV, headers=auth)
    assert r.json()["stock_g"] == 112500


def test_locations_and_loss_by_hand(client, auth):
    assert client.post("/api/v1/admin/storage-locations", json={"name": "Mehllager"}).status_code == 401
    loc = client.post("/api/v1/admin/storage-locations", json={"name": "Mehllager"}, headers=auth).json()
    rm = make(client, auth, location1_id=loc["id"])
    assert client.get("/api/v1/storage-locations").json()[0]["materials"] == 1
    client.post(f"/api/v1/admin/raw-materials/{rm}/stock/inventory", json={"stock_kg": "10"}, headers=auth)
    r = client.post(f"/api/v1/raw-materials/{rm}/stock/loss",
                    json={"amount_kg": "1,5", "reason": "spoilage", "source": "quick_entry"})
    assert r.status_code == 200 and r.json()["stock_g"] == 8500
    rows = client.get("/api/v1/admin/stock/movements", params={"kind": "loss"}, headers=auth).json()
    assert rows[0]["reason_text"] == "Verderb"


def test_scan_page_and_no_camera_test(client):
    r = client.get("/scannen")
    assert r.status_code == 200 and "Scannen" in r.text
    assert client.get("/kameratest").status_code == 404
