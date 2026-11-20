import pytest

pytest.importorskip("pdfplumber")

from app import worker  # noqa: E402


def test_selbsttest():
    assert worker.selbsttest() == 0


def test_unbekannter_leser():
    assert worker.lese("gibtsnicht", "x.pdf")["status"] == "fehler"
