"""Prüft, dass der Webserver startet und antwortet (läuft im GitHub-Testlauf)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app import __version__  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    # Ohne gestartete Waagen-Anbindung meldet Health MQTT „unavailable“, Status bleibt 200 (Modul 08, K08-7)
    assert response.json() == {"status": "ok", "version": __version__, "mqtt": "unavailable"}


def test_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "HA-Rezeptbuch" in response.text


def test_startup_creates_database(tmp_path, monkeypatch):
    db_file = tmp_path / "rezeptbuch.db"
    monkeypatch.setenv("REZEPTBUCH_DB", str(db_file))
    with TestClient(app) as started:
        assert started.get("/api/v1/health").json()["status"] == "ok"
        assert app.state.db.execute("PRAGMA user_version").fetchone()[0] >= 1
    assert db_file.exists()


def test_startup_with_broken_database_reports_error(tmp_path, monkeypatch):
    db_file = tmp_path / "rezeptbuch.db"
    db_file.write_bytes(b"keine datenbank" * 100)
    monkeypatch.setenv("REZEPTBUCH_DB", str(db_file))
    with TestClient(app) as started:
        response = started.get("/api/v1/health")
        assert response.status_code == 503
        assert response.json()["status"] == "error"
