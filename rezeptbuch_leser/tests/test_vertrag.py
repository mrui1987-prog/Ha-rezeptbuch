from app import __version__
from app.vertrag import FALSCHES_DOKUMENT, FEHLER, OK, UNLESBAR, antwort, gesundheit

DATEI = {"name": "a.pdf", "bytes": 10, "sha256": "x", "seiten": 2}
PFLICHT = {"format", "format_version", "addon_version", "leser", "leser_schema", "datei",
           "status", "meldung", "daten", "warnungen", "plausibilitaet"}


def test_gesundheit():
    g = gesundheit()
    assert g["format"] == "rezeptbuch-leser" and g["format_version"] == 1
    assert g["addon_version"] == __version__ and g["leser"] == {"kennzeichnungspass": 2}


def test_antwort_pflichtfelder():
    a = antwort("kennzeichnungspass", DATEI, {"status": OK, "daten": {"x": 1}})
    assert set(a) == PFLICHT and a["status"] == OK and a["leser_schema"] == 2
    assert a["warnungen"] == [] and a["plausibilitaet"] == []


def test_ok_mit_warnung_wird_unlesbar():
    a = antwort("kennzeichnungspass", DATEI, {"status": OK, "warnungen": ["w"]})
    assert a["status"] == UNLESBAR


def test_unbekannter_status_wird_fehler():
    assert antwort("kennzeichnungspass", DATEI, {"status": "jein"})["status"] == FEHLER


def test_plausibilitaet_sperrt_nicht():
    a = antwort("kennzeichnungspass", DATEI, {"status": OK, "plausibilitaet": ["p"]})
    assert a["status"] == OK and a["plausibilitaet"] == ["p"]


def test_falsches_dokument_bleibt():
    assert antwort("kennzeichnungspass", DATEI, {"status": FALSCHES_DOKUMENT})["status"] == FALSCHES_DOKUMENT
