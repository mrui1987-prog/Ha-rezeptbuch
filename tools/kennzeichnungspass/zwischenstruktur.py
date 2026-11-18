#!/usr/bin/env python3
"""Zwischenstruktur Schema 2 – an datenlinkXML 1.1 (XSD) angelehnt.

Ziel: Der PDF-Leser (heute) und ein späterer XML-/JSON-Leser (API) liefern
dieselbe Struktur. Import, Bericht "alt -> neu" und Freigabe hängen nur hiervon ab.

Bedeutungen wie in der XSD:
- allergene.enthalten / allergene.kreuzkontamination:
    None = keine Angabe (XML: AllergenList fehlt), [] = kein Allergen (leere Liste),
    [...] = Schlüssel der angekreuzten Allergene. Unterallergene stehen unter ihrem
    Oberbegriff (XML: verschachtelte AllergenListItem).
- naehrwerte: None = keine Angabe (XML: NutritionFacts fehlt, nur bei GDSN erlaubt).
  Einzelwert "keine Angabe" -> Schlüssel in naehrwerte.nicht_angegeben (XML: Item fehlt).
  kleiner_als entspricht dem XML-Attribut smaller="true".
- zutaten: None = keine Angabe (XML: IngredientList fehlt, nur bei GDSN erlaubt);
  struktur STRUCTURED (Liste, verschachtelbar) oder PLAINTEXT (nur bei GDSN erlaubt).
- datenquelle: "datenlink" oder "GDSN-XML" (XML: Header/DataSource/Resource).

Eigene Schlüssel für Allergene und Nährwerte (z. B. "weizen", "energie_kj").
Die datenlink-Codes (LIST_ALLERGEN, BLS-Nährwertschlüssel) sind noch nicht bekannt;
die Zuordnung kommt mit dem ersten echten XML bzw. getComponentListEntries.

Nichts wird erfunden: Unklares -> "warnungen", Rechen-/Regelverstöße -> "plausibilitaet".
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kennzeichnungspass import ALLERGENE, lese_pdf_roh  # noqa: E402

SCHEMA_VERSION = 2
EINZUG_TOLERANZ = 5.0  # pt; größerer Einzug in der Zutatentabelle = Unterzutat


def _gtin_pruefziffer_ok(g):
    if not re.fullmatch(r"\d{8}|\d{12}|\d{13}|\d{14}", g):
        return False
    ziffern = [int(c) for c in g]
    summe = sum(z * (3 if i % 2 == 0 else 1) for i, z in enumerate(reversed(ziffern[:-1])))
    return (10 - summe % 10) % 10 == ziffern[-1]


def _prozent(text):
    if not text:
        return None
    m = re.fullmatch(r"(<\s*)?(\d+(?:,\d+)?)\s*%", text.strip())
    return float(m.group(2).replace(",", ".")) if m else None


def _allergenliste(roh_allergene, spalte, angegeben):
    """Flache Kreuze -> Liste wie im XML: Oberbegriffe mit Unterallergenen."""
    if not angegeben:
        return None
    gesetzt = {k for k, v in roh_allergene.items() if v[spalte]}
    gruppe_von = {key: gruppe for key, gruppe in ALLERGENE.values()}
    liste, warn = [], []
    for key in sorted(k for k in gesetzt if gruppe_von.get(k) is None):
        unter = sorted(k for k in gesetzt if gruppe_von.get(k) == key)
        liste.append({"key": key, "unter": unter})
    waisen = {}
    for k in sorted(gesetzt):
        g = gruppe_von.get(k)
        if g and g not in gesetzt:
            waisen.setdefault(g, []).append(k)
    for g, unter in sorted(waisen.items()):
        warn.append(f"{', '.join(unter)} ({spalte}) angekreuzt, Oberbegriff {g!r} aber nicht "
                    "(im XML stünde es unter dem Oberbegriff)")
        liste.append({"key": g, "unter": unter, "oberbegriff_nicht_angekreuzt": True})
    return liste, warn


def _zutaten_verschachteln(eintraege, warnungen):
    """Liste mit Einzug (x0) -> Baum. Ohne unterschiedlichen Einzug bleibt die Liste flach."""
    if not eintraege:
        return []
    basis = min(e["x0"] for e in eintraege)
    stufen = sorted({round((e["x0"] - basis) / EINZUG_TOLERANZ) for e in eintraege})
    if len(stufen) > 1:
        warnungen.append(f"Zutatenliste mit {len(stufen)} Einzugsstufen erkannt: als Unterzutaten "
                         "gelesen (bisher ohne Beispiel geprüft)")
    wurzel, stapel = [], []  # stapel: (stufe, knoten)
    for e in eintraege:
        stufe = stufen.index(round((e["x0"] - basis) / EINZUG_TOLERANZ))
        knoten = {"name": e["name"], "anteil_prozent": _prozent(e["anteil_text"]),
                  "anteil_text": e["anteil_text"], "unterzutaten": []}
        if e["anteil_text"] and knoten["anteil_prozent"] is None:
            warnungen.append(f"Anteil {e['anteil_text']!r} bei {e['name']!r} nicht als Prozent lesbar")
        while stapel and stapel[-1][0] >= stufe:
            stapel.pop()
        (stapel[-1][1]["unterzutaten"] if stapel else wurzel).append(knoten)
        stapel.append((stufe, knoten))
    return wurzel


def _spezifikation(text):
    m = re.fullmatch(r"([^:]{2,60}):\s*(.+)", text)
    return {"bezeichnung": m.group(1).strip(), "wert": m.group(2).strip(), "text": text} if m \
        else {"bezeichnung": None, "wert": None, "text": text}


# Stichwörter in GROSSBUCHSTABEN (so kennzeichnet die EU-Verordnung Allergene in Zutatenlisten)
# -> Schlüssel des Allergenrasters
ALLERGEN_STICHWOERTE = {
    "WEIZEN": "weizen", "DINKEL": "weizen", "ROGGEN": "roggen", "GERSTE": "gerste", "HAFER": "hafer",
    "MILCH": "milch", "SOJA": "soja", "SESAM": "sesam", "LUPINE": "lupinen", "ERDNUSS": "erdnuesse",
    "ERDNÜSSE": "erdnuesse", "MANDEL": "mandeln", "HASELNUSS": "haselnuesse", "HASELNÜSSE": "haselnuesse",
    "WALNUSS": "walnuesse", "WALNÜSSE": "walnuesse", "SELLERIE": "sellerie", "SENF": "senf",
}


def _zutaten_allergen_hinweise(zutaten, allergene):
    """Hinweise (keine Korrektur): Zutatenliste nennt ein Allergen in Großbuchstaben, das in der
    Spalte „in Rezeptur / als Zutat enthalten“ nicht angekreuzt ist (z. B. WEIZENMEHL ohne Kreuz bei Weizen)."""
    if not zutaten or allergene.get("enthalten") is None:
        return []
    if zutaten["struktur"] == "PLAINTEXT":
        text = zutaten["text"] or ""
    else:
        def namen(es):
            for e in es:
                yield e["name"]
                yield from namen(e.get("unterzutaten", []))
        text = " ".join(namen(zutaten["eintraege"]))
    angekreuzt = set()
    for e in allergene["enthalten"]:
        angekreuzt.add(e["key"])
        angekreuzt.update(e["unter"])
    gefunden = {(key, stich) for lauf in re.findall(r"[A-ZÄÖÜß]{3,}", text)
                for stich, key in ALLERGEN_STICHWOERTE.items() if stich in lauf}
    return [f"Zutatenliste nennt {stich} in Großbuchstaben, im Allergenraster ist {key!r} (in Rezeptur / "
            "als Zutat enthalten) nicht angekreuzt – bitte prüfen"
            for key, stich in sorted(gefunden) if key not in angekreuzt]


def aus_roh(roh):
    warnungen = list(roh.get("warnungen", []))
    plaus = list(roh.get("plausibilitaet", []))

    # Datenquelle: Der PDF-Kopf nennt nur GDSN ausdrücklich; ohne Hinweis -> datenlink
    hinweis = roh.get("datenquelle") or ""
    if not hinweis:
        datenquelle = "datenlink"
    elif "GDSN" in hinweis:
        datenquelle = "GDSN-XML"
    else:
        datenquelle = None
        warnungen.append(f"Unbekannte Datenquelle im PDF-Hinweis: {hinweis!r}")

    plz, ort = None, None
    m = re.fullmatch(r"(\d{4,5})\s+(.+)", roh.get("plz_ort") or "")
    if m:
        plz, ort = m.groups()
    elif roh.get("plz_ort"):
        warnungen.append(f"PLZ/Ort nicht trennbar: {roh['plz_ort']!r}")

    nummern = []
    if roh.get("produktnummer"):
        nummern.append({"typ": "MANUFACTURER", "wert": roh["produktnummer"]})
    gtin = roh.get("gtin")
    if gtin and gtin.lower() != "keine angabe":
        nummern.append({"typ": "GTIN", "wert": gtin})
        if not _gtin_pruefziffer_ok(gtin):
            plaus.append(f"GTIN {gtin} hat keine gültige Länge oder Prüfziffer")

    # Allergene
    st = roh.get("allergene_status", {})
    allergene = {}
    for spalte, schl in (("enthalten", "enthalten_angegeben"), ("kreuzkontamination", "kreuzkontamination_angegeben")):
        erg = _allergenliste(roh.get("allergene", {}), spalte, st.get(schl, True))
        if erg is None:
            allergene[spalte] = None
        else:
            allergene[spalte], w = erg
            plaus.extend(w)  # Datenlage beim Datengeber, kein Lesefehler

    # Nährwerte
    nw_roh = roh.get("naehrwerte")
    naehrwerte = None
    if nw_roh:
        ref = nw_roh.get("referenz")
        m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(g|ml)", ref or "")
        bezug = {"wert": float(m.group(1).replace(",", ".")), "einheit": m.group(2)} if m else None
        if not bezug:
            warnungen.append(f"Referenzmenge {ref!r} nicht lesbar")
        zustand = {"unzubereitetes": "UNPREPARED", "zubereitetes": "PREPARED", None: None}.get(
            nw_roh.get("verarbeitungsstatus"), "?")
        if zustand == "?":
            warnungen.append(f"Verarbeitungsstatus {nw_roh.get('verarbeitungsstatus')!r} unbekannt")
            zustand = None
        werte, fehlend = {}, []
        for key, v in list(nw_roh["werte"].items()) + list(nw_roh.get("weitere", {}).items()):
            if v["angegeben"] is False:
                fehlend.append(key)
            elif v["angegeben"]:
                werte[key] = {"wert": v["wert"], "einheit": v["einheit"], "kleiner_als": v["kleiner_als"]}
                if v["wert"] >= 10000:
                    plaus.append(f"Nährwert {key} = {v['wert']} hat mehr als 4 Vorkommastellen (XSD erlaubt max. 4)")
            else:
                warnungen.append(f"Nährwert {key}: {v['text']!r} nicht lesbar")
        naehrwerte = {"bezug": bezug, "zustand": zustand, "werte": werte, "nicht_angegeben": sorted(fehlend)}

    # Zutaten
    z_roh = roh.get("zutaten")
    zutaten = None
    if z_roh and z_roh["art"] == "liste":
        baum = _zutaten_verschachteln(z_roh["eintraege"], warnungen)
        zutaten = {"struktur": "STRUCTURED", "eintraege": baum, "text": None}
        summe = sum(e["anteil_prozent"] or 0 for e in baum)
        if summe > 100.5:
            plaus.append(f"Summe der Zutatenanteile {summe:.1f} % (mehr als 100 %)")
        if not baum:
            warnungen.append("Zutatenliste ohne Einträge (XSD: auch Monokomponente muss eine Zutat haben)")
    elif z_roh and z_roh["art"] == "freitext":
        zutaten = {"struktur": "PLAINTEXT", "eintraege": [], "text": z_roh["text"],
                   "spuren_hinweis": z_roh.get("spuren_hinweis")}

    plaus.extend(_zutaten_allergen_hinweise(zutaten, allergene))

    # Regeln aus der XSD, die nur bei Quelle GDSN-XML Lücken erlauben
    if datenquelle == "datenlink":
        if naehrwerte is None:
            plaus.append("Keine Nährwerte, obwohl Quelle 'datenlink' (laut XSD nur bei GDSN möglich)")
        if zutaten is None:
            plaus.append("Kein Zutatenverzeichnis, obwohl Quelle 'datenlink' (laut XSD nur bei GDSN möglich)")
        elif zutaten["struktur"] == "PLAINTEXT":
            plaus.append("Zutaten als Klartext, obwohl Quelle 'datenlink' (laut XSD nur bei GDSN möglich)")
        if not roh.get("bezeichnung"):
            plaus.append("Keine Bezeichnung, obwohl Quelle 'datenlink' (laut XSD nur bei GDSN möglich)")

    return {
        "schema": SCHEMA_VERSION,
        "quelle": {"art": "pdf", "datei": roh.get("datei")},
        "datenquelle": datenquelle,
        "hersteller": {"name": roh.get("datengeber"), "plz": plz, "ort": ort, "land": roh.get("land")},
        "produkt": {
            "datenlink_id": roh.get("datenlink_id"),
            "name": roh.get("produktname"),
            "nummern": nummern,
            "gueltig_ab": roh.get("gueltig_ab"),
            "kennung": {"methodik": roh.get("produktkennung_methodik"),
                        "wert": roh.get("produktkennung_kennzeichen")},
            "spezifikationen": [_spezifikation(t) for t in roh.get("produktspezifisch", [])],
        },
        "lebensmittel": {
            "bezeichnung": roh.get("bezeichnung"),
            "naehrwerte": naehrwerte,
            "allergene": allergene,
            "zutaten": zutaten,
        },
        "plausibilitaet": plaus,
        "warnungen": warnungen,
    }


def lese_pdf(pfad):
    return aus_roh(lese_pdf_roh(pfad))
