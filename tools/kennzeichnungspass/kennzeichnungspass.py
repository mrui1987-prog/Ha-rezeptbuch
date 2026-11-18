#!/usr/bin/env python3
"""Testleser für datenlink-Kennzeichnungspässe (PDF) -> Zwischenstruktur (JSON).

Nur Versuch (VC04-e, Schritt 1): keine Datenbank, kein Repo. Liest nur, ändert nichts.
Aufruf:  python3 -I kennzeichnungspass.py datei1.pdf [datei2.pdf ...] [-o ausgabeordner] [--roh]
         Standard: Zwischenstruktur Schema 2 (zwischenstruktur.py); --roh: Rohdaten Schema 1.

Grundsatz: Es wird nichts erfunden. Was nicht eindeutig gelesen werden kann,
landet in "warnungen" statt in den Daten.
"""
import json
import re
import sys
from pathlib import Path

import pdfplumber

SCHEMA_VERSION = 1

# Kanonische Allergene: erstes Wort der Zeile -> (Schlüssel, Gruppe)
ALLERGENE = {
    "Glutenhaltiges": ("gluten", None),
    "Weizen": ("weizen", "gluten"),
    "Roggen": ("roggen", "gluten"),
    "Gerste": ("gerste", "gluten"),
    "Hafer": ("hafer", "gluten"),
    "Krebstiere": ("krebstiere", None),
    "Eier": ("eier", None),
    "Fische": ("fische", None),
    "Erdnüsse": ("erdnuesse", None),
    "Soja": ("soja", None),
    "Milch": ("milch", None),
    "Schalenfrüchte": ("schalenfruechte", None),
    "Mandeln": ("mandeln", "schalenfruechte"),
    "Haselnüsse": ("haselnuesse", "schalenfruechte"),
    "Walnüsse": ("walnuesse", "schalenfruechte"),
    "Kaschunüsse": ("kaschunuesse", "schalenfruechte"),
    "Pecannüsse": ("pecannuesse", "schalenfruechte"),
    "Paranüsse": ("paranuesse", "schalenfruechte"),
    "Pistazien": ("pistazien", "schalenfruechte"),
    "Makadamianüsse": ("makadamianuesse", "schalenfruechte"),
    "Sellerie": ("sellerie", None),
    "Senf": ("senf", None),
    "Sesamsamen": ("sesam", None),
    "Schwefeldioxid": ("sulfit", None),
    "Lupinen": ("lupinen", None),
    "Weichtiere": ("weichtiere", None),
}

NAEHRWERT_SCHLUESSEL = [
    ("Energie (Kilojoule)", "energie_kj"),
    ("Energie (Kilokalorien", "energie_kcal"),
    ("davon gesättigte Fettsäuren", "davon_gesaettigt"),
    ("davon Zucker", "davon_zucker"),
    ("Fett", "fett"),
    ("Kohlenhydrate", "kohlenhydrate"),
    ("Ballaststoffe", "ballaststoffe"),
    ("Eiweiß", "eiweiss"),
    ("Salz", "salz"),
]

KEINE_INFO = "keine Informationen verfügbar"
SPALTE_TRENNER_X = 490  # links davon: "in Rezeptur / als Zutat enthalten", rechts: Kreuzkontamination
LINKS_RECHTS_X = 425    # Kopfbereich Seite 1: links Beschriftung/Werte, rechts Datenlink-ID/GTIN/Gültig ab


