"""API-Tests Buchführung B1 / W2a (laufen im GitHub-Testlauf)."""

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


def invoice():
    pos = {"nr": 1, "pos": None, "warengruppe": "1405", "artikelnummer": "990164", "bezeichnung": "Leergut Pfand",
           "menge_tausendstel": 12000, "mengeneinheit": "ST", "gebinde_text": None, "bestellartikel": False,
           "preis_zehntausendstel_euro": 2500, "preiseinheit": "EIN", "netto_cent": 300, "mwst_prozent": 19}
    return {"status": "ok", "addon_version": "0.1.0", "daten": {
        "belegart": "rechnung", "haendler": "BÄKO Saar-Pfalz eG", "belegnummer": "RE9", "belegdatum": "2026-10-05",
        "summen": {"netto_cent": 300, "mwst_saetze": [{"satz": 19, "netto_cent": 300, "mwst_cent": 57, "brutto_cent": 357}]},
        "positionen": [pos]}, "plausibilitaet": []}


def test_pin_required(client):
    assert client.get("/api/v1/admin/booking/groups").status_code == 401
    assert client.get("/api/v1/admin/booking/export.xlsx?month=2026-10").status_code == 401


def test_invoice_to_export(client, auth, monkeypatch):
    monkeypatch.setattr(reader, "read", lambda r, pdf, name: invoice())
    pre = client.post("/api/v1/admin/receiving/upload", content=b"%PDF-1.4 x", headers=auth).json()
    assert pre["billing"] is True and pre["lines"][0]["booking"]["id"] == 1
    r = client.post("/api/v1/admin/receiving/commit", json={"token": pre["token"], "decisions": {"1": {"action": "other"}}},
                    headers=auth)
    assert r.status_code == 201
    m = client.get("/api/v1/admin/booking/month?month=2026-10", headers=auth).json()
    assert m["documents"][0]["gross"] == 357
    x = client.get("/api/v1/admin/booking/export.xlsx?month=2026-10", headers=auth)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert len(client.get("/api/v1/admin/booking/unchecked", headers=auth).json()) == 1
    g = client.post("/api/v1/admin/booking/groups", json={"name": "Getränke"}, headers=auth)
    assert g.status_code == 201 and g.json()["short_name"] == "Getränke"
