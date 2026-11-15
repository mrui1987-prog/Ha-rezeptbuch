"""API-Tests Modul 05, Teil C2: Rezepte, Versionen, Gruppen, Seite (laufen im GitHub-Testlauf)."""

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
                    json={"name": "Weizenmehl 550", "type": "flour", "tolerance": "20"})
    assert r.status_code == 201
    return r.json()["id"]


def create(client, auth, mehl, name="Weizenbrot", amount=1000):
    r = client.post("/api/v1/admin/recipes", headers=auth, json={
        "name": name, "steps": [{"name": "Teig"}],
        "items": [{"type": "raw_material", "raw_material_id": mehl, "amount_g": amount, "step_no": 1}]})
    assert r.status_code == 201, r.text
    return r.json()


def body_of(recipe, **changes):
    data = {"name": recipe["name"], "group_id": recipe["group_id"], "steps": recipe["steps"],
            "items": [{"id": i["id"], "type": i["type"], "raw_material_id": i["raw_material"]["id"],
                       "amount_g": i["amount_g"], "step_no": i["step_no"], "needs_review": i["needs_review"]}
                      for i in recipe["items"]],
            "revision": recipe["revision"]}
    data.update(changes)
    return data


# -- Schutz ---------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("get", "/api/v1/admin/recipes/next-number"),
    ("post", "/api/v1/admin/recipes"),
    ("put", "/api/v1/admin/recipes/1"),
    ("put", "/api/v1/admin/recipes/1/piece-weights"),
    ("put", "/api/v1/admin/recipes/1/batch-sizes"),
    ("post", "/api/v1/admin/recipes/1/unlock"),
    ("post", "/api/v1/admin/recipes/1/lock"),
    ("post", "/api/v1/admin/recipes/1/archive"),
    ("post", "/api/v1/admin/recipes/1/restore"),
    ("post", "/api/v1/admin/recipes/1/copy"),
    ("delete", "/api/v1/admin/recipes/1"),
    ("post", "/api/v1/admin/recipe-groups"),
    ("put", "/api/v1/admin/recipe-groups/order"),
    ("patch", "/api/v1/admin/recipe-groups/1"),
    ("delete", "/api/v1/admin/recipe-groups/1"),
])
def test_admin_calls_need_session(client, method, path):
    kwargs = {"json": {}} if method in ("post", "put", "patch") else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_reading_needs_no_pin(client, auth, mehl):
    r = create(client, auth, mehl)
    assert client.get("/api/v1/recipes").json() == []                   # gesperrt: nicht in der Vorwahl
    assert len(client.get("/api/v1/recipes?include_locked=true").json()) == 1
    detail = client.get(f"/api/v1/recipes/{r['id']}").json()
    assert detail["items"][0]["raw_material"]["station_name"] == "Weizenmehl 550"
    assert client.get(f"/api/v1/recipes/{r['id']}/versions/1").status_code == 200
    assert client.get("/api/v1/recipe-groups").json() == []


def test_unknown_recipe_404(client):
    assert client.get("/api/v1/recipes/99").status_code == 404
    assert client.get("/api/v1/recipes/99/versions/1").status_code == 404


# -- Ablauf ---------------------------------------------------------------------------

def test_next_number(client, auth, mehl):
    assert client.get("/api/v1/admin/recipes/next-number", headers=auth).json() == {"number": 1}
    create(client, auth, mehl)
    assert client.get("/api/v1/admin/recipes/next-number", headers=auth).json() == {"number": 2}


def test_save_flow_with_version_choice(client, auth, mehl):
    r = create(client, auth, mehl)
    url = f"/api/v1/admin/recipes/{r['id']}"
    body = body_of(r, name="Weizenbrot hell")
    answer = client.put(url, headers=auth, json=body)
    assert answer.status_code == 409 and answer.json()["code"] == "version_choice_required"
    body["version_mode"] = "new"
    saved = client.put(url, headers=auth, json=body).json()
    assert saved["version_no"] == 2 and saved["save_result"]["result"] == "new_version"
    # alter Bearbeitungsstand → 409 changed_elsewhere
    again = client.put(url, headers=auth, json=body)
    assert again.status_code == 409 and again.json()["code"] == "changed_elsewhere"