def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def _zeilen(woerter, toleranz=5.0):
    """Wörter -> Zeilen (jeweils nach x sortiert), Zeilen nach y sortiert.
    Gruppiert nach der senkrechten Mitte der Wörter (nicht nach Oberkante), damit
    Zeichen wie das Kreuz 'x' (höher als der Text) in derselben Zeile bleiben."""
    mitte = lambda w: (w["top"] + w["bottom"]) / 2
    woerter = sorted(woerter, key=lambda w: (mitte(w), w["x0"]))
    zeilen = []
    for w in woerter:
        if zeilen and abs(mitte(w) - zeilen[-1]["mitte0"]) <= toleranz:
            zeilen[-1]["w"].append(w)
            zeilen[-1]["mitte0"] = mitte(w)  # gegen das zuletzt aufgenommene Wort vergleichen (Kette)
        else:
            zeilen.append({"mitte0": mitte(w), "w": [w]})
    for z in zeilen:
        z["w"].sort(key=lambda w: w["x0"])
        z["top"] = min(w["top"] for w in z["w"])
        z["bottom"] = max(w["bottom"] for w in z["w"])
        z["text"] = _norm(" ".join(w["text"] for w in z["w"]))
    return zeilen


def _zahl(text):
    """'61,0 g' / '< 0,01 g' / '0g' / '2629 kJ' / 'keine Angabe' -> dict."""
    t = _norm(text)
    if t.lower().startswith("keine angabe"):
        return {"angegeben": False, "wert": None, "einheit": None, "kleiner_als": False, "text": t}
    m = re.fullmatch(r"(<)?\s*([\d.]+(?:,\d+)?)\s*(kJ|kcal|g|mg|µg|ml)", t)
    if not m:
        return {"angegeben": None, "wert": None, "einheit": None, "kleiner_als": False, "text": t}
    wert = float(m.group(2).replace(".", "").replace(",", ".")) if "," in m.group(2) else float(m.group(2).replace(".", ""))
    return {"angegeben": True, "wert": wert, "einheit": m.group(3), "kleiner_als": bool(m.group(1)), "text": t}


def _datum(text):
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _senkrechter_text(seite, ab_x=400):
    """Gedrehter Text (von unten nach oben gelesen), z. B. 'Kreuzkontamination: keine Angabe' im Kasten."""
    spalten = {}
    for c in seite.chars:
        if not c.get("upright", True) and c["x0"] >= ab_x:
            spalten.setdefault(round(c["x0"] / 5), []).append(c)
    return [_norm("".join(c["text"] for c in sorted(v, key=lambda c: -c["top"]))) for v in spalten.values()]


