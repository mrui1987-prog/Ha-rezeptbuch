"""Tests für den Kennzeichnungspass-Leser.

Reine Funktionen laufen immer. Die Tests an echten PDFs laufen nur, wenn die Umgebungsvariable
KENNZEICHNUNGSPASS_PDF_DIR auf einen Ordner mit Pässen zeigt (die PDFs liegen nicht im Repo).
"""
import glob
import os
import sys

import pytest

pytest.importorskip("pdfplumber")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kennzeichnungspass as kp  # noqa: E402


# ---- Zahlen und Werte

@pytest.mark.parametrize("text,erwartet", [
    ("0,01", 0.01), ("12", 12.0), ("1.234,5", 1234.5), ("1.234", 1234.0), ("3054", 3054.0), ("0.5", 0.5),
    ("", None), ("abc", None), ("1,2,3", None),
])
def test_zahl(text, erwartet):
    assert kp.zahl(text) == erwartet


@pytest.mark.parametrize("text,erwartet", [
    ("281 kJ", (281.0, "kJ", False, "wert")),
    ("0,2 g", (0.2, "g", False, "wert")),
    ("< 0,01 g", (0.01, "g", True, "wert")),
    ("<0,1 g", (0.1, "g", True, "wert")),
    ("12 g", (12.0, "g", False, "wert")),
    ("keine Angabe", (None, None, False, "keine_angabe")),
    ("Keine Angabe", (None, None, False, "keine_angabe")),
    ("32 %", (32.0, "%", False, "wert")),
    ("viel", (None, None, False, "unlesbar")),
    ("", (None, None, False, "unlesbar")),
])
def test_parse_wert(text, erwartet):
    assert kp.parse_wert(text) == erwartet


def test_keine_angabe_ist_nicht_null():
    # „keine Angabe“ darf nie wie 0 behandelt werden
    z, _, _, status = kp.parse_wert("keine Angabe")
    assert z is None and status == "keine_angabe"


@pytest.mark.parametrize("gtin,ok", [
    ("04012850004004", True), ("04304823007052", True), ("03461181539487", True),
    ("04012850004005", False), ("1234", False), ("0401285000400A", False),
])
def test_gtin(gtin, ok):
    assert kp.gtin_pruefziffer_ok(gtin) is ok


# ---- Zeilengruppierung (Fehler 18.11.2026: „x“-Kästchen liegt 2,5 pt höher als „100ml“)

def _w(text, x0, top, hoehe=10.0, breite=20.0):
    return {"text": text, "x0": x0, "x1": x0 + breite, "top": top, "bottom": top + hoehe}


def test_zeilen_kaestchen_in_einer_zeile():
    ws = [_w("x", 161.6, 162.4, 9), _w("Referenzmenge", 31.2, 164.2), _w("100g", 175.8, 164.9),
          _w("x", 233.0, 162.5, 9), _w("100ml", 243.8, 165.6)]
    zs = kp._zeilen(ws)
    assert len(zs) == 1
    assert zs[0]["text"] == "Referenzmenge x 100g x 100ml"


def test_zeilen_getrennt_bei_normalem_abstand():
    zs = kp._zeilen([_w("a", 10, 100), _w("b", 10, 120)])
    assert [z["text"] for z in zs] == ["a", "b"]


def test_checkbox_wahl():
    z = kp._zeilen([_w("Referenzmenge", 31, 164), _w("100g", 175.8, 165), _w("x", 233.0, 162, 9, 6.8),
                    _w("100ml", 243.8, 165)])[0]
    assert kp._checkbox(z, ["100g", "100ml"]) == ["100ml"]
    z = kp._zeilen([_w("x", 161.6, 162, 9, 6.8), _w("100g", 175.8, 165), _w("100ml", 243.8, 165)])[0]
    assert kp._checkbox(z, ["100g", "100ml"]) == ["100g"]
    z = kp._zeilen([_w("100g", 175.8, 165), _w("100ml", 243.8, 165)])[0]
    assert kp._checkbox(z, ["100g", "100ml"]) == []


