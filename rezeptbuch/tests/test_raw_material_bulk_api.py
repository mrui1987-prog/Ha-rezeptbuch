"""API-Tests Rohstoffverwaltung R1 (laufen im GitHub-Testlauf): Filter, Sammelaktionen, Verlauf, Export der Auswahl,
Seitenadressen."""

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


def mk(client, auth, name, **extra):
    data = {"name": name, "tolerance_unit": "g", "tolerance": "20"}
    data.update(extra)
    r = client.post("/api/v1/admin/raw-materials", headers=auth, json=data)
    assert r.status_code == 201
    return r.json()["id"]


def test_filters_and_bulk(client, auth):
    a = mk(client, auth, "Mehl", type="flour")
    b = mk(client, auth, "Zucker", price_per_kg="1")
    listed = client.get("/api/v1/raw-materials?type=flour&no_price=true").json()
    assert [r["id"] for r in listed] == [a]
    assert client.get("/api/v1/raw-materials?status=x").status_code == 400
    body = {"action": "archive", "ids": [a, b], "preview": True}
    assert client.post("/api/v1/admin/raw-materials/bulk", json=body).status_code == 401
    r = client.post("/api/v1/admin/raw-materials/bulk", headers=auth, json=body)
    assert r.status_code == 200 and r.json()["changed"] == 2
    r = client.post("/api/v1/admin/raw-materials/bulk", headers=auth, json={"action": "archive", "ids": [a]})
    assert r.status_code == 409
    r = client.post("/api/v1/admin/raw-materials/bulk", headers=auth,
                    json={"action": "archive", "ids": [a], "confirm": True})
    assert r.status_code == 200
    assert [x["id"] for x in client.get("/api/v1/raw-materials?status=archived").json()] == [a]


def test_movements_export_selection_and_pages(client, auth):
    a = mk(client, auth, "Mehl")
    b = mk(client, auth, "Salz")
    client.post(f"/api/v1/raw-materials/{a}/stock/receipt", json={"amount_kg": "5", "source": "quick_entry"})
    assert client.get("/api/v1/admin/stock/movements").status_code == 401
    moves = client.get("/api/v1/admin/stock/movements", headers=auth).json()
    assert moves[0]["name"] == "Mehl" and moves[0]["source"] == "quick_entry"
    csv = client.get(f"/api/v1/admin/raw-materials/export.csv?ids={b}", headers=auth).content.decode("utf-8-sig")
    lines = [line for line in csv.split("\r\n") if line]
    assert len(lines) == 2 and lines[1].split(";")[1] == "Salz"
    assert client.get("/api/v1/admin/raw-materials/export.csv?ids=x", headers=auth).status_code == 400
    for path in ("/admin/rohstoffe", "/admin/rohstoffe/12", "/admin/rohstoffe/neu", "/admin/rohstoffe/bestand",
                 "/admin/rohstoffe/haendler"):
        text = client.get(path).text
        assert "Rohstoffverwaltung" in text and "Bestand erfassen" in text
    io = client.get("/admin/rezepte").text
    assert "Rohstoffe aus CSV importieren" in io and "Rohstoffe exportieren (CSV)" in io
