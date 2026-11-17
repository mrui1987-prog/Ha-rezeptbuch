"""API-Tests Modul 05, Teil C3: Vorlagen-Import, Export, interne Notiz, Filter (laufen im GitHub-Testlauf)."""

import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("openpyxl")

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from app.main import app  # noqa: E402
from template_factory import build, line, raw, recipe  # noqa: E402

H = "X-Rezeptbuch-Session"
IMPORT = "/api/v1/admin/import/recipes"
EXPORT = "/api/v1/admin/recipes/export.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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


def template():
    return build([recipe("R1", "Weizenbrot", group="Brot", note="- Mohn", display="Beginn")],
                 [line("R1", "Weizenmehl 550", 1000, schritt="Teig", flag="*"), line("R1", "Wasser", 600)],
                 [raw("Weizenmehl 550", typ="flour", tol=20, unit="g"), raw("Wasser", tol=2, unit="percent")],
                 pieces=[("R1", "Laib", 800)], batches=[("R1", "2 Laibe", "Stück", 2, "Laib")])


def post(client, auth, data, **params):
    headers = dict(auth)
    headers["Content-Type"] = "application/octet-stream"
    return client.post(IMPORT, params=params, content=data, headers=headers)


def test_import_and_export_need_session(client):
    assert client.post(IMPORT, content=template()).status_code == 401
    assert client.get(EXPORT).status_code == 401
    assert client.get("/api/v1/admin/recipes/1").status_code == 401


def test_import_check_then_run(client, auth):
    r = post(client, auth, template(), mode="check")
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["ok"] and report["counts"]["recipes"] == 1 and not report["imported"]
    assert client.get("/api/v1/recipes", params={"include_locked": True}).json() == []

    r = post(client, auth, template(), mode="run")
    assert r.status_code == 200 and r.json()["imported"]
    rows = client.get("/api/v1/recipes", params={"include_locked": True}).json()
    assert [(x["name"], x["locked"], x["review_count"]) for x in rows] == [("Weizenbrot", True, 1)]


def test_import_errors_400_with_report(client, auth):
    bad = build([recipe("R1", "Roggenbrot")], [line("R1", "Roggenmehl 1150", 500)])     # Rohstoff fehlt
    r = post(client, auth, bad, mode="run")
    assert r.status_code == 400
    assert r.json()["code"] == "import_failed" and r.json()["report"]["errors"]


def test_reimport_same_file_is_unchanged(client, auth):
    """Seit 0.5.7 (C3-E5): vorhandene Rezepte sind kein Fehler; gleicher Inhalt = unverändert."""
    post(client, auth, template(), mode="run")
    r = post(client, auth, template(), mode="run")
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["recipes_unchanged"] == 1 and r.json()["counts"]["recipes_new_version"] == 0


def test_import_overwrite_needs_confirmation(client, auth):
    client.post("/api/v1/admin/raw-materials", headers=auth, json={"name": "Wasser", "tolerance": "5"})
    r = post(client, auth, template(), mode="run")
    assert r.status_code == 409 and r.json()["code"] == "overwrite_confirmation_required"
    r = post(client, auth, template(), mode="run", confirm_overwrite="true")
    assert r.status_code == 200 and r.json()["counts"]["overwritten"] == 1


def test_import_unreadable_file(client, auth):
    r = post(client, auth, b"kein Excel", mode="check")
    assert r.status_code == 400 and r.json()["code"] == "unreadable_file"


