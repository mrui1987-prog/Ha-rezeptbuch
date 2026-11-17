"""Erzeugt Importvorlagen für die Tests (ohne Betriebsdaten, Spalten wie die echte Vorlage vom 14.11.2026)."""

from __future__ import annotations

import io

from openpyxl import Workbook

RECIPES = ["Import-ID", "Rezeptnummer (Vorschlag)", "Rezeptname", "Rezeptgruppe (Vorschlag)",
           "Knetzeit langsam (min)", "Knetzeit schnell (min)", "Hinweistext", "Hinweis anzeigen (Beginn/Ende)",
           "Gesamtgewicht g (Formel)", "Anzahl Zeilen (Formel)", "Name im Original (nicht importieren)",
           "Quelle (nicht importieren)", "Prüfen", "Bemerkung"]
LINES = ["Import-ID", "Rezeptname (Formel)", "Position", "Schritt", "Zeilenart (Rohstoff/Unterrezept)",
         "Zutat (bereinigt)", "Rohstoffnummer (Formel)", "Unterrezept Import-ID", "Menge Original",
         "Einheit Original (g/kg/ml/Stück/Maß)", "Faktor g je Einheit (Formel)", "Menge g (Formel)",
         "Toleranzeinheit (g/percent, optional)", "Toleranzwert (optional)", "Prüfen", "Bemerkung / Prüfgrund",
         "Originaltext (nicht importieren)", "Quelle (nicht importieren)"]
PIECES = ["Import-ID", "Rezeptname (Formel)", "Bezeichnung", "Gewicht g", "Reihenfolge", "Prüfen", "Bemerkung"]
BATCHES = ["Import-ID", "Rezeptname (Formel)", "Bezeichnung (Taste)", "Art (Gewicht/Stück)", "Wert (g bzw. Stück)",
           "Stückgewicht-Bezeichnung (nur bei Stück)", "Reihenfolge", "Prüfen", "Bemerkung"]
RAW = ["Nummer", "Name", "Kurzname", "Typ (standard/flour)", "Toleranz (Pflicht)", "Toleranzeinheit (g/percent)",
       "Gebindegröße g", "Gebindebezeichnung", "Herkunft", "archiviert", "Zeilen in Rezepten (Formel)",
       "Schreibweisen im Original (nicht importieren)", "Umrechnung Einheit (nur für den Rezeptimport)",
       "Gramm je Einheit (z. B. Eier: 65)"]
UNITS = ["Schlüssel (Einheit + Zutat)", "Gramm je Einheit", "Bemerkung"]


def recipe(import_id, name, number=None, group=None, slow=None, fast=None, note=None, display=None):
    return [import_id, number, name, group, slow, fast, note, display]


def line(import_id, zutat, menge, einheit="g", schritt=None, art="Rohstoff", sub=None, pos=None,
         tol_unit=None, tol=None, flag=None):
    return {"id": import_id, "pos": pos, "step": schritt, "art": art, "zutat": zutat, "sub": sub,
            "menge": menge, "unit": einheit, "tol_unit": tol_unit, "tol": tol, "flag": flag}


def raw(name, number=None, typ="standard", tol=None, unit=None, size=None, label=None, archived=0, short=None,
        conv_unit=None, conv=None):
    return [number, name, short, typ, tol, unit, size, label, "own", archived, conv_unit, conv]


def conv_only(name, conv_unit, conv, number=None):
    """Zeile im Blatt „Rohstoffe“ nur mit Name (bzw. Nummer) und Umrechnung (C3-E7, E7b)."""
    return [number, name, None, None, None, None, None, None, None, None, conv_unit, conv]


def build(recipes, lines, raw_materials=(), pieces=(), batches=(), units=(), *, footnotes=True,
          cached_grams=None, extra_sheets=None, skip=()) -> bytes:
    """Vorlage als .xlsx. ``cached_grams`` setzt in „Menge g (Formel)“ eine Zahl statt der Formel."""
    wb = Workbook()
    wb.remove(wb.active)

    def sheet(title, header):
        ws = wb.create_sheet(title)
        ws.append(header)
        return ws

    if "Rezepte" not in skip:
        ws = sheet("Rezepte", RECIPES)
        for i, r in enumerate(recipes, start=2):
            ws.append([*r, f'=SUMIFS(Rezeptzeilen!$L:$L,Rezeptzeilen!$A:$A,A{i})',
                       f"=COUNTIF(Rezeptzeilen!$A:$A,A{i})", "Original", "xlsb", None, None])
    if "Rezeptzeilen" not in skip:
        ws = sheet("Rezeptzeilen", LINES)
        for i, ln in enumerate(lines, start=2):
            grams = (cached_grams or {}).get(i)
            ws.append([ln["id"], f"=IFERROR(INDEX(Rezepte!$C:$C,MATCH(A{i},Rezepte!$A:$A,0)),\"\")", ln["pos"],
                       ln["step"], ln["art"], ln["zutat"], "=1", ln["sub"], ln["menge"], ln["unit"],
                       "=1", grams if grams is not None else f"=ROUND(I{i}*K{i},0)", ln["tol_unit"], ln["tol"],
                       ln["flag"], None, "orig", "xlsb"])
    if "Stückgewichte" not in skip:
        ws = sheet("Stückgewichte", PIECES)
        for p in pieces:
            ws.append([p[0], "=1", p[1], p[2], p[3] if len(p) > 3 else None])
    if "Chargengrößen" not in skip:
        ws = sheet("Chargengrößen", BATCHES)
        for i, b in enumerate(batches, start=2):
            value = b[3] if b[3] is not None else f"=SUMIFS(Rezeptzeilen!$L:$L,Rezeptzeilen!$A:$A,A{i})"
            ws.append([b[0], "=1", b[1], b[2], value, b[4] if len(b) > 4 else None, b[5] if len(b) > 5 else None])
    if "Rohstoffe" not in skip:
        ws = sheet("Rohstoffe", RAW)
        for r in raw_materials:
            ws.append([*r[:10], "=1", "orig", *r[10:]])
        if footnotes:
            ws.append([])
            ws.append(["Spalten A bis J entsprechen dem CSV-Format der Rohstoffe (Hinweis der Vorlage)."])
    if "Umrechnung" not in skip:
        ws = sheet("Umrechnung", UNITS)
        for u in units:
            ws.append([u[0], u[1], None])
        if footnotes:
            ws.append([])
            ws.append(["Gelb = eintragen/prüfen. Faktor wird nachgeschlagen; g = 1, kg = 1000."])
    for title, rows in (extra_sheets or {}).items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
