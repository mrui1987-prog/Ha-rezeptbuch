#!/usr/bin/env python3
"""Leser für BÄKO-Belege (PDF): Auftragsbestätigung, Rechnung, Gutschrift -> JSON (Schema 1).

Grundlage: docs/bestand.md 8.1–8.4, docs/kennzeichnungspass-import.md 15.4 (M04-23, M04-25).
Liefert den Beleg so, wie er gedruckt ist – ohne Rohstoffe, ohne Umrechnung in Gramm.
Nichts wird geraten: Was nicht eindeutig lesbar ist, steht unter "warnungen"; dann gilt der
Beleg als unlesbar. Zahlen als Ganzzahlen (Tausendstel, Cent, Zehntausendstel Euro), die
gedruckten Texte stehen daneben.

Prüfungen (jede Abweichung ist eine Warnung):
- Summe der gelesenen Positionen = gedruckte Netto-Summe (bei Skonto je Position: nach Konditionen)
- je MwSt.-Satz: Summe der Positionen = gedruckter Netto-Betrag
- jeder Übertrag am Seitenende = laufende Summe bis dahin; Übertrag oben = Übertrag der Vorseite
- Rechnungsanlage/Artikelgruppen: Summe je Warengruppe = gedruckter Betrag (wo Warengruppen je Position stehen)

Aufruf:  python3 -I baeko_beleg.py beleg.pdf [...]   -> JSON auf stdout
"""
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

import pdfplumber

SCHEMA_VERSION = 1

ZEILEN_TOLERANZ = 4.5    # pt: Zeichen mit so wenig Höhenunterschied gehören zu einer Zeile
WORT_ABSTAND = 1.0       # pt: größerer Abstand trennt Wörter
RECHTS_X = 345.0         # ab hier: Menge, ME, Preis, PE, Netto, MwSt.
BESTELL_X = (320.0, 345.0)  # Kennzeichen "B" (Bestellartikel) in der Auftragsbestätigung
LINKS_ENDE_X = 60.0      # bis hier: Pos. bzw. WG

BELEGARTEN = {
    "Auftragsbestätigung": "auftragsbestaetigung",
    "Rechnung": "rechnung",
    "Gutschrift": "gutschrift",
}

PREISFAKTOR = {"EIN": 1, "HDT": 100, "TSD": 1000}
ZAHL = r"-?\d{1,3}(?:\.\d{3})*,\d+"
RE_RECHTS = re.compile(
    rf"^({ZAHL})\s?([A-ZÄÖÜ]{{1,4}})\s+({ZAHL})\s+(EIN|HDT|TSD|[A-ZÄÖÜ]{{1,4}})\s+({ZAHL})\s+(\d{{1,2}})$")
RE_KLAMMER = re.compile(r"^\(\s?(-?\d+)\s?([A-ZÄÖÜ]{1,4})\s?\)$")
RE_GEBINDE = re.compile(r"^-?\d[\d.,]*\s+[A-ZÄÖÜ]{1,4}\s+à\s+[\d.,]+\s+[A-ZÄÖÜ]{1,4}$")
RE_LIEFERUNG = re.compile(
    r"^(\S+) LS\.-Nr\.(?:-Strecke)?:\s*(\S+?),\s*Lieferdatum:\s*(\d\d\.\d\d\.\d{4})\s*(?:[,/]\s*(.*))?$")
RE_AUFTRAG = re.compile(
    r"^(?:Ihre Referenz:\s*(\S+?),\s*)?Auftrag:\s*(\S+)\s+vom\s+(\d\d\.\d\d\.\d{4})$")
