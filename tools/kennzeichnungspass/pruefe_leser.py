#!/usr/bin/env python3
"""Selbstprüfung des Kennzeichnungspass-Lesers an einem Ordner mit PDFs.

Aufruf:  python3 -I pruefe_leser.py ORDNER_ODER_PDFS...
Prüft je PDF und meldet Abweichungen; Rückgabewert 1 bei Fehlern.
Dateinamen im Format „Datengeber_-_Nummer_-_JJJJ-MM-TT_-_Titel.pdf“ (so erzeugt das Portal sie)
liefern Datum und Produktnummer zum Gegenprüfen.
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kennzeichnungspass import KeinKennzeichnungspass, gtin_pruefziffer_ok, lese_pdf  # noqa: E402


def pruefe(pfad):
    probleme = []
    r = lese_pdf(pfad)
    name = os.path.basename(pfad)
    m = re.search(r"-_(?P<nr>[^_].*?)_-_(?P<datum>\d{4}-\d{2}-\d{2})_-_", re.sub(r"^[0-9a-f]{8}-", "", name))
    if m:
        if m.group("datum") != r["produkt"]["gueltig_ab"]:
            probleme.append(f"Gültig ab {r['produkt']['gueltig_ab']} ≠ Dateiname {m.group('datum')}")
        nr = next(n["wert"] for n in r["produkt"]["nummern"] if n["typ"] == "MANUFACTURER")
        if m.group("nr").replace("_", ".") != nr and m.group("nr") != nr:
            probleme.append(f"Produktnummer {nr} ≠ Dateiname {m.group('nr')}")
    roh = r["_roh_allergenraster"]
    if roh:
        flags = sum(z["col"][s] for z in roh["zeilen"] for s in (0, 1))
        if flags != roh["anzahl_kreuze_x"]:
            probleme.append(f"Kreuze im PDF {roh['anzahl_kreuze_x']} ≠ gelesene Kennzeichen {flags}")
        if len(roh["zeilen"]) != 26:
            probleme.append(f"{len(roh['zeilen'])} statt 26 Allergenzeilen")
    for n in r["produkt"]["nummern"]:
        if n["typ"] == "GTIN" and not gtin_pruefziffer_ok(n["wert"]):
            probleme.append("GTIN-Prüfziffer falsch")
    for k in ("name",):
        if not r["hersteller"][k]:
            probleme.append("Hersteller fehlt")
    return r, probleme


def main(args):
    dateien = []
    for a in args:
        dateien += sorted(glob.glob(os.path.join(a, "*.pdf"))) if os.path.isdir(a) else [a]
    fehler = 0
    gesehen = {}
    for p in dateien:
        try:
            r, probleme = pruefe(p)
        except KeinKennzeichnungspass as e:
            print(f"ÜBERSPRUNGEN {os.path.basename(p)[:50]}: {e}")
            continue
        r.pop("_roh_allergenraster", None)
        ident = r["produkt"]["datenlink_id"]
        schl = json.dumps(r["lebensmittel"], sort_keys=True)
        if ident in gesehen and gesehen[ident] != schl:
            probleme.append("gleiche datenlink-ID, aber unterschiedliche Daten")
        gesehen[ident] = schl
        status = "OK " if not probleme else "FEHLER"
        hinweise = r["warnungen"]
        print(f"{status} {r['produkt']['titel'][:45]:45} {ident}  Hinweise: {len(hinweise)}")
        for t in probleme:
            print("      FEHLER:", t)
        for t in hinweise:
            print("      Hinweis:", t)
        fehler += bool(probleme)
    print(f"\n{len(dateien)} Dateien, {fehler} mit Fehlern")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