def lese_seite1(seite, warnungen):
    woerter = [w for w in seite.extract_words() if w["x0"] >= 100]  # x < 100: gedrehter Hinweistext
    zeilen = _zeilen(woerter)
    kopf = {}

    def wert_rechts_von(zeile, ab_x, bis_x=10000):
        return _norm(" ".join(w["text"] for w in zeile["w"] if ab_x <= w["x0"] < bis_x))

    # Linke Seite (x < 425) und rechte Seite getrennt in Zeilen bringen
    links = _zeilen([w for w in woerter if w["x0"] < LINKS_RECHTS_X])
    rechts = _zeilen([w for w in woerter if w["x0"] >= LINKS_RECHTS_X])

    # Datengeber/PLZ/Land stehen oberhalb des rechten Blocks (ID, GTIN): lange Firmennamen
    # („Vandemoortele Europe NV, Deutsche Zweigniederlassung“) laufen bis in die rechte Hälfte.
    for z in _zeilen([w for w in woerter if w["top"] < 135]):
        t = z["text"]
        if t.startswith("Datengeber"):
            kopf["datengeber"] = wert_rechts_von(z, 260)
        elif t.startswith("PLZ, Ort"):
            kopf["plz_ort"] = wert_rechts_von(z, 260)
        elif t.startswith("Land"):
            kopf["land"] = wert_rechts_von(z, 260)
    for z in links:
        t = z["text"]
        if t.startswith("Produktnummer"):
            kopf["produktnummer"] = wert_rechts_von(z, 260, LINKS_RECHTS_X)
    for z in rechts:
        t = z["text"]
        if t.startswith("Datenlink-ID"):
            kopf["datenlink_id"] = _norm(t[len("Datenlink-ID"):])
        elif t.startswith("GTIN"):
            kopf["gtin"] = _norm(t[len("GTIN"):])
            if re.fullmatch(r"[\d ]+", kopf["gtin"]):
                kopf["gtin"] = kopf["gtin"].replace(" ", "")
    rechts_text = " ".join(z["text"] for z in rechts)
    kopf["gueltig_ab"] = _datum(rechts_text)

    # Produktkennung (Freitext links, zwischen Produktnummer und "Die Richtigkeit")
    stop = next((z["top"] for z in links if z["text"].startswith("Die Richtigkeit")), 10000)
    start = next((z["top"] for z in links if z["text"].startswith("Produktnummer")), 0)
    mitte = [z for z in links if start < z["top"] < stop]
    aktuell = None
    kennung = {"methodik": [], "kennzeichen": []}
    herkunft_text = []
    in_hinweis = False
    for z in mitte:
        t = z["text"]
        if t.startswith("Produktkennung: Methodik"):
            aktuell, in_hinweis = "methodik", False
            rest = _norm(t.replace("Produktkennung: Methodik der Zuordnung zum Gebinde", ""))
            if rest:
                kennung["methodik"].append(rest)
        elif t.startswith("Produktkennung: Kennzeichen"):
            aktuell, in_hinweis = "kennzeichen", False
            rest = _norm(t.replace("Produktkennung: Kennzeichen", ""))
            if rest:
                kennung["kennzeichen"].append(rest)
        elif t.startswith("Dieser Kennzeichnungspass"):
            in_hinweis = True
            herkunft_text.append(t)
        elif in_hinweis:
            herkunft_text.append(t)
            if t.endswith("."):
                in_hinweis = False
        elif aktuell:
            kennung[aktuell].append(t)
        else:
            warnungen.append(f"Seite 1: Zeile im Kopfbereich nicht zugeordnet: {t!r}")
    for k in kennung:
        kennung[k] = [t for t in kennung[k] if t != "..."]  # im PDF stehen manchmal nur Auslassungspunkte
    kopf["produktkennung_methodik"] = " ".join(kennung["methodik"]) or None
    kopf["produktkennung_kennzeichen"] = " ".join(kennung["kennzeichen"]) or None
    hinweis = _norm(" ".join(herkunft_text))
    m = re.search(r"im (.+?) hinterlegt hat", hinweis)
    kopf["datenquelle_hinweis"] = hinweis or None
    kopf["datenquelle"] = m.group(1) if m else None

    # Allergene
    allergen_start = next((z["top"] for z in links if z["text"].startswith("Allergene")), None)
    ende = next((z["top"] for z in links if z["text"].startswith("Seite 1 von")), 10000)
    if allergen_start is None:
        warnungen.append("Seite 1: Tabelle 'Allergene' nicht gefunden")
        return kopf, {}, {}
    reihen = []
    for z in links:
        if not (allergen_start + 8 < z["top"] < ende):
            continue
        erstes = next((w for w in z["w"] if 140 <= w["x0"] < 200), None)
        if erstes and erstes["text"] in ALLERGENE:
            schluessel, gruppe = ALLERGENE[erstes["text"]]
            reihen.append({"key": schluessel, "gruppe": gruppe, "label": erstes["text"],
                           "mitte": (erstes["top"] + erstes["bottom"]) / 2,
                           "ober": erstes["top"], "unter": erstes["bottom"]})
    if len(reihen) != len(ALLERGENE):
        warnungen.append(f"Seite 1: {len(reihen)} von {len(ALLERGENE)} Allergen-Zeilen erkannt")
    # Reihen mit Untertitelzeile ("und daraus gewonnene Erzeugnisse"): Mitte der Reihe = Mitte aus Label und Untertitel
    for i, r in enumerate(reihen):
        naechste_oben = reihen[i + 1]["ober"] if i + 1 < len(reihen) else ende
        zusatz = [z for z in links if r["ober"] - 1 < z["top"] < naechste_oben - 1 and z["top"] > r["ober"] + 1
                  and not any(140 <= w["x0"] < 200 for w in z["w"])]
        if zusatz:
            r["unter"] = max(r["unter"], max(z["bottom"] for z in zusatz))
            r["mitte"] = (r["ober"] + r["unter"]) / 2

    kreuze = [w for w in woerter if w["text"] in ("X", "x") and w["x0"] >= 400
              and allergen_start < w["top"] < ende]
    allergene = {r["key"]: {"enthalten": False, "kreuzkontamination": False} for r in reihen}
    for k in kreuze:
        mitte = (k["top"] + k["bottom"]) / 2
        r = min(reihen, key=lambda r: abs(r["mitte"] - mitte))
        abstand = abs(r["mitte"] - mitte)
        if abstand > 14:
            warnungen.append(f"Seite 1: Kreuz bei y={mitte:.0f} keiner Zeile zuordenbar (Abstand {abstand:.0f})")
            continue
        spalte = "enthalten" if (k["x0"] + k["x1"]) / 2 < SPALTE_TRENNER_X else "kreuzkontamination"
        allergene[r["key"]][spalte] = True
    rechts_txt = " ".join(z["text"] for z in rechts) + " " + " ".join(_senkrechter_text(seite))
    status = {
        "enthalten_angegeben": "enthalten: keine Angabe" not in rechts_txt,
        "kreuzkontamination_angegeben": "Kreuzkontamination: keine Angabe" not in rechts_txt,
    }
    if (not status["enthalten_angegeben"] and any(a["enthalten"] for a in allergene.values())) or (
            not status["kreuzkontamination_angegeben"] and any(a["kreuzkontamination"] for a in allergene.values())):
        warnungen.append("Seite 1: 'keine Angabe' und gesetzte Kreuze in derselben Spalte")
    return kopf, allergene, status


