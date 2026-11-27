"""Tests für den BÄKO-Belegleser mit erfundenen Belegen (Aufbau wie echt, docs/bestand.md 8).

Echte Belege (Kundendaten) liegen nicht im Repo: Test unten nur mit BAEKO_BELEG_PDF_DIR.
"""
import glob
import os
import sys

import pytest

pytest.importorskip("pdfplumber")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "leser"))

import baeko_beleg as bb  # noqa: E402
from app.beleg_mantel import lese_baeko_beleg  # noqa: E402
from app.testpdf import beispiel_rechnung, beleg_pdf, erzeuge_pdf  # noqa: E402


@pytest.fixture
def lies(tmp_path):
    def _lies(inhalt, mantel=False):
        pfad = tmp_path / "beleg.pdf"
        pfad.write_bytes(inhalt)
        return lese_baeko_beleg(pfad) if mantel else bb.lese_beleg(pfad)
    return _lies


def _pos(**kw):
    p = {"wg": "103", "art": "200001", "anzahl": "1 SCK a 25 KG", "bez": ["Roggenmehl Muster"],
         "menge": "25,000", "me": "KG", "preis": "0,6800", "pe": "EIN", "netto": "17,00", "mwst": 7}
    p.update(kw)
    return p


def test_beispielrechnung_vollstaendig(lies):
    d = lies(beispiel_rechnung())
    assert d["warnungen"] == [] and d["belegart"] == "rechnung" and d["belegnummer"] == "RE0000001"
    assert d["belegdatum"] == "2026-02-01" and d["haendler"] == "BÄKO Musterstadt eG"
    a, b = d["positionen"]
    assert (a["artikelnummer"], a["menge_tausendstel"], a["mengeneinheit"], a["preis_zehntausendstel_euro"],
            a["preiseinheit"], a["netto_cent"], a["mwst_prozent"]) == ("100001", 50000, "KG", 599000, "HDT", 2995, 7)
    assert a["lieferung"] == {"art": "Hauptorder", "lieferschein": "LI0000001", "lieferdatum": "2026-02-02",
                              "zusatz": "Zufuhr"}
    assert a["auftrag"] == {"referenz": "CL0000001", "auftrag": "AT0000001", "auftragsdatum": "2026-02-01"}
    assert b["bezeichnung"] == "Limo 0,5l Glas" and b["warengruppe"] == "1001"
    assert d["summen"]["netto_cent"] == d["summen"]["gelesen_netto_cent"] == 4026
    assert {w["warengruppe"] for w in d["warengruppen"]} == {"101", "1001"}


def test_kopf_ohne_kundenname(lies):
    d = lies(beispiel_rechnung())
    assert "Musterbäckerei" not in str({k: v for k, v in d.items() if k != "positionen"})
    assert d["ihre_referenz"] is None  # steht nur im Abschnitt, nicht im Kopf


def test_summe_falsch_ist_unlesbar(lies):
    d = lies(beispiel_rechnung(netto_summe=4027))
    assert any("Netto-Summe" in w for w in d["warnungen"])
    assert lies(beispiel_rechnung(netto_summe=4027), mantel=True)["status"] == "unlesbar"


def test_seitenumbruch_mit_uebertrag(lies):
    pos = [_pos(art=f"20000{i}") for i in range(1, 4)]
    d = lies(beleg_pdf("rechnung", pos, umbruch_nach=2))
    assert d["warnungen"] == [] and len(d["positionen"]) == 3 and d["seiten"] == 3
    d = lies(beleg_pdf("rechnung", pos, umbruch_nach=2, uebertrag_falsch=True))
    assert any("Übertrag" in w for w in d["warnungen"])


def test_skonto_je_position(lies):
    p = _pos(skonto=("- 2 % Skonto (vor Steuer / Rabatt)", "-0,34"))
    d = lies(beleg_pdf("rechnung", [p, _pos(art="200002")]))
    assert d["warnungen"] == []
    a = d["positionen"][0]
    assert a["skonto"]["cent"] == -34 and a["netto_nach_konditionen_cent"] == 1666
    assert d["summen"]["gelesen_netto_cent"] == 1666 + 1700


def test_wert_bei_umbruch_zwischen_skonto_und_summe():
    leser = bb._Leser()
    p = {"netto_cent": 2350, "skonto": {"cent": -47}, "netto_nach_konditionen_cent": None}
    assert leser._wert(p) == 2303


