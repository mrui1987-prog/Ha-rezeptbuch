"""API-Tests Modul 05, Teil C1: Rohstoff-CSV-Import, Filter 0 %, Sperre B2 (laufen im GitHub-Testlauf)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

H = "X-Rezeptbuch-Session"
URL = "/api/v1/admin/import/raw-materials"
HEADER = "Nummer;Name;Kurzname;Typ;Toleranz;Toleranzeinheit;Gebindegröße g;Gebindebezeichnung;Herkunft;archiviert"


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


def csv_bytes(*lines):
    return ("\r\n".join([HEADER, *lines]) + "\r\n").encode("utf-8")


def post(client, auth, data, **params):
    headers = dict(auth)
    headers["Content-Type"] = "application/octet-stream"
    return client.post(URL, params=params, content=data, headers=headers)


def test_import_needs_session(client):
    assert client.post(URL, content=csv_bytes(";Hefe;;;1;g;;;;")).status_code == 401


def test_check_then_run(client, auth):
    data = csv_bytes(";Hefe;;;1;g;;;;", ";Vanille;;;;;;;;")
    r = post(client, auth, data, mode="check")
    assert r.status_code == 200
    report = r.json()
    assert report["ok"] and not report["imported"] and report["counts"]["new"] == 2
    assert client.get("/api/v1/raw-materials").json() == []
    r = post(client, auth, data, mode="run")
    assert r.status_code == 200 and r.json()["imported"]
    items = {i["name"]: i for i in client.get("/api/v1/raw-materials").json()}
    assert (items["Vanille"]["tolerance"], items["Vanille"]["tolerance_unit"]) == (0, "percent")


def test_overwrite_needs_confirmation(client, auth):
    item = client.post("/api/v1/admin/raw-materials", headers=auth,
                       json={"name": "Salz", "tolerance": "5", "tolerance_unit": "g"}).json()
    data = csv_bytes(f"{item['number']};Salz;;;7;g;;;;")
    r = post(client, auth, data, mode="run")
    assert r.status_code == 409
    assert r.json()["code"] == "overwrite_confirmation_required"
    assert r.json()["report"]["changes"][0]["fields"][0]["new"] == "7 g"
    assert client.get(f"/api/v1/raw-materials/{item['id']}").json()["tolerance"] == 5
    r = post(client, auth, data, mode="run", confirm_overwrite="true")
    assert r.status_code == 200
    assert client.get(f"/api/v1/raw-materials/{item['id']}").json()["tolerance"] == 7


def test_run_with_errors_400_and_nothing_saved(client, auth):
    r = post(client, auth, csv_bytes(";Gut;;;1;g;;;;", ";=Böse;;;1;g;;;;"), mode="run")
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "import_failed"
    assert body["report"]["errors"][0]["line"] == 3
    assert client.get("/api/v1/raw-materials").json() == []


def test_unreadable_file_400(client, auth):
    r = post(client, auth, b"Nummer;Toleranz\r\n1;2\r\n", mode="check")
    assert r.status_code == 400


def test_file_too_large_413(client, auth):
    r = post(client, auth, b"Name\r\n" + b"x" * (5 * 1024 * 1024 + 10), mode="check")
    assert r.status_code == 413


def test_zero_percent_filter(client, auth):
    post(client, auth, csv_bytes(";Null;;;0;%;;;;", ";Hand;;;0;g;;;;", ";Fünf;;;5;g;;;;"), mode="run")
    found = client.get("/api/v1/raw-materials", params={"zero_percent": "true"}).json()
    assert [i["name"] for i in found] == ["Null"]


def test_b2_on_create_400(client, auth):
    r = client.post("/api/v1/admin/raw-materials", headers=auth,
                    json={"name": "=SUMME(A1)", "tolerance": "5", "tolerance_unit": "g"})
    assert r.status_code == 400
    assert r.json()["code"] == "formula_start"


def test_admin_page_has_import_and_filter(client):
    text = client.get("/admin/rohstoffe").text
    assert "CSV-Import" in text and "nur Toleranz 0 %" in text
    assert "0 % wird gewogen" in text


def test_version_050(client):
    assert client.get("/api/v1/health").json()["version"] == "0.5.0"