def lese_seiten_ab_2(seiten, warnungen):
    """Seiten 2.. -> Bezeichnung, Produktspezifisches, Nährwerte, Zutaten."""
    alle = []
    for s in seiten:
        zl = _zeilen(s.extract_words())
        # Seitenkopf (2 Zeilen: "Produktname  Datengeber" / "Prod-Nr.: ... datenlink-ID: ...") und Fuß entfernen
        zl = [z for z in zl if not re.match(r"Seite \d+ von \d+", z["text"])]
        while zl and not (zl[0]["text"].startswith("Prod-Nr.")):
            zl = zl[1:]
        zl = zl[1:]  # die Prod-Nr.-Zeile selbst
        alle.extend(zl)

    out = {"bezeichnung": None, "produktspezifisch": [], "naehrwerte": None, "zutaten": None}
    abschnitt = None
    puffer = {"bezeichnung": [], "spezifisch": [], "naehr": [], "zutaten": []}
    for z in alle:
        t = z["text"]
        if t == "Bezeichnung" and abschnitt is None:
            abschnitt = "bezeichnung"
            continue
        if t.startswith("Produktspezifische Angaben"):
            abschnitt = "spezifisch"
            continue
        if t.startswith("Nährwertangaben"):
            abschnitt = "naehr"
            continue
        if t.startswith("Zutatenverzeichnis"):
            abschnitt = "zutaten"
            continue
        if abschnitt:
            puffer[abschnitt].append(z)
        else:
            warnungen.append(f"Seite 2: Zeile vor 'Bezeichnung' ignoriert: {t!r}")

    out["bezeichnung"] = _norm(" ".join(z["text"] for z in puffer["bezeichnung"])) or None
    out["produktspezifisch"] = [z["text"].lstrip("- ").strip() for z in puffer["spezifisch"]]

    # Nährwerte
    n = puffer["naehr"]
    if len(n) == 1 and n[0]["text"] == KEINE_INFO:
        out["naehrwerte"] = None
        out["naehrwerte_hinweis"] = KEINE_INFO
    elif n:
        nw = {"referenz": None, "verarbeitungsstatus": None, "werte": {}, "weitere": {}}
        for z in n:
            t = z["text"]
            if t.startswith("Die Angaben sind Durchschnittswerte"):
                continue
            if t.startswith("Referenzmenge"):
                teile = t.split()
                if "x" in teile and teile.index("x") + 1 < len(teile):
                    nw["referenz"] = teile[teile.index("x") + 1]
                else:
                    warnungen.append(f"Seite 2: Referenzmenge nicht lesbar: {t!r}")
                continue
            if t.startswith("Verarbeitungsstatus"):
                teile = t.split()
                if "x" in teile and teile.index("x") + 1 < len(teile):
                    nw["verarbeitungsstatus"] = teile[teile.index("x") + 1]
                else:
                    warnungen.append(f"Seite 2: Verarbeitungsstatus nicht lesbar: {t!r}")
                continue
            # Wert = rechter Teil (x >= 400), Beschriftung = linker Teil
            label = _norm(" ".join(w["text"] for w in z["w"] if w["x0"] < 400))
            wert = _norm(" ".join(w["text"] for w in z["w"] if w["x0"] >= 400))
            if not wert:
                m = re.match(r"(.+?)\s+((?:<\s*)?[\d.,]+\s*(?:kJ|kcal|g|mg|µg|ml)|keine Angabe)$", t)
                if m:
                    label, wert = m.group(1), m.group(2)
            if label.endswith(" keine") and wert.startswith("Angabe"):  # "keine" ragt in die Beschriftung
                label, wert = label[:-len(" keine")], "keine " + wert
            key = next((k for pre, k in NAEHRWERT_SCHLUESSEL if label.startswith(pre)), None)
            if key:
                nw["werte"][key] = _zahl(wert)
            else:
                nw["weitere"][label] = _zahl(wert)
                warnungen.append(f"Seite 2: unbekannte Nährwert-Zeile {label!r} -> unter 'weitere' abgelegt")
        out["naehrwerte"] = nw
    else:
        warnungen.append("Seite 2: Abschnitt Nährwertangaben leer")

    # Zutaten
    zu = puffer["zutaten"]
    if len(zu) == 1 and zu[0]["text"] == KEINE_INFO:
        out["zutaten"] = None
        out["zutaten_hinweis"] = KEINE_INFO
    elif zu and zu[0]["text"].startswith("Bezeichnung") and "Anteil" in zu[0]["text"]:
        liste = []
        for z in zu[1:]:
            name = _norm(" ".join(w["text"] for w in z["w"] if w["x0"] < 400))
            anteil = _norm(" ".join(w["text"] for w in z["w"] if w["x0"] >= 400)) or None
            if not name:
                warnungen.append(f"Seite 2: Zutatenzeile ohne Namen: {z['text']!r}")
                continue
            x0 = min(w["x0"] for w in z["w"] if w["x0"] < 400)
            liste.append({"name": name, "anteil_text": anteil, "x0": round(x0, 1)})
        out["zutaten"] = {"art": "liste", "eintraege": liste}
    elif zu:
        text = _norm(" ".join(z["text"] for z in zu))
        spuren = re.search(r"Kann Spuren von (.+?) enthalten\.", text)
        out["zutaten"] = {"art": "freitext", "text": text,
                          "spuren_hinweis": spuren.group(1) if spuren else None}
    else:
        warnungen.append("Seite 2: Zutatenverzeichnis leer")
    return out


