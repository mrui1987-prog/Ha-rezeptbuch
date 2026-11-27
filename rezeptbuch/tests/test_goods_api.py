"""API-Tests Handelsware und Pfand H1 (laufen im GitHub-Testlauf)."""

import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import Workbook  # noqa: E402

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


def _xlsx():
    wb = Workbook()
    ws = wb.active
    ws.append(["Abverkauf 16.11.2026 - 22.11.2026"])
    ws.append(["Artikel-Nr.", "Bezeichnung", "Anzahl", "Umsatz"])
    ws.append([1101, "Cola", 5, "12,50"])
    ws.append([1003, "Pfand Einweg", 5, "1,25"])
    ws.append([500, "Offene Handelswaren", 2, 4])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_goods_create_list_and_sales_import(client, auth):
    cola = client.post("/api/v1/admin/raw-materials", headers=auth,
                       json={"name": "Cola", "type": "goods", "register_no": 1101}).json()
    assert cola["type"] == "goods" and cola["stock_g"] == 0
    client.post("/api/v1/admin/raw-materials", headers=auth,
                json={"name": "Pfand Einweg", "type": "goods", "is_deposit": True, "register_no": 1003})
    assert client.post(f"/api/v1/raw-materials/{cola['id']}/stock/receipt", json={"amount_kg": "24"}).status_code == 200
    listed = client.get("/api/v1/raw-materials?type=goods").json()
    assert {r["name"] for r in listed} == {"Cola", "Pfand Einweg"}
    assert client.post("/api/v1/admin/sales-imports?mode=check", content=_xlsx()).status_code == 401
    rep = client.post("/api/v1/admin/sales-imports?mode=check", content=_xlsx(),
                      headers=dict(auth, **{"X-Dateiname": "abverkauf.xlsx"})).json()
    assert rep["date_from"] == "2026-11-16" and rep["counts"]["booked"] == 2 and rep["counts"]["collective"] == 1
    run = client.post("/api/v1/admin/sales-imports?mode=run", content=_xlsx(), headers=auth)
    assert run.status_code == 200 and run.json()["booked"] == 2
    again = client.post("/api/v1/admin/sales-imports?mode=run", content=_xlsx(), headers=auth)
    assert again.status_code == 409 and again.json()["code"] == "period_imported"
    assert client.get(f"/api/v1/raw-materials/{cola['id']}").json()["stock_g"] == 19000
    imports = client.get("/api/v1/admin/sales-imports", headers=auth).json()
    assert len(imports) == 1 and imports[0]["deposit_cents"] == 125
    detail = client.get(f"/api/v1/admin/sales-imports/{imports[0]['id']}", headers=auth).json()
    assert len(detail["lines"]) == 3
    ov = client.get("/api/v1/admin/deposit-overview", headers=auth).json()
    assert ov["customers_cents"] == 125 and ov["total_cents"] == -125
    assert client.delete(f"/api/v1/admin/sales-imports/{imports[0]['id']}", headers=auth).json()["reversed"] == 2
    assert client.get(f"/api/v1/raw-materials/{cola['id']}").json()["stock_g"] == 24000


def test_move_and_copy(client, auth):
    m = client.post("/api/v1/admin/raw-materials", headers=auth,
                    json={"name": "H-Milch", "type": "standard", "tolerance_unit": "g", "tolerance": "5"}).json()
    res = client.post(f"/api/v1/admin/raw-materials/{m['id']}/copy", headers=auth,
                      json={"to": "goods", "piece_g": 1000, "register_no": 1200})
    assert res.status_code == 201 and res.json()["raw_material"]["stock_ref"]["id"] == m["id"]
    a = client.post("/api/v1/admin/raw-materials", headers=auth,
                    json={"name": "Tüten", "type": "aid", "unit_label": "VE"}).json()
    moved = client.post(f"/api/v1/admin/raw-materials/{a['id']}/move", headers=auth, json={"to": "goods"})
    assert moved.status_code == 200 and moved.json()["raw_material"]["type"] == "goods"
    bad = client.post(f"/api/v1/admin/raw-materials/{a['id']}/copy", headers=auth, json={"to": "other"})
    assert bad.status_code == 400


def test_loss_deposit_return(client, auth):
    p = client.post("/api/v1/admin/raw-materials", headers=auth,
                    json={"name": "Pfand Kiste", "type": "goods", "is_deposit": True}).json()
    client.post(f"/api/v1/raw-materials/{p['id']}/stock/receipt", json={"amount_kg": "5"})
    res = client.post(f"/api/v1/raw-materials/{p['id']}/stock/loss", json={"amount_kg": "2", "reason": "deposit_return"})
    assert res.status_code == 200
    assert client.get(f"/api/v1/raw-materials/{p['id']}").json()["stock_g"] == 3000


def test_pages_still_load(client):
    for path in ("/wareneingang", "/scannen", "/admin/rohstoffe"):
        assert client.get(path).status_code == 200