def test_auftragsbestaetigung_bestellartikel_und_gebinde(lies):
    pos = [
        {"pos": 1, "art": "300001", "bez": ["Apfelwürfel Muster", "im Beutel 5kg"], "klammer": "(1 KT)",
         "gebinde": "1 VE à 3 BT", "menge": "3,000", "me": "BT", "preis": "8,49", "pe": "EIN", "netto": "25,47",
         "mwst": 7},
        {"pos": 2, "art": "300002", "bez": ["Kirschwasser Muster"], "b": True, "klammer": "(1 KN)",
         "bestell": ["----------", "Bestell-Artikel", "Lieferung erfolgt, sobald verfügbar", "----------"],
         "gebinde": "1 VE à 5 L", "menge": "5,000", "me": "L", "preis": "11,06", "pe": "EIN", "netto": "55,30",
         "mwst": 19},
    ]
    d = lies(beleg_pdf("auftragsbestaetigung", pos))
    assert d["warnungen"] == [] and d["belegart"] == "auftragsbestaetigung"
    assert d["lieferdatum_voraussichtlich"] == "2026-02-03"
    a, b = d["positionen"]
    assert a["pos"] == 1 and a["gebinde_text"] == "1 VE à 3 BT" and a["gebinde_klammer"] == "(1 KT)"
    assert a["bezeichnung"] == "Apfelwürfel Muster im Beutel 5kg" and not a["bestellartikel"]
    assert b["bestellartikel"] and "Bestell-Artikel" in b["bestell_hinweis"]


def test_ihre_artikelnummer_gefuellt_ist_unlesbar(lies):
    pos = [{"pos": 1, "art": "300001", "bez": ["Muster"], "menge": "1,000", "me": "KG", "preis": "1,00",
            "pe": "EIN", "netto": "1,00", "mwst": 7}]
    d = lies(beleg_pdf("auftragsbestaetigung", pos, ueberdruck=[(1, 55.0, 300, "4711")]))
    assert any("Ihre Art.-Nr." in w for w in d["warnungen"])


def test_gutschrift_negativ_mit_grundtext(lies):
    pos = [{"pos": 1, "art": "400001", "bez": ["Quark Muster"], "klammer": "(-3 EI)", "gebinde": "3 VE à 5 KG",
            "zusatz": ["Rücknahme wg. doppelter Lieferung"], "menge": "-15,000", "me": "KG", "preis": "2,2800",
            "pe": "EIN", "netto": "-34,20", "mwst": 7}]
    abschn = {0: ["Rücknahme LS.-Nr.: LI0000009, Lieferdatum: 23.12.2025 / Musterstadt",
                  "Auftrag: RN0000001 vom 20.12.2025"]}
    d = lies(beleg_pdf("gutschrift", pos, abschnitte=abschn))
    assert d["warnungen"] == [] and d["belegart"] == "gutschrift"
    p = d["positionen"][0]
    assert p["menge_tausendstel"] == -15000 and p["netto_cent"] == -3420
    assert p["zusatztext"] == ["Rücknahme wg. doppelter Lieferung"]
    assert p["lieferung"]["art"] == "Rücknahme" and p["auftrag"]["auftrag"] == "RN0000001"


def test_packungs_preiseinheit_mit_klammer(lies):
    # Echter Fall AT1003549: 120 ST, Preis 27,95 je KT, Klammer (2 KT) -> Netto 55,90
    d = lies(beleg_pdf("rechnung", [_pos(menge="120,000", me="ST", preis="27,9500", pe="KT",
                                         netto="55,90", klammer="(2 KT)")]))
    assert not d["warnungen"] and d["plausibilitaet"] == []
    p = d["positionen"][0]
    assert p["preiseinheit"] == "KT" and p["netto_cent"] == 5590 and p["gebinde_klammer"] == "(2 KT)"


def test_packungs_preiseinheit_falsches_netto_wird_gemeldet(lies):
    d = lies(beleg_pdf("rechnung", [_pos(menge="120,000", me="ST", preis="27,9500", pe="KT",
                                         netto="60,00", klammer="(2 KT)")]))
    assert any("weicht" in w for w in d["plausibilitaet"])