# ---- Zutaten

def _zeile(text, x0, top, hoehe=10.0):
    return kp._zeilen([_w(text, x0, top, hoehe)])[0]


def test_zutaten_keine_informationen():
    assert kp._zutaten([_zeile("keine Informationen verfügbar", 31, 400)], lambda m: None) is None


def test_zutaten_klartext():
    zs = [_zeile("Zutaten: Mehl (WEIZEN), Wasser,", 31, 400), _zeile("Salz.", 31, 412)]
    z = kp._zutaten(zs, lambda m: None)
    assert z == {"art": "PLAINTEXT", "text": "Mehl (WEIZEN), Wasser, Salz."}


def test_zutaten_tabelle_leerer_anteil():
    zs = [_zeile("Bezeichnung Anteil", 34, 493), _zeile("H-Vollmilch 3,5% Fett", 34, 510)]
    z = kp._zutaten(zs, lambda m: None)
    assert z["art"] == "STRUCTURED"
    assert z["eintraege"] == [{"name": "H-Vollmilch 3,5% Fett", "anteil_prozent": None, "ebene": 0}]


def test_zutaten_tabelle_mit_anteil_und_summe():
    warnungen = []
    kopf = _zeile("Bezeichnung Anteil", 34, 493)
    a = kp._zeilen([_w("Sultaninen", 34, 510), _w("99,5 %", 450, 510)])[0]
    b = kp._zeilen([_w("Öl", 34, 530), _w("0,5 %", 450, 530)])[0]
    z = kp._zutaten([kopf, a, b], warnungen.append)
    assert [e["anteil_prozent"]["wert"] for e in z["eintraege"]] == [99.5, 0.5]
    assert warnungen == []
    c = kp._zeilen([_w("Zucker", 34, 550), _w("5 %", 450, 550)])[0]
    kp._zutaten([kopf, a, b, c], warnungen.append)
    assert any("Summe der Zutatenanteile" in w for w in warnungen)


# ---- Zutatenliste gegen Allergenraster

def _allergene(*schluessel):
    return {"enthalten": [{"allergen": s, "schluessel": s, "oberbegriff_angekreuzt": True, "unter": []}
                          for s in schluessel], "kreuzkontamination": None}


def test_hinweis_allergen_in_zutaten_nicht_angekreuzt():
    z = {"art": "PLAINTEXT", "text": "WEIZENMEHL, Salz"}
    assert len(kp.zutaten_allergen_hinweise(z, _allergene("milch"))) == 1
    assert kp.zutaten_allergen_hinweise(z, _allergene("weizen")) == []


def test_hinweis_nur_bei_grossbuchstaben_und_bekannter_spalte():
    # Kleinschrift („Kokosmilch“) ist kein Allergenhinweis; „keine Angabe“ in der Spalte -> nichts zu vergleichen
    assert kp.zutaten_allergen_hinweise({"art": "PLAINTEXT", "text": "Kokosmilch, Sojaöl"}, _allergene()) == []
    assert kp.zutaten_allergen_hinweise({"art": "PLAINTEXT", "text": "MILCH"},
                                        {"enthalten": None, "kreuzkontamination": None}) == []


# ---- echte PDFs (optional)

PDF_DIR = os.environ.get("KENNZEICHNUNGSPASS_PDF_DIR")
PDFS = sorted(glob.glob(os.path.join(PDF_DIR, "*.pdf"))) if PDF_DIR else []


@pytest.mark.skipif(not PDFS, reason="KENNZEICHNUNGSPASS_PDF_DIR nicht gesetzt")
@pytest.mark.parametrize("pdf", PDFS, ids=[os.path.basename(p)[:40] for p in PDFS])
def test_pdf_selbstpruefung(pdf):
    import pruefe_leser
    r, probleme = pruefe_leser.pruefe(pdf)
    assert probleme == []
    assert r["produkt"]["titel"] and "?" not in r["produkt"]["titel"]
    assert r["lebensmittel"]["allergene"]["anzahl_zeilen"] == 26