def test_validation_error_400(client, auth, mehl):
    r = client.post("/api/v1/admin/recipes", headers=auth, json={"name": "=X"})
    assert r.status_code == 400 and r.json()["code"] == "formula_start"


def test_unlock_lock_copy_archive_restore_delete(client, auth, mehl):
    r = create(client, auth, mehl)
    base = f"/api/v1/admin/recipes/{r['id']}"
    assert client.post(base + "/unlock", headers=auth).json()["locked"] is False
    assert len(client.get("/api/v1/recipes").json()) == 1
    assert client.post(base + "/lock", headers=auth).json()["locked"] is True
    copy = client.post(base + "/copy", headers=auth)
    assert copy.status_code == 201 and copy.json()["name"] == "Kopie von Weizenbrot"
    assert client.post(base + "/archive", headers=auth).json()["archived"] is True
    assert client.post(base + "/restore", headers=auth).json()["archived"] is False
    assert client.delete(base, headers=auth).status_code == 204
    assert client.get(f"/api/v1/recipes/{r['id']}").status_code == 404


def test_unlock_confirmation(client, auth):
    salz = client.post("/api/v1/admin/raw-materials", headers=auth,
                       json={"name": "Salz", "tolerance": "0", "tolerance_unit": "percent"}).json()["id"]
    r = client.post("/api/v1/admin/recipes", headers=auth, json={
        "name": "Sole", "items": [{"type": "raw_material", "raw_material_id": salz, "amount_g": 20}]}).json()
    url = f"/api/v1/admin/recipes/{r['id']}/unlock"
    answer = client.post(url, headers=auth, json={})
    assert answer.status_code == 409 and answer.json()["code"] == "confirmation_required"
    assert answer.json()["zero_percent_items"][0]["name"] == "Salz"
    assert client.post(url, headers=auth, json={"confirm": True}).json()["locked"] is False


def test_piece_weights_and_batch_sizes(client, auth, mehl):
    r = create(client, auth, mehl)
    base = f"/api/v1/admin/recipes/{r['id']}"
    r = client.put(base + "/piece-weights", headers=auth,
                   json={"revision": 0, "piece_weights": [{"label": "Stück", "weight_g": "65"}]}).json()
    r = client.put(base + "/batch-sizes", headers=auth, json={"revision": r["revision"], "batch_sizes": [
        {"label": "30 Stück", "kind": "pieces", "value": "30", "piece_weight_label": "Stück"}]}).json()
    assert r["batch_sizes"][0]["piece_weight_g"] == 65
    answer = client.put(base + "/piece-weights", headers=auth, json={"piece_weights": []})
    assert answer.status_code == 409 and answer.json()["code"] == "confirmation_required"
    r = client.put(base + "/piece-weights", headers=auth,
                   json={"piece_weights": [], "confirm_delete_batch_sizes": True}).json()
    assert r["batch_sizes"] == []


def test_groups(client, auth):
    a = client.post("/api/v1/admin/recipe-groups", headers=auth, json={"name": "Brote"})
    assert a.status_code == 201
    b = client.post("/api/v1/admin/recipe-groups", headers=auth, json={"name": "Kuchen"}).json()
    order = client.put("/api/v1/admin/recipe-groups/order", headers=auth,
                       json={"group_ids": [b["id"], a.json()["id"]]}).json()
    assert [g["name"] for g in order] == ["Kuchen", "Brote"]
    renamed = client.patch(f"/api/v1/admin/recipe-groups/{b['id']}", headers=auth, json={"name": "Torten"})
    assert renamed.json()["name"] == "Torten"
    assert client.post("/api/v1/admin/recipe-groups", headers=auth, json={"name": "torten"}).status_code == 409
    assert client.delete(f"/api/v1/admin/recipe-groups/{b['id']}", headers=auth).status_code == 204


def test_recipes_page_is_served(client):
    page = client.get("/admin/rezepte")
    assert page.status_code == 200
    assert "Rezepte" in page.text and "api/v1/" in page.text
    assert page.headers["cache-control"] == "no-store"
    assert "Rezepte" in client.get("/admin/rohstoffe").text            # Reiter auf der Rohstoffseite