def test_packungs_preiseinheit_ohne_klammer_nicht_pruefbar(lies):
    d = lies(beleg_pdf("rechnung", [_pos(pe="KAR")]))
    assert any("nicht prüfbar" in w for w in d["plausibilitaet"])


def test_ueberdruck_wird_getrennt_und_gemeldet(lies):
    # Zeile 2 der Bezeichnung von Position 1 liegt bei top 312; "M32" darüber gedruckt
    pos = [_pos(bez=["Faltenbeutel Muster", "gruen"]), _pos(art="200002")]
    d = lies(beleg_pdf("rechnung", pos, ueberdruck=[(1, 194.0, 312, "M32")]))
    assert d["warnungen"] == []
    assert d["positionen"][0]["bezeichnung_zeilen"] == ["Faltenbeutel Muster", "gruen", "M32"]
    assert any("übereinander gedruckt" in p for p in d["plausibilitaet"])


def test_ueberdruck_auf_zeile_des_naechsten_artikels(lies):
    pos = [_pos(), _pos(art="200002")]
    # Position 2 beginnt bei top 312
    d = lies(beleg_pdf("rechnung", pos, ueberdruck=[(1, 194.0, 312, "M32")]))
    assert d["warnungen"] == []
    assert d["positionen"][0]["bezeichnung_zeilen"][-1] == "M32"
    assert d["positionen"][1]["bezeichnung"] == "Roggenmehl Muster"


def test_doppeldruck_wird_verworfen(lies):
    pos = [_pos(bez=["Faltenbeutel", "(ehem. 59)"])]
    d = lies(beleg_pdf("rechnung", pos, ueberdruck=[(1, 195.0, 312, "(ehem. 59)")]))
    assert d["warnungen"] == [] and d["plausibilitaet"] == []
    assert d["positionen"][0]["bezeichnung"] == "Faltenbeutel (ehem. 59)"


def test_kein_baeko_beleg(lies):
    assert lies(erzeuge_pdf(1, text="Irgendwas"), mantel=True)["status"] == "falsches_dokument"


def test_mantel_ok(lies):
    e = lies(beispiel_rechnung(), mantel=True)
    assert e["status"] == "ok" and e["daten"]["schema"] == 1 and e["seiten"] == 2


@pytest.mark.parametrize("text,stellen,wert", [("1.000,000", 3, 1000000), ("-34,20", 2, -3420),
                                                ("0,8590", 4, 8590), ("59,9000", 4, 599000)])
def test_ganzzahlen(text, stellen, wert):
    assert bb._ganz(text, stellen) == wert


def test_zu_viele_nachkommastellen():
    with pytest.raises(ValueError):
        bb._ganz("1,234", 2)


PDF_DIR = os.environ.get("BAEKO_BELEG_PDF_DIR")
PDFS = sorted(glob.glob(os.path.join(PDF_DIR, "*.pdf"))) if PDF_DIR else []


@pytest.mark.skipif(not PDFS, reason="BAEKO_BELEG_PDF_DIR nicht gesetzt")
@pytest.mark.parametrize("pfad", PDFS)
def test_echte_belege(pfad):
    e = lese_baeko_beleg(pfad)
    if e["status"] == "falsches_dokument":
        pytest.skip("kein BÄKO-Beleg mit Text (z. B. Scan)")
    assert e["status"] == "ok", e.get("warnungen")
    s = e["daten"]["summen"]
    assert s["netto_cent"] == s["gelesen_netto_cent"]


def test_bereich_und_seitenmasse(lies):
    """Leser 0.2.0: jede Position kennt ihren Bereich auf der Seite (Vorschaubild der Zuordnung)."""
    from app.testpdf import beispiel_rechnung
    import tempfile, pathlib
    from app.leser.baeko_beleg import lese_beleg
    with tempfile.TemporaryDirectory() as tmp:
        pfad = pathlib.Path(tmp) / "r.pdf"
        pfad.write_bytes(beispiel_rechnung())
        d = lese_beleg(pfad)
    assert d["seitenmasse"] and d["seitenmasse"][0]["breite"] > 0
    oben = -1
    for p in d["positionen"]:
        b = p["bereich"]
        assert b["seite"] >= 1 and b["unten"] > b["oben"]
        if b["seite"] == 1:
            assert b["oben"] > oben
            oben = b["oben"]