RE_EXT = re.compile(r"^Ext\. Belegnummer:\s*(\S+)$")
RE_LIEFBELEG = re.compile(r"^Lieferantenbelegnr\.:\s*(\S+)$")
RE_SKONTO = re.compile(rf"^-\s*([\d,]+)\s*%\s*Skonto\b.*?\s({ZAHL})$")
RE_KONDITIONEN = re.compile(rf"Summe nach Konditionen:\s*({ZAHL})\s*\**$")
RE_UEBERTRAG = re.compile(rf"^Übertrag\s+({ZAHL})$")
RE_MWST = re.compile(rf"(?:^|\s)(\d{{1,2}})% MwSt\.:\s+({ZAHL})\s+({ZAHL})\s+({ZAHL})$")
RE_SUMME = re.compile(rf"^Summe:\s+({ZAHL})\s+({ZAHL})\s+({ZAHL})$")
RE_BELEGSUMME = re.compile(rf"^(Auftragssumme|Rechnungssumme|Gutschriftssumme) EUR:\s+({ZAHL})$")
RE_WG_ZEILE = re.compile(rf"^(\d{{3,4}}) (.+?)\s+({ZAHL})\s+({ZAHL})\s+({ZAHL})\s+({ZAHL})$")
RE_WG_SUMME = re.compile(rf"^Summe:\s+({ZAHL})\s+({ZAHL})\s+({ZAHL})\s+({ZAHL})$")
RE_DATUM = re.compile(r"(\d\d)\.(\d\d)\.(\d{4})")
BESTELL_TEXTE = ("Bestell-Artikel", "Lieferung erfolgt, sobald verfügbar")
ENDE_TEXTE = ("Ermäßigte", "Netto:", "Netto EUR")


# ---------------------------------------------------------------- Zahlen und Daten

def _dezimal(text):
    return Decimal(text.replace(".", "").replace(",", "."))


def _ganz(text, stellen):
    """'1.000,000' -> 1000000 bei stellen=3; exakt, sonst ValueError."""
    wert = _dezimal(text) * (10 ** stellen)
    if wert != wert.to_integral_value():
        raise ValueError(f"{text!r} hat mehr als {stellen} Nachkommastellen")
    return int(wert)


