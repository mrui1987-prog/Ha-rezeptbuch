#!/usr/bin/env python3
"""Leser für datenlink-Kennzeichnungspässe (PDF) -> neutrale Zwischenstruktur.

Grundsatz: nur Lesen, nichts erfinden. Was nicht sicher gelesen werden kann,
wird als Warnung gemeldet und nicht geraten. Keine Datenbank, kein Netzwerk.

Aufruf:  python3 -I kennzeichnungspass.py datei.pdf [weitere.pdf ...]   (JSON auf stdout)

Zustände bei Allergenen und Nährwerten:
  None  = „keine Angabe“ bzw. „keine Informationen verfügbar“ (unbekannt!)
  []    = Angabe vorhanden, aber nichts enthalten
  Liste = Eintrag(e) vorhanden
Das ist etwas anderes als „nicht enthalten“ und darf nie vermischt werden.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict

import pdfplumber

SCHEMA = 3

# Zellfarben im Allergenraster (aus den PDFs abgelesen, 18.11.2026):
#   rot    = „in Rezeptur / als Zutat enthalten“ (Spalte 1)
#   orange = „Kreuzkontamination“ (Spalte 2)
FARBE_ROT = (0.82, 0.0, 0.0)
FARBE_ORANGE = (0.98, 0.61, 0.1)

HEADER_ZEILEN_OBEN = 45     # Kopf der Folgeseiten (Titel, Prod-Nr.) unterhalb dieser Höhe ignorieren
FUSS_ZEILEN_UNTEN = 800     # „Seite n von m“

KEINE_INFO = "keine informationen verfügbar"


class KeinKennzeichnungspass(ValueError):
    pass


# ----------------------------------------------------------------- Hilfsfunktionen

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _zeilen(woerter, tol=3.5):
    """Wörter zu Zeilen gruppieren (nach vertikalem Mittelpunkt), je Zeile nach x sortiert.
    Kästchen-Zeichen („x“) und Schrift mit anderer Größe liegen oft 1–3 pt höher/tiefer."""
    zs = []
    for w in sorted(woerter, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"])):
        mitte = (w["top"] + w["bottom"]) / 2
        for z in zs:
            if abs(z["mitte"] - mitte) <= tol:
                z["w"].append(w)
                z["mitte"] = (z["mitte"] * (len(z["w"]) - 1) + mitte) / len(z["w"])
                break
        else:
            zs.append({"mitte": mitte, "w": [w]})
    for z in zs:
        z["w"].sort(key=lambda w: w["x0"])
        z["text"] = _norm(" ".join(w["text"] for w in z["w"]))
        z["x0"] = z["w"][0]["x0"]
        z["top"] = min(w["top"] for w in z["w"])
        z["bottom"] = max(w["bottom"] for w in z["w"])
    zs.sort(key=lambda z: z["mitte"])
    return zs


def _slug(s: str) -> str:
    s = s.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = re.sub(r"\(.*?\)", "", s)
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def gtin_pruefziffer_ok(gtin: str) -> bool:
    if not gtin.isdigit() or len(gtin) not in (8, 12, 13, 14):
        return False
    ziffern = [int(c) for c in gtin]
    pruef = ziffern.pop()
    summe = sum(z * (3 if i % 2 == 0 else 1) for i, z in enumerate(reversed(ziffern)))
    return (10 - summe % 10) % 10 == pruef


def zahl(text: str):
    """„0,01“ -> 0.01 ; „1.234,5“ -> 1234.5 ; sonst None."""
    t = text.strip().replace(" ", "")
    if not re.fullmatch(r"\d{1,3}(\.\d{3})*(,\d+)?|\d+(,\d+)?|\d+\.\d+", t):
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    return float(t)


def parse_wert(text: str):
    """Nährwert-/Anteilswert. Rückgabe (zahl|None, einheit|None, kleiner_als, status).
    status: 'wert' | 'keine_angabe' | 'unlesbar'"""
    t = _norm(text)
    if not t:
        return None, None, False, "unlesbar"
    if t.lower() == "keine angabe":
        return None, None, False, "keine_angabe"
    m = re.fullmatch(r"(<|≤|kleiner als)?\s*(\d[\d.,]*)\s*(kJ|kcal|g|mg|µg|ml|%)?", t, re.I)
    if not m:
        return None, None, False, "unlesbar"
    z = zahl(m.group(2))
    if z is None:
        return None, None, False, "unlesbar"
    return z, m.group(3), bool(m.group(1)), "wert"


# ----------------------------------------------------------------- Seite 1

def _seite1(pg, warn):
    up = [w for w in pg.extract_words(extra_attrs=["upright"]) if w["upright"]]
    out = {}

    # Kopfbereich: oben (Datengeber, PLZ/Ort, Land) laufen Werte bis in die rechte Hälfte
    # (lange Firmennamen); ab „Produktnummer“ steht rechts ein zweiter Block (ID, GTIN, Datum).
    kopf = [w for w in up if 60 < w["top"] < 295]
    oben = [w for w in kopf if w["top"] < 135]
    unten = [w for w in kopf if w["top"] >= 135]
    links = _zeilen(oben) + _zeilen([w for w in unten if w["x0"] < 420])
    rechts = _zeilen([w for w in unten if w["x0"] >= 420])

    feld = {}
    aktuell = None
    labels = ("Datengeber", "PLZ, Ort", "Land", "Produktnummer",
              "Produktkennung: Methodik der Zuordnung zum Gebinde", "Produktkennung: Kennzeichen")
    for z in links:
        t = z["text"]
        hit = next((l for l in labels if t == l or t.startswith(l + " ")), None)
        if hit:
            aktuell = hit
            feld[hit] = t[len(hit):].strip()
        elif aktuell and aktuell.startswith("Produktkennung") and z["x0"] > 140:
            feld[aktuell] = _norm(feld[aktuell] + " " + t)   # Wert steht eingerückt unter dem Label
        elif t.startswith(("Die Richtigkeit", "Dieser", "erstellt,", "hat.")):
            aktuell = None
        elif aktuell and aktuell in ("Datengeber", "PLZ, Ort", "Land", "Produktnummer") and z["x0"] > 200:
            feld[aktuell] = _norm(feld[aktuell] + " " + t)   # umgebrochener Wert
        else:
            aktuell = None

    rf = {}
    for z in rechts:
        t = z["text"]
        m = re.match(r"(Datenlink-ID|GTIN)\s*(.*)$", t)
        if m:
            rf[m.group(1)] = m.group(2).strip()
    # Gültig ab: Datum steht unter „Gültig ab Datum“
    seitentext = _norm(" ".join(z["text"] for z in rechts))
    m = re.search(r"Gültig ab Datum\s*(\d{2})\.(\d{2})\.(\d{4})", seitentext)
    gueltig_ab = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
    if not m:
        warn("Gültig-ab-Datum nicht gefunden")

    gesamt = _norm(" ".join(w["text"] for w in up))
    quelle = "GDSN" if "GDSN-Datenpool" in gesamt else "datenlink"

    out["datengeber"] = feld.get("Datengeber")
    out["plz_ort"] = feld.get("PLZ, Ort")
    out["land"] = feld.get("Land")
    out["produktnummer"] = feld.get("Produktnummer")        # immer Text („10026.01“, „00943“)
    out["datenlink_id"] = rf.get("Datenlink-ID")
    out["gtin"] = rf.get("GTIN") or None
    out["gueltig_ab"] = gueltig_ab
    out["quelle"] = quelle
    out["produktkennung_methodik"] = feld.get("Produktkennung: Methodik der Zuordnung zum Gebinde")
    out["produktkennung_kennzeichen"] = feld.get("Produktkennung: Kennzeichen")

    for k in ("datengeber", "produktnummer", "datenlink_id"):
        if not out[k]:
            warn(f"Pflichtfeld fehlt: {k}")
    if out["gtin"] and not gtin_pruefziffer_ok(out["gtin"]):
        warn(f"GTIN {out['gtin']}: Prüfziffer falsch")
    if out["gtin"] and not out["gtin"].isdigit():
        warn(f"GTIN nicht numerisch: {out['gtin']!r}")

    # Titel nur als Rückfall aus dem Seitentext (dort gehen Zeichen verloren!)
    tw = [w for w in up if w["top"] < 72 and w["x0"] > 125]
    out["_titel_seitentext"] = _norm(" ".join(w["text"] for w in tw))
    return out


def _allergene(pg, warn):
    """Allergenraster über Koordinaten lesen."""
    ws = pg.extract_words(extra_attrs=["upright"])
    up = [w for w in ws if w["upright"]]
    tab = [w for w in up if w["top"] > 318 and w["top"] < 800]

    # Spaltengrenzen aus den Rechtecken: Spalte 1 und 2 der Kopfzeile des Rasters
    # (x ≈ 408–482 und 490–564); Kopfzeilen-Text „in Rezeptur…“/„Kreuzkontamination“ liefert sie nicht.
    spalten = _spalten(pg)

    # Zeilenbezeichnungen: Oberbegriffe (x0 < 150) und Unterallergene (eingerückt)
    zeilen = []
    for z in _zeilen([w for w in tab if w["x0"] < 400], tol=4.0):
        ebene = 0 if z["x0"] < 155 else 1
        if ebene == 0:
            name = _norm(" ".join(w["text"] for w in z["w"] if w["x0"] < 280))
        else:
            name = z["text"]
        if not name:
            continue
        zeilen.append({"name": name, "ebene": ebene, "mitte": z["mitte"],
                       "col": [False, False]})
    if not zeilen:
        warn("Allergenraster: keine Zeilen gefunden")
        return None

    def zeile_nahe(y):
        z = min(zeilen, key=lambda z: abs(z["mitte"] - y))
        return z if abs(z["mitte"] - y) < 8 else None

    # Signal 1: farbige Zellen
    farbzellen = []
    for r in pg.rects:
        c = r.get("non_stroking_color")
        if not (r.get("fill") and c and len(c) == 3):
            continue
        c = tuple(round(v, 2) for v in c)
        if c in (FARBE_ROT, FARBE_ORANGE) and r["top"] > 318:
            farbzellen.append((c, (r["x0"] + r["x1"]) / 2, (r["top"] + r["bottom"]) / 2))
    # Signal 2: der Buchstabe X
    xs = [((w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2) for w in tab if w["text"] == "X"]

    def spalte_von(x):
        for i, (a, b) in enumerate(spalten):
            if a - 2 <= x <= b + 2:
                return i
        return None

    marken_f, marken_x = set(), set()
    for c, x, y in farbzellen:
        z, s = zeile_nahe(y), spalte_von(x)
        if z is None or s is None:
            warn(f"farbige Zelle ohne Zeile/Spalte bei y={y:.0f}")
            continue
        erwartet = 0 if c == FARBE_ROT else 1
        if s != erwartet:
            warn(f"Zellfarbe passt nicht zur Spalte ({z['name']})")
        marken_f.add((id(z), s))
    for x, y in xs:
        z, s = zeile_nahe(y), spalte_von(x)
        if z is None or s is None:
            warn(f"X ohne Zeile/Spalte bei y={y:.0f}")
            continue
        marken_x.add((id(z), s))
    if marken_f != marken_x:
        warn(f"Allergen-Kreuze (X: {len(marken_x)}) und Zellfarben ({len(marken_f)}) stimmen nicht überein; "
             "es gilt die Vereinigung, bitte Seite prüfen")
    for zid, s in marken_f | marken_x:
        next(z for z in zeilen if id(z) == zid)["col"][s] = True

    # „keine Angabe“ je Spalte: senkrecht gedruckter Text im Spaltenkasten
    keine_angabe = [False, False]
    rot = [c for c in pg.chars if not c.get("upright", True) and c["top"] > 318]
    for s, (a, b) in enumerate(spalten):
        zeichen = [c for c in rot if a - 2 <= (c["x0"] + c["x1"]) / 2 <= b + 2]
        if zeichen:
            text = "".join(c["text"] for c in sorted(zeichen, key=lambda c: -c["top"]))
            text = _norm(text[::-1]) if text[::-1].lower().find("keine") >= 0 or text.lower().find("anig") >= 0 else _norm(text)
            # pdfplumber liefert senkrechten Text je nach Richtung vorwärts oder rückwärts
            if "keine angabe" in text.lower() or "keine angabe" in text[::-1].lower():
                keine_angabe[s] = True
            else:
                warn(f"Unbekannter senkrechter Text in Spalte {s + 1}: {text!r}")
    for s in (0, 1):
        if keine_angabe[s] and any(z["col"][s] for z in zeilen):
            warn(f"Spalte {s + 1}: „keine Angabe“ und zugleich Kreuze – bitte Seite prüfen")

    return {"zeilen": zeilen, "keine_angabe": keine_angabe, "anzahl_kreuze_x": len(marken_x)}


def _spalten(pg):
    """x-Bereiche der beiden Kreuzspalten aus den Zellrechtecken (Standard: 408–482, 490–564)."""
    kand = [r for r in pg.rects if r["top"] > 318 and r["width"] > 50 and r["x0"] > 380]
    s1 = [r for r in kand if r["x0"] < 486 and r["x1"] <= 490]
    s2 = [r for r in kand if r["x0"] >= 486]
    a = (min(r["x0"] for r in s1), max(r["x1"] for r in s1)) if s1 else (408.0, 482.0)
    b = (min(r["x0"] for r in s2), max(r["x1"] for r in s2)) if s2 else (490.0, 564.0)
    return [a, b]


def _allergen_struktur(roh, warn):
    """Rasterzeilen -> Struktur je Spalte (None / [] / Liste mit Oberbegriff und Unterallergenen)."""
    if roh is None:
        return None
    ergebnis = {}
    for s, name in enumerate(("enthalten", "kreuzkontamination")):
        if roh["keine_angabe"][s]:
            ergebnis[name] = None
            continue
        liste = []
        eltern = None
        for z in roh["zeilen"]:
            if z["ebene"] == 0:
                eltern = {"allergen": z["name"], "schluessel": _slug(z["name"]),
                          "oberbegriff_angekreuzt": bool(z["col"][s]), "unter": []}
                liste.append(eltern)
            else:
                if eltern is None:
                    warn(f"Unterallergen ohne Oberbegriff: {z['name']}")
                    continue
                if z["col"][s]:
                    eltern["unter"].append({"allergen": z["name"], "schluessel": _slug(z["name"])})
        ergebnis[name] = [e for e in liste if e["oberbegriff_angekreuzt"] or e["unter"]]
        for e in ergebnis[name]:
            if e["unter"] and not e["oberbegriff_angekreuzt"]:
                warn(f"Plausibilität: nur Unterallergen angekreuzt, Oberbegriff nicht ({e['allergen']}, "
                     f"{name})")
    ergebnis["anzahl_zeilen"] = len(roh["zeilen"])
    return ergebnis


# ----------------------------------------------------------------- Seite 2 ff.

NAEHRWERTE = {
    "energie (kilojoule)": ("energie_kj", "kJ"),
    "energie (kilokalorien, 1 kcal = 4,1868 kj)": ("energie_kcal", "kcal"),
    "fett": ("fett", "g"),
    "davon gesättigte fettsäuren": ("fett_gesaettigt", "g"),
    "kohlenhydrate": ("kohlenhydrate", "g"),
    "davon zucker": ("zucker", "g"),
    "ballaststoffe": ("ballaststoffe", "g"),
    "eiweiß": ("eiweiss", "g"),
    "salz": ("salz", "g"),
}


def _folgeseiten_zeilen(pdf):
    """Alle Zeilen ab Seite 2, ohne Seitenkopf und Fuß, mit fortlaufender y-Position."""
    zs = []
    offset = 0.0
    for pg in pdf.pages[1:]:
        ws = [w for w in pg.extract_words(extra_attrs=["upright"])
              if w["upright"] and HEADER_ZEILEN_OBEN < w["top"] < FUSS_ZEILEN_UNTEN]
        for z in _zeilen(ws):
            z["top"] += offset
            z["bottom"] += offset
            for w in z["w"]:
                w["top"] += offset
                w["bottom"] += offset
            zs.append(z)
        offset += pg.height
    return zs


def _kopf_folgeseite(pdf):
    ws = [w for w in pdf.pages[1].extract_words() if w["top"] < HEADER_ZEILEN_OBEN]
    zs = _zeilen(ws)
    info = {}
    if len(zs) >= 2:
        m = re.search(r"Prod-Nr\.:\s*(\S+)\s+datenlink-ID:\s*(\S+)", zs[1]["text"])
        if m:
            info["produktnummer"], info["datenlink_id"] = m.group(1), m.group(2)
    return info


def _checkbox(zeile, optionen):
    """Gewählte Option einer Zeile mit Kästchen: ein „x“ unmittelbar vor der Option."""
    xs = [w for w in zeile["w"] if w["text"] == "x"]
    opts = []
    for w in zeile["w"]:
        for o in optionen:
            if w["text"] == o:
                opts.append((o, w))
    # „unzubereitetes Produkt“: das Wort steht, „Produkt“ folgt – Optionen sind Anfangswörter
    gewaehlt = []
    for x in xs:
        for o, w in opts:
            if 0 <= w["x0"] - x["x1"] < 12:
                gewaehlt.append(o)
    return gewaehlt


def _seite2(pdf, warn):
    zs = _folgeseiten_zeilen(pdf)
    txt = [z["text"] for z in zs]

    def idx(prefix):
        return next((i for i, t in enumerate(txt) if t.startswith(prefix)), None)

    i_bez, i_nw, i_zu = idx("Bezeichnung"), idx("Nährwertangaben"), idx("Zutatenverzeichnis")
    if None in (i_bez, i_nw, i_zu) or not (i_bez < i_nw < i_zu):
        raise KeinKennzeichnungspass("Seiten ab 2: Abschnitte Bezeichnung/Nährwertangaben/Zutatenverzeichnis nicht gefunden")

    bezeichnung = _norm(" ".join(txt[i_bez + 1:i_nw]))
    if not bezeichnung:
        warn("Bezeichnung leer")

    # --- Nährwerte
    nw_zeilen = zs[i_nw + 1:i_zu]
    naehrwerte = None
    nw_text = [z["text"] for z in nw_zeilen]
    if nw_text and nw_text[0].lower() == KEINE_INFO:
        naehrwerte = None
        if len(nw_text) > 1:
            warn(f"Nährwerte „keine Informationen“, aber weitere Zeilen: {nw_text[1:]}")
    else:
        bezug = zustand = None
        werte = {}
        nicht_angegeben = []
        for z in nw_zeilen:
            t = z["text"]
            if t.startswith("Die Angaben sind Durchschnittswerte"):
                continue
            if t.startswith("Referenzmenge"):
                g = _checkbox(z, ["100g", "100ml"])
                if len(g) == 1:
                    bezug = {"100g": "100 g", "100ml": "100 ml"}[g[0]]
                else:
                    warn(f"Referenzmenge nicht eindeutig lesbar (gefunden: {g})")
                continue
            if t.startswith("Verarbeitungsstatus"):
                g = _checkbox(z, ["unzubereitetes", "zubereitetes"])
                if len(g) == 1:
                    zustand = {"unzubereitetes": "UNPREPARED", "zubereitetes": "PREPARED"}[g[0]]
                elif not g:
                    zustand = None   # nicht angekreuzt: keine Angabe (kommt vor)
                else:
                    warn(f"Verarbeitungsstatus nicht eindeutig lesbar (gefunden: {g})")
                continue
            label = _norm(" ".join(w["text"] for w in z["w"] if w["x0"] < 375))
            wert = _norm(" ".join(w["text"] for w in z["w"] if w["x0"] >= 375))
            schluessel = NAEHRWERTE.get(label.lower())
            if schluessel is None:
                warn(f"Unbekannte Nährwertzeile: {t!r}")
                continue
            key, einheit = schluessel
            zahl_, ein, kl, status = parse_wert(wert)
            if status == "keine_angabe":
                nicht_angegeben.append(key)
            elif status == "unlesbar":
                warn(f"Nährwert {key} nicht lesbar: {wert!r}")
            else:
                if ein and ein != einheit:
                    warn(f"Nährwert {key}: Einheit {ein!r} statt {einheit!r}")
                werte[key] = {"wert": zahl_, "einheit": ein or einheit, "kleiner_als": kl}
        if bezug is None:
            warn("Referenzmenge fehlt")
        naehrwerte = {"bezug": bezug, "zustand": zustand, "werte": werte, "nicht_angegeben": nicht_angegeben}
        _plausi_naehrwerte(werte, warn)

    # --- Zutaten
    zu = zs[i_zu + 1:]
    zutaten = _zutaten(zu, warn)
    return bezeichnung, naehrwerte, zutaten


def _plausi_naehrwerte(w, warn):
    def v(k):
        return w[k]["wert"] if k in w else None
    kj, kcal = v("energie_kj"), v("energie_kcal")
    if kj and kcal and abs(kj / kcal - 4.1868) / 4.1868 > 0.03:
        warn(f"Plausibilität: {kj} kJ passt nicht zu {kcal} kcal")
    if v("fett_gesaettigt") is not None and v("fett") is not None and v("fett_gesaettigt") > v("fett") + 0.05:
        warn("Plausibilität: gesättigte Fettsäuren > Fett")
    if v("zucker") is not None and v("kohlenhydrate") is not None and v("zucker") > v("kohlenhydrate") + 0.05:
        warn("Plausibilität: Zucker > Kohlenhydrate")
    haupt = [v(k) for k in ("fett", "kohlenhydrate", "ballaststoffe", "eiweiss", "salz") if v(k) is not None]
    if haupt and sum(haupt) > 101.5:
        warn(f"Plausibilität: Nährstoffe summieren sich auf {sum(haupt):.1f} g (> 100)")


def _zutaten(zeilen, warn):
    if not zeilen:
        warn("Zutatenverzeichnis: kein Inhalt")
        return None
    erste = zeilen[0]["text"]
    if erste.lower() == KEINE_INFO:
        return None
    if erste.startswith("Bezeichnung") and "Anteil" in erste:
        return _zutaten_tabelle(zeilen[1:], warn)
    # Klartext: „Zutaten: …“ über mehrere Zeilen
    text = _norm(" ".join(z["text"] for z in zeilen))
    if text.startswith("Zutaten:"):
        text = text[len("Zutaten:"):].strip()
    else:
        warn("Zutaten im Klartext ohne Einleitung „Zutaten:“")
    return {"art": "PLAINTEXT", "text": text}


def _zutaten_tabelle(zeilen, warn):
    if not zeilen:
        return {"art": "STRUCTURED", "eintraege": []}
    eintraege = []
    x_min = min(z["x0"] for z in zeilen)
    # Spalte „Anteil“ = rechts; Name = alles links davon
    for z in zeilen:
        name = _norm(" ".join(w["text"] for w in z["w"] if w["x0"] < 440))
        anteil_txt = _norm(" ".join(w["text"] for w in z["w"] if w["x0"] >= 440))
        anteil = None
        if anteil_txt:
            zhl, ein, kl, status = parse_wert(anteil_txt if "%" in anteil_txt else anteil_txt + " %")
            if status != "wert":
                warn(f"Zutatenanteil nicht lesbar: {anteil_txt!r}")
            else:
                anteil = {"wert": zhl, "kleiner_als": kl}
        eintraege.append({"name": name, "anteil_prozent": anteil, "x0": z["x0"], "top": z["top"],
                          "bottom": z["bottom"]})
    # Umbruch oder neue Zutat? Zeilen ohne Anteil direkt unter einer Zeile mit gleichem Einzug,
    # deren Abstand kleiner als eine normale Tabellenzeile ist, gehören zur Zeile darüber.
    ergebnis = []
    for e in eintraege:
        if ergebnis:
            vor = ergebnis[-1]
            abstand = e["top"] - vor["top"]
            hoehe = vor["bottom"] - vor["top"]
            if e["anteil_prozent"] is None and abs(e["x0"] - vor["x0"]) < 2 and abstand < hoehe * 1.35:
                vor["name"] = _norm(vor["name"] + " " + e["name"])
                vor["top"] = e["top"]
                vor["bottom"] = e["bottom"]
                continue
            if e["anteil_prozent"] is None and abs(e["x0"] - vor["x0"]) < 2 and abstand < hoehe * 1.6:
                warn(f"Zutatenzeile unklar (Umbruch oder neue Zutat?): {e['name']!r}")
        ergebnis.append(e)
    schritt = None
    for e in ergebnis:
        e["ebene"] = 0
    # Einzug -> Unterzutaten (Ebene 1, 2, …)
    xs = sorted({round(e["x0"]) for e in ergebnis})
    for e in ergebnis:
        e["ebene"] = xs.index(round(e["x0"]))
    if len(xs) > 1:
        schritt = xs[1] - xs[0]
        warn(f"Zutaten mit Einzug (Unterzutaten) gelesen, Einzugsstufen: {len(xs)} – bitte prüfen")
    for e in ergebnis:
        for k in ("x0", "top", "bottom"):
            e.pop(k)
    summe = sum(e["anteil_prozent"]["wert"] for e in ergebnis if e["anteil_prozent"] and e["ebene"] == 0)
    if summe > 100.5:
        warn(f"Plausibilität: Summe der Zutatenanteile {summe:g} % > 100 %")
    return {"art": "STRUCTURED", "eintraege": ergebnis}



# Stichwörter in GROSSBUCHSTABEN (so kennzeichnet die EU-Verordnung Allergene in Zutatenlisten)
ALLERGEN_STICHWOERTE = {
    "WEIZEN": "weizen", "DINKEL": "weizen", "ROGGEN": "roggen", "GERSTE": "gerste", "HAFER": "hafer",
    "MILCH": "milch", "SOJA": "soja", "SESAM": "sesamsamen", "LUPINE": "lupinen",
    "ERDNUSS": "erdnuesse", "ERDNÜSSE": "erdnuesse", "MANDEL": "mandeln", "HASELNUSS": "haselnuesse",
    "HASELNÜSSE": "haselnuesse", "WALNUSS": "walnuesse", "WALNÜSSE": "walnuesse", "SELLERIE": "sellerie",
    "SENF": "senf",
}


def zutaten_allergen_hinweise(zutaten, allergene):
    """Hinweise (keine Korrektur!), wenn die Zutatenliste ein Allergen in Großbuchstaben nennt,
    das im Allergenraster („in Rezeptur / als Zutat enthalten“) nicht angekreuzt ist."""
    if not zutaten or not allergene or allergene.get("enthalten") is None:
        return []
    if zutaten["art"] == "PLAINTEXT":
        text = zutaten["text"]
    else:
        text = " ".join(e["name"] for e in zutaten["eintraege"])
    angekreuzt = set()
    for e in allergene["enthalten"]:
        angekreuzt.add(e["schluessel"])
        angekreuzt.update(u["schluessel"] for u in e["unter"])
    hinweise = []
    gefunden = set()
    for lauf in re.findall(r"[A-ZÄÖÜß]{3,}", text):
        for stich, key in ALLERGEN_STICHWOERTE.items():
            if stich in lauf:
                gefunden.add((key, stich))
    for key, stich in sorted(gefunden):
        if key not in angekreuzt:
            hinweise.append(f"Zutatenliste nennt {stich} in Großbuchstaben, im Allergenraster ist "
                            f"„{key}“ (Spalte „in Rezeptur / als Zutat enthalten“) nicht angekreuzt – bitte prüfen")
    return hinweise


# ----------------------------------------------------------------- Gesamt

def lese_pdf(pfad: str) -> dict:
    warnungen: list[str] = []
    warn = warnungen.append
    with pdfplumber.open(pfad) as pdf:
        meta = pdf.metadata or {}
        if (meta.get("Subject") or "").strip() != "Produktspezifikation":
            raise KeinKennzeichnungspass(f"Betreff ist {meta.get('Subject')!r}, nicht „Produktspezifikation“")
        if len(pdf.pages) < 2:
            raise KeinKennzeichnungspass("weniger als 2 Seiten")
        s1 = _seite1(pdf.pages[0], warn)
        alle = _allergene(pdf.pages[0], warn)
        allergene = _allergen_struktur(alle, warn)
        if alle and alle["zeilen"] and len(alle["zeilen"]) != 26:
            warn(f"Allergenraster hat {len(alle['zeilen'])} statt 26 Zeilen (Aufbau geändert?)")
        bezeichnung, naehrwerte, zutaten = _seite2(pdf, warn)
        kopf2 = _kopf_folgeseite(pdf)
        seiten = len(pdf.pages)

    # Titel: Dateimetadaten sind zuverlässig, der Seitentext verliert Zeichen
    # („DOONY?S“ statt „DOONY’S“, „Herstel ung“ statt „Herstellung“).
    titel_meta = _norm(meta.get("Title") or "")
    titel = re.sub(r"\s*\(Produkt-Nr\.\s*[^)]*\)\s*$", "", titel_meta) or None
    titel_text = s1.pop("_titel_seitentext")
    if not titel:
        titel = titel_text
        warn("Titel nicht in den Dateimetadaten, Seitentext verwendet (Zeichen können fehlen)")
    elif _norm(titel_text) != titel:
        # nur melden, wenn der Seitentext inhaltlich abweicht (Zeichenverlust)
        if re.sub(r"[^\w]", "", titel_text) != re.sub(r"[^\w]", "", titel):
            warn("Hinweis: Titel im Seitentext weicht von den Metadaten ab (Zeichenverlust im PDF); Metadaten verwendet")

    warnungen.extend(zutaten_allergen_hinweise(zutaten, allergene))

    # Abgleich Seite 1 / Folgeseite
    for k in ("produktnummer", "datenlink_id"):
        if kopf2.get(k) and s1.get(k) and kopf2[k] != s1[k]:
            warn(f"{k}: Seite 1 ({s1[k]}) ≠ Seite 2 ({kopf2[k]})")
    m = re.search(r"\(Produkt-Nr\.\s*([^)]*)\)\s*$", titel_meta)
    if m and s1.get("produktnummer") and m.group(1).strip() != s1["produktnummer"]:
        warn(f"Produktnummer in Metadaten ({m.group(1)}) ≠ Seite 1 ({s1['produktnummer']})")

    # XSD-Regel: fehlende Nährwerte/Zutaten und Klartext-Zutaten nur bei Quelle GDSN
    if s1["quelle"] != "GDSN":
        if naehrwerte is None:
            warn("Regelprüfung: keine Nährwerte bei Quelle datenlink (nach XSD nur bei GDSN erlaubt)")
        if zutaten is None or zutaten["art"] == "PLAINTEXT":
            warn("Regelprüfung: keine/Klartext-Zutaten bei Quelle datenlink (nach XSD nur bei GDSN erlaubt)")

    return {
        "schema": SCHEMA,
        "datenquelle": s1["quelle"],
        "hersteller": {"name": s1["datengeber"], "plz_ort": s1["plz_ort"], "land": s1["land"]},
        "produkt": {
            "datenlink_id": s1["datenlink_id"],
            "titel": titel,
            "nummern": [n for n in (
                {"typ": "MANUFACTURER", "wert": s1["produktnummer"]},
                {"typ": "GTIN", "wert": s1["gtin"]} if s1["gtin"] else None) if n],
            "gueltig_ab": s1["gueltig_ab"],
            "produktkennung": {"methodik": s1["produktkennung_methodik"],
                               "kennzeichen": s1["produktkennung_kennzeichen"]},
        },
        "lebensmittel": {
            "bezeichnung": bezeichnung,
            "naehrwerte": naehrwerte,
            "allergene": allergene,
            "zutaten": zutaten,
        },
        "seiten": seiten,
        "warnungen": warnungen,
        "_roh_allergenraster": alle,
    }


def main(argv):
    ergebnis = []
    for p in argv:
        try:
            r = lese_pdf(p)
            r.pop("_roh_allergenraster", None)
            ergebnis.append({"datei": p, "ergebnis": r})
        except KeinKennzeichnungspass as e:
            ergebnis.append({"datei": p, "abgelehnt": str(e)})
    json.dump(ergebnis, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main(sys.argv[1:])
