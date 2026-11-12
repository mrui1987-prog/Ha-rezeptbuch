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
    assert response.json() == {"status": "ok", "version": __version__}


def test_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "HA-Rezeptbuch" in response.text
