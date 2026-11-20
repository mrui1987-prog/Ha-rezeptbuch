"""HTTP-Schnittstelle von Add-on 3 (15.2) mit echtem Server auf einem freien Port."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

pytest.importorskip("pdfplumber")

from app import main as m  # noqa: E402
from app.testpdf import erzeuge_pdf  # noqa: E402


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), m.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _anfrage(port, methode, pfad, koerper=None, kopf=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    c.request(methode, pfad, body=koerper, headers=kopf or {})
    r = c.getresponse()
    daten = json.loads(r.read().decode("utf-8"))
    c.close()
    return r.status, daten


def test_gesundheit(server):
    code, d = _anfrage(server, "GET", "/v1/gesundheit")
    assert code == 200 and d["leser"] == {"kennzeichnungspass": 2}


def test_unbekannte_pfade(server):
    assert _anfrage(server, "GET", "/")[0] == 404
    assert _anfrage(server, "POST", "/v1/lesen/baeko-beleg", b"%PDF-1.4")[0] == 404
    assert _anfrage(server, "POST", "/v1/gibtsnicht", b"x")[0] == 404


def test_leer_und_kein_pdf(server):
    assert _anfrage(server, "POST", "/v1/lesen/kennzeichnungspass", b"")[0] == 400
    assert _anfrage(server, "POST", "/v1/lesen/kennzeichnungspass", b"hallo")[0] == 400


def test_zu_gross(server, monkeypatch):
    monkeypatch.setattr(m, "MAX_BYTES", 100)
    code, d = _anfrage(server, "POST", "/v1/lesen/kennzeichnungspass", b"%PDF-" + b"0" * 200)
    assert code == 413


def test_falsches_dokument(server):
    pdf = erzeuge_pdf(1)
    code, d = _anfrage(server, "POST", "/v1/lesen/kennzeichnungspass", pdf, {"X-Dateiname": "../ordner/rechnung.pdf"})
    assert code == 200 and d["status"] == "falsches_dokument"
    assert d["datei"]["name"] == "rechnung.pdf" and d["datei"]["bytes"] == len(pdf)
    assert d["datei"]["seiten"] == 1 and len(d["datei"]["sha256"]) == 64
    assert d["format_version"] == 1 and d["daten"] is None


def test_pass_mit_einer_seite_unlesbar(server):
    code, d = _anfrage(server, "POST", "/v1/lesen/kennzeichnungspass", erzeuge_pdf(1, betreff="Produktspezifikation"))
    assert code == 200 and d["status"] == "unlesbar" and d["warnungen"]


def test_kaputtes_pdf_wird_fehler(server):
    code, d = _anfrage(server, "POST", "/v1/lesen/kennzeichnungspass", b"%PDF-1.4\nkaputt")
    assert code == 200 and d["status"] == "fehler"


def test_zeitlimit(monkeypatch):
    erg = m.lese_im_prozess("kennzeichnungspass", erzeuge_pdf(1), None, zeitlimit=0.001)
    assert erg["status"] == "fehler" and "Zeit" in erg["meldung"]


def test_zu_viele_seiten():
    erg = m.lese_im_prozess("kennzeichnungspass", erzeuge_pdf(21, betreff="Produktspezifikation"), None)
    assert erg["status"] == "unlesbar" and erg["seiten"] == 21


def test_sauberer_name():
    assert m._sauberer_name("C:\\x\\y.pdf") == "y.pdf"
    assert m._sauberer_name("") is None and m._sauberer_name(None) is None


def test_zweiseitiger_pass_ohne_inhalt_unlesbar_mit_dateiname(server):
    pdf = erzeuge_pdf(2, betreff="Produktspezifikation")
    code, d = _anfrage(server, "POST", "/v1/lesen/kennzeichnungspass", pdf, {"X-Dateiname": "pass.pdf"})
    assert code == 200 and d["status"] == "unlesbar" and d["warnungen"]
    assert d["daten"]["schema"] == 2 and d["daten"]["quelle"]["datei"] == "pass.pdf"