def _iso(text):
    m = RE_DATUM.search(text or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _euro(cent):
    s = f"{abs(cent) // 100:,}".replace(",", ".") + f",{abs(cent) % 100:02d}"
    return ("-" if cent < 0 else "") + s


# ---------------------------------------------------------------- Zeilen aus Zeichen

def _woerter(zeichen):
    """Zeichen einer Zeile -> Wörter. Grundlage ist die Reihenfolge im PDF: Ein Textlauf endet,
    wenn das nächste Zeichen nach links springt. Übereinander gedruckte Texte (kommt bei der BÄKO
    vor) bleiben so getrennte Läufe; jedes Wort trägt die Nummer seines Laufs."""
    laeufe = []
    for c in sorted(zeichen, key=lambda c: c["_i"]):
        if laeufe and c["x0"] >= laeufe[-1][-1]["x1"] - 0.5:
            laeufe[-1].append(c)
        else:
            laeufe.append([c])
    woerter = []
    for nr, lauf in enumerate(laeufe):
        akt = None
        for c in lauf:
            if c["text"].isspace():
                akt = None
                continue
            if akt and c["x0"] - akt["x1"] <= WORT_ABSTAND:
                akt["text"] += c["text"]
                akt["x1"] = c["x1"]
            else:
                akt = {"text": c["text"], "x0": c["x0"], "x1": c["x1"], "strang": nr}
                woerter.append(akt)
    return sorted(woerter, key=lambda w: w["x0"]), len(laeufe)


def _zeilen(seite):
    zeichen = [dict(c, _i=i) for i, c in enumerate(seite.dedupe_chars().chars)]
    zeichen.sort(key=lambda c: (c["top"], c["x0"]))
    gruppen = []
    for c in zeichen:
        if gruppen and c["top"] - gruppen[-1]["top"] <= ZEILEN_TOLERANZ:
            gruppen[-1]["zeichen"].append(c)
        else:
            gruppen.append({"top": c["top"], "zeichen": [c]})
    zeilen = []
    for g in gruppen:
        woerter, straenge = _woerter(g["zeichen"])
        if woerter:
            zeilen.append({"top": g["top"], "woerter": woerter, "straenge": straenge,
                           "text": " ".join(w["text"] for w in woerter)})
    return zeilen


def _text(woerter):
    return " ".join(w["text"] for w in woerter)


def _ueberlagert(woerter):
    """True, wenn sich Wörter in x überschneiden (überdruckte Zeile)."""
    for a, b in zip(woerter, woerter[1:]):
        if b["x0"] < a["x1"] - 0.5:
            return True
    return False


# ---------------------------------------------------------------- Kopf

def _kopfwert(zeilen, schluessel):
    for z in zeilen:
        t = z["text"]
        i = t.find(schluessel)
        if i >= 0:
            rest = t[i + len(schluessel):].strip()
            return rest
    return None


def _lies_kopf(zeilen, warnungen):
    """Kopf aus Seite 1, nur oberhalb der Positionstabelle (Name und Anschrift des Kunden werden
    bewusst nicht übernommen)."""
    ende = next((i for i, z in enumerate(zeilen) if "Beschreibung" in z["text"] and "Preis" in z["text"]),
                len(zeilen))
    zeilen = zeilen[:ende]
    kopf = {}
    alle = " ".join(z["text"] for z in zeilen)
    belegart = None
    for z in zeilen:
        for wort, art in BELEGARTEN.items():
            if re.fullmatch(rf"(?:Fortsetzung )?{wort}(?:\s+Seite\s+\d+)?", z["text"].strip()):
                belegart = belegart or art
    kopf["belegart"] = belegart
    for z in zeilen:
        m = re.match(r"^(.*?eG), Postfach", z["text"])
        if m:
            kopf["haendler"] = m.group(1)
            break
    else:
        kopf["haendler"] = None
    m = re.search(r"Belegnummer:\s*((?:AT|RE|GS)\d+)", alle)
    kopf["belegnummer"] = m.group(1) if m else None
    datum = _kopfwert(zeilen, "Auftragsdatum:") if belegart == "auftragsbestaetigung" else \
        _kopfwert(zeilen, "Belegdatum:")
    kopf["belegdatum"] = _iso(datum)
    kopf["lieferdatum_voraussichtlich"] = None
    if belegart == "auftragsbestaetigung":
        # "Voraussichtl." steht eine Zeile über "Lieferdatum: …"
        for z in zeilen:
            if z["text"].startswith("Lieferdatum:") or " Lieferdatum: " in f" {z['text']}":
                if "LS.-Nr." not in z["text"]:
                    kopf["lieferdatum_voraussichtlich"] = _iso(z["text"])
                    break
    kunde = _kopfwert(zeilen, "Kundennummer:")
    kopf["kundennummer"] = kunde.split()[0] if kunde else None
    kopf["kundennummer_text"] = kunde
    kopf["ausstelldatum_text"] = _kopfwert(zeilen, "Ausstelldatum:")
    ref = _kopfwert(zeilen, "Ihre Referenz:")
    kopf["ihre_referenz"] = ref.split()[0].rstrip(",") if ref else None
    kopf["versandart"] = _kopfwert(zeilen, "Versandart:")
    for feld in ("belegart", "haendler", "belegnummer", "belegdatum"):
        if not kopf.get(feld):
            warnungen.append(f"Kopf: {feld} nicht gefunden")
    if belegart and kopf.get("belegnummer"):
        vorsilbe = {"auftragsbestaetigung": "AT", "rechnung": "RE", "gutschrift": "GS"}[belegart]
        if not kopf["belegnummer"].startswith(vorsilbe):
            warnungen.append(f"Belegnummer {kopf['belegnummer']} passt nicht zur Belegart {belegart}")
    return kopf


# ---------------------------------------------------------------- Positionen

class _Leser:
    def __init__(self):
        self.positionen = []
        self.warnungen = []
        self.plausibilitaet = []
        self.lieferung = None
        self.auftrag = None
        self.ext_belegnummer = None
        self.lieferantenbeleg = None
        self.laufend = 0        # laufende Summe in Cent (nach Konditionen)
        self.uebertrag = None   # Übertrag am Ende der letzten Seite
        self.fuss = []          # Zeilen nach den Positionen (Summen, Anlage)
        self.layout = None      # "rechnung" (WG/Artikelnr./Anzahl) oder "pos" (Pos/Artikelnr.)

    # -- Hilfen
    def _pos(self):
        return self.positionen[-1] if self.positionen else None

    def _wert(self, pos):
        """Betrag, mit dem die Position in Überträge und Summen eingeht (nach Skonto)."""
        if pos["netto_nach_konditionen_cent"] is not None:
            return pos["netto_nach_konditionen_cent"]
        if pos["skonto"] is not None:  # Seitenumbruch zwischen Skonto- und Summenzeile
            return pos["netto_cent"] + pos["skonto"]["cent"]
        return pos["netto_cent"]

    def _summe_neu(self):
        return sum(self._wert(p) for p in self.positionen)

    # -- eine Seite
    def seite(self, nr, zeilen):
        kopfzeile = next((i for i, z in enumerate(zeilen)
                          if "Beschreibung" in z["text"] and "Preis" in z["text"]), None)
        if kopfzeile is None:
            # Seite ohne Positionstabelle (z. B. Rechnungsanlage)
            self.fuss.extend(zeilen)
            return
        kopf = zeilen[kopfzeile]
        besch = next(w for w in kopf["woerter"] if w["text"] == "Beschreibung")
        besch_x = besch["x0"] - 2.0
        layout = "rechnung" if kopf["woerter"][0]["text"] == "WG" else "pos"
        if self.layout and self.layout != layout:
            self.warnungen.append(f"Seite {nr}: Tabellenaufbau wechselt")
        self.layout = layout
        oben_gesehen = False
        for i, z in enumerate(zeilen[kopfzeile + 1:], start=kopfzeile + 1):
            t = z["text"]
            if t.startswith(("Mainzer Straße", "Allen Verkäufen")):
                break
            m = RE_UEBERTRAG.match(t)
            if m:
                wert = _ganz(m.group(1), 2)
                if not oben_gesehen and not self._seit_kopf_positionen(nr):
                    oben_gesehen = True
                    if self.uebertrag is not None and wert != self.uebertrag:
                        self.warnungen.append(
                            f"Seite {nr}: Übertrag oben {m.group(1)} ≠ Übertrag der Vorseite {_euro(self.uebertrag)}")
                    continue
                if wert != self._summe_neu():
                    self.warnungen.append(
                        f"Seite {nr}: Übertrag {m.group(1)} ≠ Summe der gelesenen Positionen {_euro(self._summe_neu())}")
                self.uebertrag = wert
                continue
            erstes = z["woerter"][0]
            if erstes["x0"] < LINKS_ENDE_X and not erstes["text"].isdigit():
                self.fuss.extend(zeilen[i:])
                return
            if any(t.startswith(e) for e in ENDE_TEXTE):
                self.fuss.extend(zeilen[i:])
                return
            self._zeile(nr, z, besch_x, layout)

    def _seit_kopf_positionen(self, nr):
        return any(p["seite"] == nr for p in self.positionen)

    def _zeile(self, nr, z, besch_x, layout):
        ws, ueberdruck = self._ueberdruck_trennen(z["woerter"])
        if len(ws) != len(z["woerter"]):
            z = dict(z, woerter=ws, text=_text(ws))
        vorher = len(self.positionen)
        self._zeile_einordnen(nr, z, besch_x, layout)
        if ueberdruck:
            pos = self._pos()
            if len(self.positionen) > vorher and vorher > 0:
                # auf der Zeile eines neuen Artikels: übergelaufene Zeile des vorigen Artikels
                pos = self.positionen[vorher - 1]
            if any(w["x0"] < besch_x or w["x1"] > RECHTS_X for w in ueberdruck) or not pos:
                self.warnungen.append(f"Seite {nr}: übereinander gedruckter Text außerhalb der Bezeichnung: "
                                      f"{_text(ueberdruck)!r}")
                return
            pos["bezeichnung_zeilen"].append(_text(ueberdruck))
            self.plausibilitaet.append(
                f"Seite {nr}: Text im PDF übereinander gedruckt ({_text(ueberdruck)!r}), getrennt gelesen und "
                f"Artikel {pos['artikelnummer']} zugeordnet – Zuordnung der Bezeichnung unsicher")

    @staticmethod
    def _ueberdruck_trennen(ws):
        """Wörter eines Nebenstrangs, die Wörter eines anderen Strangs überdecken, abtrennen."""
        if not _ueberlagert(ws):
            return ws, []
        laengen = {}
        for w in ws:
            laengen[w["strang"]] = laengen.get(w["strang"], 0) + len(w["text"])
        haupt = max(laengen, key=laengen.get)
        def deckt(w, v):
            return w["strang"] != v["strang"] and w["x0"] < v["x1"] - 0.5 and v["x0"] < w["x1"] - 0.5
        # Doppeldruck desselben Texts (leicht versetzt): den späteren Lauf weglassen
        doppelt = [w for w in ws if any(deckt(w, v) and v["text"] == w["text"] and v["strang"] < w["strang"]
                                        for v in ws)]
        ws = [w for w in ws if w not in doppelt]
        neben = [w for w in ws if any(deckt(w, v) for v in ws)
                 and laengen[w["strang"]] < max(laengen[v["strang"]] for v in ws if deckt(w, v))]
        return [w for w in ws if w not in neben], neben

    def _zeile_einordnen(self, nr, z, besch_x, layout):
        ws = z["woerter"]
        links = [w for w in ws if w["x1"] <= besch_x]
        rechts = [w for w in ws if w["x0"] >= RECHTS_X]
        mitte = [w for w in ws if w not in links and w not in rechts]
        t = z["text"]
        bestell = [w for w in mitte if w["text"] == "B" and BESTELL_X[0] <= w["x0"] < BESTELL_X[1]]
        mitte = [w for w in mitte if w not in bestell]
        mitte_text = _text(mitte)

        # Abschnittszeilen (Lieferschein, Auftrag, Belegnummern) – ganze Zeile, ohne Spalten links
        if not links:
            m = RE_LIEFERUNG.match(t)
            if m:
                self.lieferung = {"art": m.group(1), "lieferschein": m.group(2),
                                  "lieferdatum": _iso(m.group(3)), "zusatz": (m.group(4) or None)}
                self.auftrag = None
                self.lieferantenbeleg = None
                return
            m = RE_AUFTRAG.match(t)
            if m:
                self.auftrag = {"referenz": m.group(1), "auftrag": m.group(2), "auftragsdatum": _iso(m.group(3))}
                return
            m = RE_EXT.match(t)
            if m:
                self.ext_belegnummer = m.group(1)
                return
            m = RE_LIEFBELEG.match(t)
            if m:
                self.lieferantenbeleg = m.group(1)
                return

        # neue Position
        if links:
            self._neue_position(nr, z, links, mitte, rechts, bool(bestell), layout)
            return

        pos = self._pos()
        m = RE_SKONTO.match(t)
        if m and pos:
            if pos["skonto"] is not None:
                self.warnungen.append(f"Seite {nr}: zweite Skontozeile bei Artikel {pos['artikelnummer']}")
            pos["skonto"] = {"text": t[:t.rfind(m.group(2))].strip(), "prozent_text": m.group(1),
                             "cent": _ganz(m.group(2), 2)}
            return
        m = RE_KONDITIONEN.search(t)
        if m and pos:
            pos["netto_nach_konditionen_cent"] = _ganz(m.group(1), 2)
            if pos["skonto"] is None or pos["netto_cent"] + pos["skonto"]["cent"] != pos["netto_nach_konditionen_cent"]:
                self.warnungen.append(
                    f"Seite {nr}: Summe nach Konditionen bei Artikel {pos['artikelnummer']} passt nicht zu Netto − Skonto")
            return
        if rechts:
            m = RE_KLAMMER.match(_text(rechts))
            if m and pos and pos["gebinde_klammer"] is None:
                pos["gebinde_klammer"] = f"({m.group(1)} {m.group(2)})"
                rechts = []
        if rechts:
            self.warnungen.append(f"Seite {nr}: Zeile nicht zugeordnet: {t!r}")
            return
        if not pos:
            self.warnungen.append(f"Seite {nr}: Text vor der ersten Position: {t!r}")
            return
        self._text_zur_position(pos, mitte_text)

    def _text_zur_position(self, pos, text):
        if not text:
            return
        if set(text) == {"-"} or text in BESTELL_TEXTE:
            pos["bestell_hinweis"].append(text)
            return
        if self.layout == "pos" and RE_GEBINDE.match(text) and pos["gebinde_text"] is None:
            pos["gebinde_text"] = text
            return
        if pos["gebinde_text"] is not None:
            pos["zusatztext"].append(text)
        else:
            pos["bezeichnung_zeilen"].append(text)

    def _neue_position(self, nr, z, links, mitte, rechts, bestell, layout):
        t = z["text"]
        m = RE_RECHTS.match(_text(rechts))
        if not m:
            self.warnungen.append(f"Seite {nr}: Position nicht lesbar (Menge/Preis/Netto): {t!r}")
            return
        lt = [w["text"] for w in links]
        pos_nr = wg = anzahl = None
        if layout == "rechnung":
            if len(lt) < 2 or not lt[0].isdigit() or not re.fullmatch(r"\d{6}", lt[1]):
                self.warnungen.append(f"Seite {nr}: WG/Artikelnummer nicht lesbar: {t!r}")
                return
            wg, artikel, anzahl = lt[0], lt[1], " ".join(lt[2:]) or None
        else:
            if len(lt) != 2 or not lt[0].isdigit() or not re.fullmatch(r"\d{6}", lt[1]):
                self.warnungen.append(
                    f"Seite {nr}: Pos./Artikelnummer nicht lesbar (Spalte „Ihre Art.-Nr.“ gefüllt?): {t!r}")
                return
            pos_nr, artikel = int(lt[0]), lt[1]
        menge, me, preis, pe, netto, mwst = m.groups()
        pos = {
            "seite": nr,
            "pos": pos_nr,
            "warengruppe": wg,
            "artikelnummer": artikel,
            "anzahl_text": anzahl,
            "bezeichnung_zeilen": [],
            "bezeichnung": None,
            "gebinde_text": None,
            "gebinde_klammer": None,
            "zusatztext": [],
            "bestellartikel": bestell,
            "bestell_hinweis": [],
            "menge_text": menge,
            "menge_tausendstel": _ganz(menge, 3),
            "mengeneinheit": me,
            "preis_text": preis,
            "preis_zehntausendstel_euro": _ganz(preis, 4),
            "preiseinheit": pe,
            "netto_text": netto,
            "netto_cent": _ganz(netto, 2),
            "mwst_prozent": int(mwst),
            "skonto": None,
            "netto_nach_konditionen_cent": None,
            "lieferung": dict(self.lieferung) if self.lieferung else None,
            "auftrag": dict(self.auftrag) if self.auftrag else None,
            "ext_belegnummer": self.ext_belegnummer,
            "lieferantenbeleg": self.lieferantenbeleg,
        }
        if mitte:
            pos["bezeichnung_zeilen"].append(_text(mitte))
        self.positionen.append(pos)
        if pe in PREISFAKTOR:
            self._preis_pruefen(nr, pos)

    def _packungspreis_pruefen(self, pos):
        """Preiseinheit = Verpackung (z. B. KT): Menge steht in der Klammerzeile „(2 KT)“."""
        m = RE_KLAMMER.match(pos["gebinde_klammer"] or "")
        if not m or m.group(2) != pos["preiseinheit"]:
            self.plausibilitaet.append(
                f"Seite {pos['seite']}: Artikel {pos['artikelnummer']}: Preiseinheit {pos['preiseinheit']} "
                f"ohne passende Klammerzeile – Preis nicht prüfbar")
            return
        roh = Decimal(int(m.group(1))) * pos["preis_zehntausendstel_euro"] / 100
        if abs(roh - pos["netto_cent"]) > 1 + Decimal(m.group(1)):
            self.plausibilitaet.append(
                f"Seite {pos['seite']}: Artikel {pos['artikelnummer']}: {m.group(1)} {pos['preiseinheit']} × Preis "
                f"({roh / 100:.2f}) weicht vom Netto {pos['netto_text']} ab")

    def _preis_pruefen(self, nr, pos):
        faktor = PREISFAKTOR[pos["preiseinheit"]]
        # Menge (Tausendstel) × Preis (Zehntausendstel €) / Faktor -> Cent
        roh = Decimal(pos["menge_tausendstel"]) * pos["preis_zehntausendstel_euro"] / faktor / 100000
        # gedruckte Preise sind gerundet (AB: 2 Stellen) -> Spielraum: halbe letzte Stelle × Menge
        stellen = len(pos["preis_text"].split(",")[1])
        spiel = abs(Decimal(pos["menge_tausendstel"]) / 1000) * Decimal(5) / (10 ** stellen) * 100 / faktor + 1
        if abs(roh - pos["netto_cent"]) > spiel:
            self.plausibilitaet.append(
                f"Seite {nr}: Artikel {pos['artikelnummer']}: Menge × Preis ({roh / 100:.2f}) weicht vom Netto "
                f"{pos['netto_text']} ab")

    # -- Fuß: Summen, MwSt., Warengruppen, Zahlung
    def fuss_lesen(self, kopf):
        summen = {"netto_cent": None, "mwst_cent": None, "brutto_cent": None, "belegsumme_cent": None,
                  "mwst_saetze": []}
        warengruppen = []
        wg_summe = None
        zahlung = None
        in_anlage = False
        for z in self.fuss:
            t = z["text"]
            if t.startswith("Artikelgruppe"):
                in_anlage = True
                continue
            if in_anlage:
                m = RE_WG_ZEILE.match(t)
                if m:
                    warengruppen.append({"warengruppe": m.group(1), "name": m.group(2).strip(),
                                         "ohne_mwst_cent": _ganz(m.group(3), 2),
                                         "ermaessigt_cent": _ganz(m.group(4), 2),
                                         "voll_cent": _ganz(m.group(5), 2), "betrag_cent": _ganz(m.group(6), 2)})
                    continue
                m = RE_WG_SUMME.match(t)
                if m:
                    wg_summe = _ganz(m.group(4), 2)
                    in_anlage = False
                    continue
            m = RE_MWST.search(t)
            if m:
                summen["mwst_saetze"].append({"satz": int(m.group(1)), "netto_cent": _ganz(m.group(2), 2),
                                              "mwst_cent": _ganz(m.group(3), 2),
                                              "brutto_cent": _ganz(m.group(4), 2)})
                continue
            m = RE_SUMME.match(t)
            if m and summen["netto_cent"] is None:
                summen["netto_cent"], summen["mwst_cent"], summen["brutto_cent"] = (
                    _ganz(m.group(1), 2), _ganz(m.group(2), 2), _ganz(m.group(3), 2))
                continue
            m = RE_BELEGSUMME.match(t)
            if m:
                summen["belegsumme_cent"] = _ganz(m.group(2), 2)
                continue
            if t.startswith(("Abbuchung zum", "Gutschrift zum", "Zahlbar")):
                zahlung = t
        gelesen = self._summe_neu()
        summen["gelesen_netto_cent"] = gelesen
        if summen["netto_cent"] is None:
            self.warnungen.append("Netto-Summe des Belegs nicht gefunden")
        elif gelesen != summen["netto_cent"]:
            self.warnungen.append(
                f"Summe der Positionen {_euro(gelesen)} ≠ Netto-Summe des Belegs {_euro(summen['netto_cent'])}")
        if summen["belegsumme_cent"] is not None and summen["brutto_cent"] is not None \
                and summen["belegsumme_cent"] != summen["brutto_cent"]:
            self.warnungen.append("Belegsumme ≠ Brutto-Summe")
        for satz in summen["mwst_saetze"]:
            s = sum(self._wert(p) for p in self.positionen if p["mwst_prozent"] == satz["satz"])
            if s != satz["netto_cent"]:
                self.warnungen.append(
                    f"{satz['satz']} % MwSt.: Positionen {_euro(s)} ≠ gedruckt {_euro(satz['netto_cent'])}")
        if summen["mwst_saetze"] and {p["mwst_prozent"] for p in self.positionen} - {
                s["satz"] for s in summen["mwst_saetze"]}:
            self.warnungen.append("Position mit MwSt.-Satz, der in den Summen fehlt")
        if warengruppen:
            if wg_summe is not None and wg_summe != sum(w["betrag_cent"] for w in warengruppen):
                self.warnungen.append("Artikelgruppen: Einzelbeträge ergeben nicht die Summe")
            if all(p["warengruppe"] for p in self.positionen):
                for w in warengruppen:
                    s = sum(self._wert(p) for p in self.positionen if p["warengruppe"] == w["warengruppe"])
                    if abs(s) != abs(w["betrag_cent"]):
                        self.warnungen.append(
                            f"Warengruppe {w['warengruppe']}: Positionen {_euro(s)} ≠ Anlage {_euro(w['betrag_cent'])}")
                fehlend = {p["warengruppe"] for p in self.positionen} - {w["warengruppe"] for w in warengruppen}
                if fehlend:
                    self.warnungen.append(f"Warengruppen ohne Eintrag in der Anlage: {sorted(fehlend)}")
        if kopf.get("belegart") == "gutschrift":
            if any(p["netto_cent"] > 0 for p in self.positionen):
                self.plausibilitaet.append("Gutschrift mit positiver Position")
        elif any(p["netto_cent"] < 0 for p in self.positionen):
            self.plausibilitaet.append("Negative Position auf einer Auftragsbestätigung/Rechnung")
        return summen, warengruppen, zahlung


def lese_beleg(pfad):
    """PDF -> Daten (Schema 1). Wirft nur bei kaputten PDFs; Leserprobleme stehen in "warnungen"."""
    pfad = Path(pfad)
    with pdfplumber.open(pfad) as pdf:
        seiten = [_zeilen(s) for s in pdf.pages]
    leser = _Leser()
    kopf = _lies_kopf(seiten[0] if seiten else [], leser.warnungen)
    for nr, zeilen in enumerate(seiten, start=1):
        leser.seite(nr, zeilen)
    summen, warengruppen, zahlung = leser.fuss_lesen(kopf)
    if not leser.positionen:
        leser.warnungen.append("Keine Positionen gefunden")
    for p in leser.positionen:
        p["bezeichnung"] = " ".join(p["bezeichnung_zeilen"]) or None
        if p["bestellartikel"] and not p["bestell_hinweis"]:
            leser.plausibilitaet.append(f"Artikel {p['artikelnummer']}: „B“ ohne Hinweistext")
        if p["preiseinheit"] not in PREISFAKTOR:
            leser._packungspreis_pruefen(p)
    for i, p in enumerate(leser.positionen, start=1):
        p["nr"] = i
    return {
        "schema": SCHEMA_VERSION,
        "datei": pfad.name,
        "seiten": len(seiten),
        **kopf,
        "positionen": leser.positionen,
        "summen": summen,
        "warengruppen": warengruppen,
        "zahlung_text": zahlung,
        "plausibilitaet": leser.plausibilitaet,
        "warnungen": leser.warnungen,
    }


def ist_baeko_beleg(erste_seite_text):
    return "BÄKO" in erste_seite_text and any(w in erste_seite_text for w in BELEGARTEN)


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    for d in argv:
        print(json.dumps(lese_beleg(d), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