def test_export_download_and_route_order(client, auth):
    post(client, auth, template(), mode="run")
    r = client.get(EXPORT, headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(XLSX)
    assert 'filename="rezepte_' in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb["Rezepte"]["C2"].value == "Weizenbrot"
    assert client.get(EXPORT, headers=auth, params={"include_archived": True}).status_code == 200


def test_internal_note_only_in_admin_view(client, auth):
    mehl = client.post("/api/v1/admin/raw-materials", headers=auth,
                       json={"name": "Weizenmehl 550", "type": "flour", "tolerance": "20"}).json()["id"]
    created = client.post("/api/v1/admin/recipes", headers=auth, json={
        "name": "Brot", "internal_note": "nur intern",
        "items": [{"type": "raw_material", "raw_material_id": mehl, "amount_g": 1000}]}).json()
    assert created["internal_note"] == "nur intern"
    assert "internal_note" not in client.get(f"/api/v1/recipes/{created['id']}").json()
    assert client.get(f"/api/v1/admin/recipes/{created['id']}", headers=auth).json()["internal_note"] == "nur intern"


def test_filter_archived_raw_materials(client, auth):
    mehl = client.post("/api/v1/admin/raw-materials", headers=auth,
                       json={"name": "Weizenmehl 550", "type": "flour", "tolerance": "20"}).json()["id"]
    client.post("/api/v1/admin/recipes", headers=auth, json={
        "name": "Brot", "items": [{"type": "raw_material", "raw_material_id": mehl, "amount_g": 1000}]})
    params = {"include_locked": True, "archived_raw_materials": True}
    assert client.get("/api/v1/recipes", params=params).json() == []
    assert client.post(f"/api/v1/admin/raw-materials/{mehl}/archive", headers=auth).status_code == 200
    rows = client.get("/api/v1/recipes", params=params).json()
    assert [r["archived_raw_material_count"] for r in rows] == [1]


def test_page_has_c3_parts(client):
    html = client.get("/admin/rezepte").text
    for text in ("Import/Export", "Zutaten speichern", "Kurzname: ", "am Anfang und am Ende", "nur am Ende",
                 "Interne Notiz", "mit archivierten Rohstoffen", "Ist der Hinweistext leer"):
        assert text in html, text
    assert "Station: " not in html


# -- Sammelaktionen (C3-E1) --------------------------------------------------------------------

BULK = "/api/v1/admin/recipes/bulk"


def test_bulk_needs_session(client):
    assert client.post(BULK, json={"action": "lock", "ids": [1]}).status_code == 401


def test_bulk_unlock_check_run(client, auth):
    post(client, auth, template(), mode="run")
    rid = client.get("/api/v1/recipes", params={"include_locked": True}).json()[0]["id"]
    r = client.post(BULK, headers=auth, json={"action": "unlock", "ids": [rid], "mode": "check"})
    assert r.status_code == 200 and r.json()["counts"]["done"] == 1 and r.json()["warnings"][0]["review_count"] == 1
    r = client.post(BULK, headers=auth, json={"action": "unlock", "ids": [rid], "mode": "run"})
    assert r.status_code == 409 and r.json()["code"] == "confirmation_required"
    r = client.post(BULK, headers=auth, json={"action": "unlock", "ids": [rid], "mode": "run", "confirm": True})
    assert r.status_code == 200 and r.json()["executed"]
    assert client.get("/api/v1/recipes").json()[0]["id"] == rid          # jetzt in der Vorwahl


def test_bulk_bad_input(client, auth):
    assert client.post(BULK, headers=auth, json={"action": "lock", "ids": []}).status_code == 400
    assert client.post(BULK, headers=auth, json={"action": "kopieren", "ids": [1]}).status_code == 400


def test_export_selection(client, auth):
    post(client, auth, template(), mode="run")
    rid = client.get("/api/v1/recipes", params={"include_locked": True}).json()[0]["id"]
    r = client.get(EXPORT, headers=auth, params={"ids": str(rid)})
    assert r.status_code == 200
    assert load_workbook(io.BytesIO(r.content))["Rezepte"]["C2"].value == "Weizenbrot"
    assert client.get(EXPORT, headers=auth, params={"ids": "a,b"}).status_code == 400


def test_page_has_bulk_bar(client):
    html = client.get("/admin/rezepte").text
    for text in ("sel-all", "Auswahl aufheben", "Endgültig löschen", "admin/recipes/bulk"):
        assert text in html, text


def test_import_include_samples_param(client, auth):
    """C3-E11: Musterdaten werden übersprungen, mit include_samples=true importiert."""
    sample = client.get("/api/v1/admin/recipes/template.xlsx", headers=auth).content
    r = post(client, auth, sample, mode="check")
    assert r.status_code == 200 and r.json()["nothing_to_import"] and r.json()["counts"]["samples_recipes"] == 2
    r = post(client, auth, sample, mode="check", include_samples="true")
    assert r.status_code == 200 and r.json()["counts"]["recipes"] == 2 and r.json()["counts"]["conversions"] == 2


def test_bulk_restore(client, auth):
    """C3-E8: Sammelaktion „Wiederherstellen“."""
    assert post(client, auth, template(), mode="run").status_code == 200
    rid = client.get("/api/v1/recipes", params={"include_locked": "true"}).json()[0]["id"]
    body = {"action": "archive", "ids": [rid], "mode": "run", "confirm": True}
    assert client.post("/api/v1/admin/recipes/bulk", json=body, headers=auth).status_code == 200
    body["action"] = "restore"
    r = client.post("/api/v1/admin/recipes/bulk", json=body, headers=auth)
    assert r.status_code == 200, r.text
    assert [e["id"] for e in r.json()["done"]] == [rid]


def test_replace_raw_material_api(client, auth):
    """C3-E9: Vorschau, Bestätigung nötig, Ausführen; C3-E10: alte Version mit aktueller Menge."""
    assert post(client, auth, template(), mode="run").status_code == 200
    rms = {m["name"]: m["id"] for m in client.get("/api/v1/raw-materials").json()}
    milch = client.post("/api/v1/admin/raw-materials", headers=auth, json={"name": "Milch", "tolerance": "5"}).json()
    url = "/api/v1/admin/recipes/replace-raw-material"
    body = {"old_raw_material_id": rms["Wasser"], "new_raw_material_id": milch["id"], "factor": "0,5"}
    assert client.post(url, json=body).status_code == 401
    r = client.post(url, json=body, headers=auth)
    assert r.status_code == 200, r.text
    recipe = r.json()["recipes"][0]
    assert recipe["changes"][0]["old_g"] == 600 and recipe["changes"][0]["new_g"] == 300
    body.update(mode="run", recipes=[{"id": recipe["id"], "revision": recipe["revision"]}])
    r = client.post(url, json=body, headers=auth)
    assert r.status_code == 409 and r.json()["code"] == "confirmation_required"
    body["confirm"] = True
    r = client.post(url, json=body, headers=auth)
    assert r.status_code == 200 and r.json()["done"][0]["new_version"] == 2
    old = client.get(f"/api/v1/recipes/{recipe['id']}/versions/1").json()
    assert old["items"][1]["current"]["missing"] is True and old["current_only"][0]["name"] == "Milch"
    r = client.post(url, json={**body, "factor": "0"}, headers=auth)
    assert r.status_code == 400
