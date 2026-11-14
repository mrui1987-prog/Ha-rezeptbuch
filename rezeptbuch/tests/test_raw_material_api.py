"""API-Tests Modul 03: PIN-Anmeldung, Rohstoffe, Export, Seite (laufen im GitHub-Testlauf)."""

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


def new(name="Margarine A", **kw):
    data = {"name": name, "type": "standard", "tolerance_unit": "g", "tolerance": "5"}
    data.update(kw)
    return data


# -- Anmeldung ----------------------------------------------------------------------

def test_system_info_shows_probe_operation(client):
    info = client.get("/api/v1/system/info").json()
    assert info["pin_is_default"] is True


def test_login_wrong_pin_401(client):
    assert client.post("/api/v1/admin/login", json={"pin": "0000"}).status_code == 401


def test_login_empty_pin_400(client):
    assert client.post("/api/v1/admin/login", json={"pin": ""}).status_code == 400


def test_lock_after_five_failures(client):
    for _ in range(5):
        client.post("/api/v1/admin/login", json={"pin": "0000"})
    assert client.post("/api/v1/admin/login", json={"pin": "1234"}).status_code == 423


def test_logout_ends_session(client, auth):
    assert client.post("/api/v1/admin/logout", headers=auth).status_code == 200
    assert client.get("/api/v1/admin/raw-materials/next-number", headers=auth).status_code == 401


# -- Schutz -------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("get", "/api/v1/admin/raw-materials/next-number"),
    ("get", "/api/v1/admin/raw-materials/similar?name=x"),
    ("get", "/api/v1/admin/raw-materials/export.csv"),
    ("post", "/api/v1/admin/raw-materials"),
    ("patch", "/api/v1/admin/raw-materials/1"),
    ("post", "/api/v1/admin/raw-materials/1/archive"),
    ("post", "/api/v1/admin/raw-materials/1/restore"),
    ("delete", "/api/v1/admin/raw-materials/1"),
])
def test_admin_calls_need_session(client, method, path):
    kwargs = {"json": {}} if method in ("post", "patch") else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_reading_needs_no_pin(client):
    assert client.get("/api/v1/raw-materials").json() == []


# -- Anlegen, Lesen, Ändern ---------------------------------------------------------

def test_create_read_update(client, auth):
    n = client.get("/api/v1/admin/raw-materials/next-number", headers=auth).json()["number"]
    r = client.post("/api/v1/admin/raw-materials", json=new(number=str(n), display_name="Margarine"), headers=auth)
    assert r.status_code == 201
    item = r.json()
    assert item["number"] == n
    got = client.get(f"/api/v1/raw-materials/{item['id']}").json()
    assert got["name"] == "Margarine A"
    r = client.patch(f"/api/v1/admin/raw-materials/{item['id']}", json={"tolerance": "10"}, headers=auth)
    assert r.status_code == 200
    assert client.get("/api/v1/raw-materials", params={"search": "margarine"}).json()


def test_tolerance_required(client, auth):
    data = new()
    data["tolerance"] = None
    assert client.post("/api/v1/admin/raw-materials", json=data, headers=auth).status_code == 400


def test_duplicate_name_409(client, auth):
    assert client.post("/api/v1/admin/raw-materials", json=new("Zucker"), headers=auth).status_code == 201
    r = client.post("/api/v1/admin/raw-materials", json=new("zucker"), headers=auth)
    assert r.status_code == 409
    assert r.json()["code"] == "name_taken"


def test_not_found_404(client):
    assert client.get("/api/v1/raw-materials/999").status_code == 404


# -- Archivieren, Löschen, Export ---------------------------------------------------

def test_archive_restore_delete(client, auth):
    item = client.post("/api/v1/admin/raw-materials", json=new("Salz"), headers=auth).json()
    base = f"/api/v1/admin/raw-materials/{item['id']}"
    assert client.post(base + "/archive", headers=auth).status_code == 200
    assert client.get("/api/v1/raw-materials").json() == []
    assert len(client.get("/api/v1/raw-materials", params={"include_archived": "true"}).json()) == 1
    assert client.post(base + "/restore", headers=auth).status_code == 200
    assert client.delete(base, headers=auth).status_code == 204
    assert client.get(f"/api/v1/raw-materials/{item['id']}").status_code == 404


def test_export_csv(client, auth):
    client.post("/api/v1/admin/raw-materials", json=new("Hefe"), headers=auth)
    r = client.get("/api/v1/admin/raw-materials/export.csv", headers=auth)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "Hefe" in r.content.decode("utf-8-sig")


def test_similar_names(client, auth):
    client.post("/api/v1/admin/raw-materials", json=new("Weizenmehl 550"), headers=auth)
    r = client.get("/api/v1/admin/raw-materials/similar", params={"name": "Weizenmehl 505"}, headers=auth)
    assert r.status_code == 200 and r.json()


# -- Seite und Datenbankfehler ------------------------------------------------------

@pytest.mark.parametrize("path", ["/admin", "/admin/login", "/admin/rohstoffe"])
def test_admin_page(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert "Probebetrieb" in r.text


def test_503_without_database(tmp_path, monkeypatch):
    db_file = tmp_path / "rezeptbuch.db"
    db_file.write_bytes(b"keine datenbank" * 100)
    monkeypatch.setenv("REZEPTBUCH_DB", str(db_file))
    with TestClient(app) as c:
        assert c.get("/api/v1/raw-materials").status_code == 503