def plausibilitaet(daten):
    """Rechenprüfungen der Nährwerte. Nur Hinweise, keine Korrekturen."""
    hinweise = []
    nw = daten.get("naehrwerte")
    if not nw:
        return hinweise
    w = {k: v["wert"] for k, v in nw["werte"].items() if v.get("angegeben")}
    if "energie_kj" in w and "energie_kcal" in w and w["energie_kj"] > 0:
        soll = w["energie_kj"] / 4.1868
        if abs(soll - w["energie_kcal"]) > max(3, 0.03 * soll):
            hinweise.append(f"kcal ({w['energie_kcal']}) passt nicht zu kJ ({w['energie_kj']}), erwartet ca. {soll:.0f}")
    if "davon_gesaettigt" in w and "fett" in w and w["davon_gesaettigt"] > w["fett"] + 0.05:
        hinweise.append("gesättigte Fettsäuren größer als Fett")
    if "davon_zucker" in w and "kohlenhydrate" in w and w["davon_zucker"] > w["kohlenhydrate"] + 0.05:
        hinweise.append("Zucker größer als Kohlenhydrate")
    summe = sum(w.get(k, 0) for k in ("fett", "kohlenhydrate", "ballaststoffe", "eiweiss", "salz"))
    if summe > 100.5:
        hinweise.append(f"Summe Fett+KH+Ballaststoffe+Eiweiß+Salz = {summe:.1f} g (mehr als 100 g)")
    if nw.get("referenz") not in (None, "100g"):
        hinweise.append(f"Referenzmenge ist {nw.get('referenz')!r}, nicht 100g")
    if nw.get("verarbeitungsstatus") not in (None, "unzubereitetes"):
        hinweise.append(f"Verarbeitungsstatus ist {nw.get('verarbeitungsstatus')!r}")
    return hinweise


