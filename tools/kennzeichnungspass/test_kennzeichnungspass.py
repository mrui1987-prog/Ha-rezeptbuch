"""Tests für den Kennzeichnungspass-Leser (Testleser VC04-e).

Reine Funktionen laufen immer. Die Tests an echten PDFs laufen nur, wenn KENNZEICHNUNGSPASS_PDF_DIR
auf einen Ordner mit Pässen zeigt (die PDFs liegen nicht im Repo).
"""
import glob
import os
import sys

import pytest

pytest.importorskip("pdfplumber")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kennzeichnungspass as kp  # noqa: E402
import zwischenstruktur as zs  # noqa: E402


def _w(text, x0, top, hoehe=10.0, breite=20.0):
    return {"text": text, "x0": x0, "x1": x0 + breite, "top": top, "bottom": top + hoehe}


# Fehler 18.11.2026: „Referenzmenge 100g x 100ml“ – das Kästchen-x liegt höher als der Text und riss die Zeile
def test_zeilen_kaestchen_bleibt_in_der_zeile():
    ws = [_w("Referenzmenge", 31, 164.2), _w("100g", 175.8, 164.9), _w("x", 233.0, 162.4, 9),
          _w("100ml", 243.8, 167.5)]
    z = kp._zeilen(ws)
    assert len(z) == 1 and z[0]["text"] == "Referenzmenge 100g x 100ml"


def test_zeilen_getrennt_bei_normalem_abstand():
    assert [z["text"] for z in kp._zeilen([_w("a", 10, 100), _w("b", 10, 120)])] == ["a", "b"]


@pytest.mark.parametrize("text,erwartet", [
    ("281 kJ", (True, 281.0, "kJ", False)), ("< 0,01 g", (True, 0.01, "g", True)),
    ("0,2 g", (True, 0.2, "g", False)), ("keine Angabe", (False, None, None, False)),
])
def test_zahl(text, erwartet):
    r = kp._zahl(text)
    assert (r["angegeben"], r["wert"], r["einheit"], r["kleiner_als"]) == erwartet


def test_keine_angabe_ist_nicht_null():
    r = kp._zahl("keine Angabe")
    assert r["angegeben"] is False and r["wert"] is None


def _allergene(*keys):
    return {"enthalten": [{"key": k, "unter": []} for k in keys], "kreuzkontamination": None}


def test_hinweis_allergen_in_zutaten_nicht_angekreuzt():
    z = {"struktur": "PLAINTEXT", "text": "WEIZENMEHL, Salz", "eintraege": []}
    assert len(zs._zutaten_allergen_hinweise(z, _allergene("milch"))) == 1
    assert zs._zutaten_allergen_hinweise(z, _allergene("weizen")) == []


def test_hinweis_nur_grossbuchstaben_und_nur_bei_bekannter_spalte():
    klein = {"struktur": "PLAINTEXT", "text": "Kokosmilch, Sojaöl", "eintraege": []}
    assert zs._zutaten_allergen_hinweise(klein, _allergene()) == []
    gross = {"struktur": "PLAINTEXT", "text": "MILCH", "eintraege": []}
    assert zs._zutaten_allergen_hinweise(gross, {"enthalten": None, "kreuzkontamination": None}) == []


def test_hinweis_bei_zutatenliste_mit_unterzutaten():
    z = {"struktur": "STRUCTURED", "text": None, "eintraege": [
        {"name": "Mehl", "unterzutaten": [{"name": "ROGGENMEHL", "unterzutaten": []}]}]}
    assert len(zs._zutaten_allergen_hinweise(z, _allergene())) == 1


PDF_DIR = os.environ.get("KENNZEICHNUNGSPASS_PDF_DIR")
PDFS = sorted(glob.glob(os.path.join(PDF_DIR, "*.pdf"))) if PDF_DIR else []


@pytest.mark.skipif(not PDFS, reason="KENNZEICHNUNGSPASS_PDF_DIR nicht gesetzt")
def test_selbstpruefung_an_echten_pdfs(capsys):
    import pruefe_leser
    assert pruefe_leser.main(PDF_DIR) == 0, capsys.readouterr().out
