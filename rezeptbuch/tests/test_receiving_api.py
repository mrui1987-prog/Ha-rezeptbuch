"""API-Tests Wareneingang W1 (laufen im GitHub-Testlauf)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.readers import client as reader  # noqa: E402

H = "X-Rezeptbuch-Session"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REZEPTBUCH_DB", str(tmp_path / "rezeptbuch.db"))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth(client):
    return {H: client.post("/api/v1/admin/login", json={"pin": "1234"}).json()["session"]}


def answer(no="AT1"):
    return {"status": "ok", "addon_version": "0.1.0", "daten": {
        "belegart": "auftragsbestaetigung", "haendler": "BÄKO Saar-Pfalz eG", "belegnummer": no,
        "belegdatum": "2026-11-20", "lieferdatum_voraussichtlich": "2026-11-23", "summen": {"netto_cent": 100},
        "positionen": [{"nr": 1, "artikelnummer": "202656", "bezeichnung": "Weizenmehl 550",
                        "menge_tausendstel": 50000, "mengeneinheit": "KG", "gebinde_text": "2 SCK à 25 KG",
                        "bestellartikel": False, "preis_zehntausendstel_euro": 6000, "preiseinheit": "EIN",
                        "netto_cent": 3000, "mwst_prozent": 7}]}}


def test_upload_commit_book(client, auth, monkeypatch):
    monkeypatch.setattr(reader, "read", lambda r, pdf, name: answer())
    rm = client.post("/api/v1/admin/raw-materials", json={"name": "Weizenmehl 550", "type": "standard",
                                                          "tolerance_unit": "g", "tolerance": "5"},
                     headers=auth).json()["id"]
    assert client.post("/api/v1/admin/receiving/upload", content=b"%PDF-1").status_code == 401
    pre = client.post("/api/v1/admin/receiving/upload", content=b"%PDF-1", headers=dict(auth, **{"X-Dateiname": "a.pdf"}))
    assert pre.status_code == 200 and pre.json()["lines"][0]["target"] == "unknown"
    doc = client.post("/api/v1/admin/receiving/commit", headers=auth, json={
        "token": pre.json()["token"], "decisions": {"1": {"action": "assign", "raw_material_id": rm}}})
    assert doc.status_code == 201
    deliveries = client.get("/api/v1/receiving/deliveries").json()
    line = deliveries[0]["lines"][0]
    res = client.post(f"/api/v1/receiving/deliveries/{doc.json()['id']}/book",
                      json={"lines": [{"id": line["id"], "qty_milli": 50000, "start_tracking": True}]})
    assert res.status_code == 200 and res.json()["status"] == "booked"
    assert client.get(f"/api/v1/raw-materials/{rm}").json()["stock_g"] == 50000
    assert client.get("/api/v1/admin/receiving/documents", headers=auth).json()[0]["doc_no"] == "AT1"


def test_reader_unreachable_message(client, auth, monkeypatch):
    monkeypatch.setenv("REZEPTBUCH_READER_URL", "http://127.0.0.1:9")
    res = client.post("/api/v1/admin/receiving/upload", content=b"%PDF-1", headers=auth)
    assert res.status_code == 409 and res.json()["code"] == "reader_unreachable"


def test_page(client):
    assert client.get("/wareneingang").status_code == 200
    assert 'href="wareneingang"' in client.get("/").text