def lese_pdf_roh(pfad):
    """PDF -> Rohdaten (Schema 1, nah am PDF-Layout)."""
    pfad = Path(pfad)
    warnungen = []
    with pdfplumber.open(pfad) as pdf:
        titel = _norm(pdf.metadata.get("Title", ""))
        subject = _norm(pdf.metadata.get("Subject", ""))
        if subject != "Produktspezifikation":
            warnungen.append(f"PDF-Betreff ist {subject!r}, erwartet 'Produktspezifikation'")
        if len(pdf.pages) < 2:
            warnungen.append("PDF hat weniger als 2 Seiten")
            return {"datei": pfad.name, "warnungen": warnungen}
        kopf, allergene, astatus = lese_seite1(pdf.pages[0], warnungen)
        rest = lese_seiten_ab_2(pdf.pages[1:], warnungen)
    m = re.fullmatch(r"(.+?) \(Produkt-Nr\. (.+)\)", titel)
    produktname = m.group(1) if m else titel
    if m and kopf.get("produktnummer") and m.group(2) != kopf["produktnummer"]:
        warnungen.append(f"Produktnummer im Titel ({m.group(2)}) ≠ Kopf ({kopf['produktnummer']})")
    daten = {
        "schema": SCHEMA_VERSION,
        "datei": pfad.name,
        "produktname": produktname,
        **kopf,
        "bezeichnung": rest["bezeichnung"],
        "produktspezifisch": rest["produktspezifisch"],
        "allergene": allergene,
        "allergene_status": astatus,
        "naehrwerte": rest["naehrwerte"],
        "naehrwerte_hinweis": rest.get("naehrwerte_hinweis"),
        "zutaten": rest["zutaten"],
        "zutaten_hinweis": rest.get("zutaten_hinweis"),
    }
    daten["plausibilitaet"] = plausibilitaet(daten)
    daten["warnungen"] = warnungen
    return daten


def main(argv):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zwischenstruktur import lese_pdf  # Schema 2 (an datenlinkXML angelehnt)
    ausgabe = None
    dateien = []
    roh = False
    it = iter(argv)
    for a in it:
        if a == "--roh":
            roh = True
        elif a == "-o":
            ausgabe = Path(next(it))
        else:
            dateien.append(a)
    if not dateien:
        print(__doc__)
        return 2
    if ausgabe:
        ausgabe.mkdir(parents=True, exist_ok=True)
    for d in dateien:
        daten = lese_pdf_roh(d) if roh else lese_pdf(d)
        text = json.dumps(daten, ensure_ascii=False, indent=2)
        if ausgabe:
            (ausgabe / (Path(d).stem + ".json")).write_text(text, encoding="utf-8")
        else:
            print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
