"""API-Tests Modul 06: Berechnung und Bezugsgrößen, Prüfseite (laufen im GitHub-Testlauf)."""

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
def recipe(client, auth):
    """Brötchenteig: Mehl 10 000 g, Wasser 5 800 g, Salz 200 g (G = 16 000 g), Stückgewicht 65 g."""
    ids = {}
    for name, kind, tol in (("Weizenmehl 550", "flour", "20"), ("Wasser", "standard", "50"),
                            ("Salz", "standard", "2")):
        r = client.post("/api/v1/admin/raw-materials", headers=auth,
                        json={"name": name, "type": kind, "tolerance": tol})
        assert r.status_code == 201, r.text
        ids[name] = r.json()["id"]
    r = client.post("/api/v1/admin/recipes", headers=auth, json={
        "name": "Brötchenteig",
        "items": [{"type": "raw_material", "raw_material_id": ids["Weizenmehl 550"], "amount_g": 10000},
                  {"type": "raw_material", "raw_material_id": ids["Wasser"], "amount_g": 5800},
                  {"type": "raw_material", "raw_material_id": ids["Salz"], "amount_g": 200}]})
    assert r.status_code == 201, r.text
    rec = r.json()
    r = client.put(f"/api/v1/admin/recipes/{rec['id']}/piece-weights", headers=auth,
                   json={"piece_weights": [{"label": "Stück", "weight_g": 65}]})
    assert r.status_code == 200, r.text
    return {"recipe": r.json(), "rm": ids}


def test_calculation_without_pin(client, recipe):
    rid = recipe["recipe"]["id"]
    r = client.post("/api/v1/calculation", json={"recipe_id": rid, "basis_type": "flour_total", "value": "5",
                                                  "input_unit": "kg"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert [i["target_g"] for i in data["items"]] == [5000, 2900, 100]
    assert data["totals"]["target_g"] == 8000
    assert data["piece_hints"][0]["count_tenths"] == 1230        # 8 000 / 65 = 123,07 → 123,0


def test_pieces_via_api(client, recipe):
    rec = recipe["recipe"]
    r = client.post("/api/v1/calculation", json={
        "recipe_id": rec["id"], "basis_type": "pieces",
        "pieces": [{"piece_weight_id": rec["piece_weights"][0]["id"], "count": 100}]})
    assert r.status_code == 200, r.text
    assert r.json()["basis"]["target_g"] == 6500


def test_basis_options_without_pin(client, recipe):
    rid = recipe["recipe"]["id"]
    r = client.get(f"/api/v1/recipes/{rid}/basis-options")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_g"] == 16000 and data["flour_total_available"] is True
    assert [o["name"] for o in data["raw_materials"]] == ["Weizenmehl 550", "Wasser", "Salz"]


@pytest.mark.parametrize("body, field", [
    ({"basis_type": "total", "value": "0"}, "value"),
    ({"basis_type": "total", "value": 100, "input_unit": "l"}, "input_unit"),
    ({"basis_type": "raw_material", "value": 100}, "raw_material_id"),
    ({"basis_type": "batch_size", "batch_size_id": 999}, "batch_size_id"),
])
def test_calculation_errors(client, recipe, body, field):
    body = dict(body, recipe_id=recipe["recipe"]["id"])
    r = client.post("/api/v1/calculation", json=body)
    assert r.status_code == 400, r.text
    assert r.json()["field"] == field
    assert isinstance(r.json()["detail"], str)


def test_not_found(client, recipe):
    assert client.post("/api/v1/calculation", json={"recipe_id": 999, "basis_type": "total",
                                                    "value": 100}).status_code == 404
    assert client.get("/api/v1/recipes/999/basis-options").status_code == 404


def test_calc_page_and_tabs(client):
    r = client.get("/admin/berechnung")
    assert r.status_code == 200
    assert "Berechnung" in r.text and "calculation" in r.text
    assert r.headers["cache-control"] == "no-store"
    assert "admin/berechnung" in client.get("/admin/rezepte").text
    assert "admin/berechnung" in client.get("/admin/rohstoffe").text
