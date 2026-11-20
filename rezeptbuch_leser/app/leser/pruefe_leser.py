#!/usr/bin/env python3
"""Selbstprüfung des Testlesers gegen die Beispiel-PDFs (keine Daten werden verändert).

Aufruf:  python3 -I pruefe_leser.py ordner_mit_pdfs
Prüft: (1) Dateiname enthält dasselbe Datum wie 'Gültig ab', (2) Produktnummer/Datenlink-ID gesetzt,
(3) Anzahl gelesener Kreuze = Anzahl gesetzter Allergen-Flags, (4) 26 Allergenzeilen,
(5) gleiche PDFs (gleiche Produktnummer + Datenlink-ID) liefern gleiche Daten,
(6) feste Stichproben (von Hand mit dem gerenderten PDF verglichen),
(7) Zwischenstruktur Schema 2: gleiche Allergene, keine Warnungen, keine Verstöße gegen XSD-Regeln.
"""
import json
import re
import sys
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kennzeichnungspass import lese_pdf_roh as lese_pdf  # noqa: E402
from zwischenstruktur import aus_roh  # noqa: E402

# Von Hand gegen das gerenderte PDF geprüft (18.11.2026)
STICHPROBEN = {
    "10182549": {  # Backtivat (CSM)
        "enthalten": {"gluten", "weizen", "milch"},
        "kreuz": {"gerste", "hafer", "eier", "soja", "sellerie"},
        "naehrwerte": None, "zutaten": None,
    },
    "100518": {  # Fondant (Back Europ)
        "enthalten": {"sulfit"}, "kreuz": set(),
        "kreuz_angegeben": False,
    },
    "100125": {  # Haselnusskerne
        "enthalten": {"schalenfruechte", "haselnuesse"}, "kreuz": set(),
        "kreuz_angegeben": False,
        "salz_kleiner_als": True,
    },
    "10116864": {  # allesgute Das Urige (CSM) – Weizen nur bei Kreuzkontamination, Oberbegriff nicht
        "enthalten": {"gluten", "weizen", "roggen", "gerste", "hafer"},
        "kreuz": {"weizen", "eier", "soja", "milch", "sesam", "lupinen"},
        "naehrwerte": None, "zutaten": None,
    },
    "85050": {  # UNIFERM Kondikrem
        "enthalten": {"milch"}, "kreuz": {"gluten", "eier", "soja", "sesam", "lupinen"},
        "naehrwerte": None, "zutaten": None,
    },
    "203048114": {  # Dawn Himbeere
        "enthalten": set(), "kreuz": {"gluten", "weizen", "eier", "milch"},
        "enthalten_angegeben": False,
    },
}


def main(ordner):
    fehler = []
    ergebnisse = []
    for pdf_pfad in sorted(Path(ordner).glob("*.pdf")):
        with pdfplumber.open(pdf_pfad) as pdf:
            if (pdf.metadata.get("Subject") or "").strip() != "Produktspezifikation":
                print(f"übersprungen (kein Kennzeichnungspass): {pdf_pfad.name}")
                continue
        d = lese_pdf(pdf_pfad)
        ergebnisse.append(d)
        name = f"{d.get('produktnummer')} ({pdf_pfad.name[:20]}…)"
        # (1) Datum im Dateinamen
        m = re.search(r"(\d{4}-\d{2}-\d{2})", pdf_pfad.name)
        if m and d.get("gueltig_ab") != m.group(1):
            fehler.append(f"{name}: gültig ab {d.get('gueltig_ab')} ≠ Dateiname {m.group(1)}")
        # (2) Pflichtfelder
        for feld in ("produktnummer", "datenlink_id", "datengeber", "gueltig_ab", "bezeichnung"):
            if not d.get(feld):
                fehler.append(f"{name}: Feld {feld} fehlt")
        # (3)/(4) Kreuze und Zeilen
        with pdfplumber.open(pdf_pfad) as pdf:
            kreuze = sum(1 for w in pdf.pages[0].extract_words()
                         if w["text"] in ("X", "x") and w["x0"] >= 400 and w["top"] > 290)
        flags = sum(a["enthalten"] + a["kreuzkontamination"] for a in d["allergene"].values())
        if kreuze != flags:
            fehler.append(f"{name}: {kreuze} Kreuze im PDF, aber {flags} Flags gelesen")
        if len(d["allergene"]) != 26:
            fehler.append(f"{name}: {len(d['allergene'])} Allergenzeilen statt 26")
        if d["warnungen"]:
            fehler.append(f"{name}: Warnungen {d['warnungen']}")
        # (7) Schema 2: gleiche Kreuze, keine Warnungen, XSD-Regeln
        z = aus_roh(d)
        al = z["lebensmittel"]["allergene"]
        n2 = sum(len(e["unter"]) + (0 if e.get("oberbegriff_nicht_angekreuzt") else 1)
                 for sp in al.values() if sp for e in sp)
        if n2 != flags:
            fehler.append(f"{name}: Schema 2 hat {n2} Allergene, Rohdaten {flags}")
        if z["warnungen"]:
            fehler.append(f"{name}: Schema-2-Warnungen {z['warnungen']}")
        xsd = [p for p in z["plausibilitaet"] if "laut XSD" in p]
        if xsd:
            fehler.append(f"{name}: verstößt gegen XSD-Regel: {xsd}")
        # (6) Stichproben
        s = STICHPROBEN.get(d.get("produktnummer"))
        if s:
            enth = {k for k, v in d["allergene"].items() if v["enthalten"]}
            kreuz = {k for k, v in d["allergene"].items() if v["kreuzkontamination"]}
            if "enthalten" in s and enth != s["enthalten"]:
                fehler.append(f"{name}: enthalten {sorted(enth)} ≠ {sorted(s['enthalten'])}")
            if "kreuz" in s and kreuz != s["kreuz"]:
                fehler.append(f"{name}: Kreuzkontamination {sorted(kreuz)} ≠ {sorted(s['kreuz'])}")
            for schl in ("kreuz_angegeben", "enthalten_angegeben"):
                if schl in s:
                    ist = d["allergene_status"]["kreuzkontamination_angegeben" if schl == "kreuz_angegeben"
                                                else "enthalten_angegeben"]
                    if ist != s[schl]:
                        fehler.append(f"{name}: {schl} = {ist}, erwartet {s[schl]}")
            if "naehrwerte" in s and (d["naehrwerte"] is None) != (s["naehrwerte"] is None):
                fehler.append(f"{name}: Nährwerte vorhanden/nicht vorhanden stimmt nicht")
            if s.get("salz_kleiner_als") and not d["naehrwerte"]["werte"]["salz"]["kleiner_als"]:
                fehler.append(f"{name}: '< 0,01 g' beim Salz nicht erkannt")
    # (5) Duplikate
    nach_id = {}
    for d in ergebnisse:
        nach_id.setdefault((d.get("produktnummer"), d.get("datenlink_id")), []).append(d)
    for schluessel, liste in nach_id.items():
        if len(liste) > 1:
            ohne = [{k: v for k, v in x.items() if k != "datei"} for x in liste]
            if any(json.dumps(o, sort_keys=True) != json.dumps(ohne[0], sort_keys=True) for o in ohne[1:]):
                fehler.append(f"{schluessel}: {len(liste)} PDFs desselben Produkts liefern unterschiedliche Daten")
    print(f"{len(ergebnisse)} PDFs gelesen, {len(nach_id)} verschiedene Produkte")
    if fehler:
        print("FEHLER:")
        for f in fehler:
            print(" -", f)
        return 1
    print("alle Prüfungen bestanden")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
