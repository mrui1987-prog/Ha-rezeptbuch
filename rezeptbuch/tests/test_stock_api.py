"""API-Tests VC03-b Bestand (laufen im GitHub-Testlauf): Zugang ohne PIN, Inventur mit PIN, Filter, Archivieren."""

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


@pytest.fixture
def mehl(client, auth):
    r = client.post("/api/v1/admin/raw-materials", headers=auth,
                    json={"name": "Mehl", "type": "flour", "tolerance_unit": "g", "tolerance": "20",
                          "stock_alert_kg": "10"})
    assert r.status_code == 201
    return r.json()["id"]


def test_receipt_without_pin_inventory_with_pin(client, auth, mehl):
    r = client.post(f"/api/v1/raw-materials/{mehl}/stock/receipt", json={"amount_kg": "25", "station": 1})
    assert r.status_code == 200 and r.json()["stock_g"] == 25000
    assert client.post(f"/api/v1/admin/raw-materials/{mehl}/stock/inventory",
                       json={"stock_kg": "8"}).status_code == 401
    r = client.post(f"/api/v1/admin/raw-materials/{mehl}/stock/inventory", headers=auth, json={"stock_kg": "8"})
    assert r.status_code == 200 and r.json()["stock_status"] == "alert"
    listed = client.get("/api/v1/raw-materials?below_alert=true").json()
    assert [r["id"] for r in listed] == [mehl]
    moves = client.get(f"/api/v1/raw-materials/{mehl}/stock/movements").json()
    assert [m["kind"] for m in moves] == ["inventory", "receipt"]
    assert client.post(f"/api/v1/raw-materials/{mehl}/stock/receipt", json={"amount_kg": "x"}).status_code == 400


def test_archive_with_stock_zero_and_csv(client, auth, mehl):
    client.post(f"/api/v1/raw-materials/{mehl}/stock/receipt", json={"amount_kg": "3"})
    r = client.post(f"/api/v1/admin/raw-materials/{mehl}/archive", headers=auth, json={"stock_zero": True})
    assert r.status_code == 200 and r.json()["archived"] and r.json()["stock_g"] == 0
    csv = client.get("/api/v1/admin/raw-materials/export.csv", headers=auth).content.decode("utf-8-sig")
    assert csv.split("\r\n")[0].endswith("Bestand kg;Meldewert kg;Händler (aktiv);Artikelnummer (aktiv);datenlink-ID")


def test_archive_without_body_still_works(client, auth, mehl):
    assert client.post(f"/api/v1/admin/raw-materials/{mehl}/archive", headers=auth).status_code == 200


def test_receipt_photo_upload_without_pin_view_with_pin(client, auth, mehl):
    """M03-37: Beleg-Foto ohne PIN anhängen, ansehen nur mit PIN."""
    r = client.post(f"/api/v1/raw-materials/{mehl}/stock/receipt", json={"amount_kg": "25"})
    mid = r.json()["movement_id"]
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    r = client.post(f"/api/v1/stock/movements/{mid}/photo", content=jpeg, headers={"Content-Type": "image/jpeg"})
    assert r.status_code == 200 and r.json()["has_photo"] is True
    assert client.post(f"/api/v1/stock/movements/{mid}/photo", content=jpeg).status_code == 409
    assert client.get(f"/api/v1/admin/stock/movements/{mid}/photo").status_code == 401
    r = client.get(f"/api/v1/admin/stock/movements/{mid}/photo", headers=auth)
    assert r.status_code == 200 and r.content == jpeg and r.headers["content-type"] == "image/jpeg"
    moves = client.get(f"/api/v1/raw-materials/{mehl}/stock/movements").json()
    assert moves[0]["has_photo"] == 1
    assert client.post(f"/api/v1/stock/movements/{mid}/photo", content=b"kein bild").status_code in (400, 409)
