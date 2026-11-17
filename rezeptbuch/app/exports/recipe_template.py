"""Export der Rezepte als .xlsx im Format der Importvorlage (Modul 05, Teil C3, docs/rezepte.md 6.3).

Blätter wie die Vorlage: Rezepte, Rezeptzeilen, Stückgewichte, Chargengrößen, Rohstoffe (nur
verwendete) und eine leere Umrechnung; davor ein Blatt „Info“. Je Rezept die **aktuelle Version**;
Menge Original = Menge g, Einheit g (Faktor 1). Import-ID = „R“ + Rezeptnummer. Die Datei kann in
eine leere Datenbank wieder importiert werden (K05-1).

Alle Textzellen werden ausdrücklich als Text geschrieben, nie als Formel (Sperre B2): Ein alter
Name oder ein Hinweistext, der mit „=“ beginnt, bleibt in Excel ein harmloser Text.
Spalten mit „(nicht importieren)“ oder „(Formel)“ dienen nur der Information.
"""

from __future__ import annotations

import io
import sqlite3
from datetime import datetime

from .. import __version__
from ..raw_materials import service as rm_service
from ..recipes import service as recipe_service

RECIPE_HEADER = [
    "Import-ID", "Rezeptnummer", "Rezeptname", "Rezeptgruppe", "Knetzeit langsam (min)",
    "Knetzeit schnell (min)", "Hinweistext", "Hinweis anzeigen (Beginn = am Anfang und am Ende, Ende = nur am Ende)",
    "Notiz intern", "Status (nicht importieren)", "Version (nicht importieren)",
]
LINE_HEADER = [
    "Import-ID", "Rezeptname (nicht importieren)", "Position", "Schritt", "Zeilenart (Rohstoff/Unterrezept)",
    "Zutat (bereinigt)", "Rohstoffnummer (nicht importieren)", "Unterrezept Import-ID", "Menge Original",
    "Einheit Original (g/kg/ml/Stück/Maß)", "Faktor g je Einheit (Formel)", "Menge g (Formel)",
    "Toleranzeinheit (g/percent, optional)", "Toleranzwert (optional)", "Prüfen",
]
PIECE_HEADER = ["Import-ID", "Rezeptname (nicht importieren)", "Bezeichnung", "Gewicht g", "Reihenfolge"]
BATCH_HEADER = [
    "Import-ID", "Rezeptname (nicht importieren)", "Bezeichnung (Taste)", "Art (Gewicht/Stück)",
    "Wert (g bzw. Stück)", "Stückgewicht-Bezeichnung (nur bei Stück)", "Reihenfolge",
]
RAW_HEADER = [
    "Nummer", "Name", "Kurzname", "Typ", "Toleranz", "Toleranzeinheit", "Gebindegröße g",
    "Gebindebezeichnung", "Herkunft (nicht importieren)", "archiviert",
]
UNIT_HEADER = ["Schlüssel (Einheit + Zutat)", "Gramm je Einheit", "Bemerkung"]

WIDTHS = {
    "Rezepte": [10, 12, 30, 20, 12, 12, 50, 22, 40, 14, 12],
    "Rezeptzeilen": [10, 26, 9, 22, 14, 30, 12, 12, 12, 12, 10, 10, 12, 12, 8],
    "Stückgewichte": [10, 26, 24, 11, 11],
    "Chargengrößen": [10, 26, 24, 14, 14, 22, 11],
    "Rohstoffe": [9, 30, 16, 10, 10, 14, 14, 16, 12, 10],
    "Umrechnung": [30, 16, 50],
}


def import_id(number: int) -> str:
    return f"R{number}"


def _status(recipe: dict) -> str:
    if recipe["archived"]:
        return "archiviert"
    return "gesperrt" if recipe["locked"] else "öffentlich"


def _put(ws, row: int, values: list) -> None:
    """Schreibt eine Zeile; Texte immer als Text (nie Formel, B2)."""
    for column, value in enumerate(values, start=1):
        if value is None or value == "":
            continue
        cell = ws.cell(row=row, column=column)
        cell.value = value
        if isinstance(value, str):
            cell.data_type = "s"          # verhindert, dass „=…“ als Formel gespeichert wird


def _sheet(wb, title: str, header: list[str]):
    from openpyxl.styles import Font, PatternFill

    ws = wb.create_sheet(title)
    _put(ws, 1, header)
    bold = Font(bold=True)
    fill = PatternFill("solid", fgColor="DDDDDD")
    for column, width in enumerate(WIDTHS.get(title, []), start=1):
        ws.cell(row=1, column=column).font = bold
        ws.cell(row=1, column=column).fill = fill
        ws.column_dimensions[ws.cell(row=1, column=column).column_letter].width = width
    ws.freeze_panes = "A2"
    return ws


def _tolerance_cells(tolerance: dict | None) -> tuple:
    if tolerance is None:
        return None, None
    if tolerance["unit"] == "percent":
        return "percent", float(tolerance["value"])
    return "g", int(tolerance["value"])


def _selected(conn: sqlite3.Connection, include_archived: bool, ids: list[int] | None = None) -> list[dict]:
    """Rezepte für den Export; Unterrezepte der gewählten Rezepte kommen immer mit (auch archivierte).

    ``ids``: nur diese Rezepte (Auswahl in der Rezeptliste, C3-E1), dann ohne Rücksicht auf ``include_archived``.
    """
    every = {r["id"]: r for r in recipe_service.list_recipes(conn, include_locked=True, include_archived=True)}
    if ids is not None:
        chosen = {rid for rid in ids if rid in every}
    else:
        chosen = {rid for rid, r in every.items() if include_archived or not r["archived"]}
    details: dict[int, dict] = {}
    pending = list(chosen)
    while pending:
        rid = pending.pop()
        details[rid] = recipe_service.get_recipe(conn, rid)
        for item in details[rid]["items"]:
            sub = item.get("sub_recipe")
            if sub and sub["id"] not in chosen:
                chosen.add(sub["id"])
                pending.append(sub["id"])
    return sorted(details.values(), key=lambda r: r["number"])


def build_workbook(conn: sqlite3.Connection, include_archived: bool = False, ids: list[int] | None = None) -> bytes:
    """Erzeugt die .xlsx-Datei (alle Rezepte oder nur die Auswahl ``ids`` mit ihren Unterrezepten)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment

    recipes = _selected(conn, include_archived, ids)
    wb = Workbook()
    info = wb.active
    info.title = "Info"
    stamp = datetime.now().strftime("%d.%m.%Y %H:%M")
    archived_count = sum(1 for r in recipes if r["archived"])
    lines = [
        "HA-Rezeptbuch – Export der Rezepte",
        f"Erstellt am {stamp} mit Version {__version__}. {len(recipes)} Rezepte"
        + (" (Auswahl mit Unterrezepten)" if ids is not None else "")
        + (f", davon {archived_count} archiviert." if archived_count else "."),
        "Je Rezept die aktuelle Version. Mengen in Gramm (Einheit g, Faktor 1). Import-ID = R + Rezeptnummer.",
        "Wieder importierbar im Admin-Bereich unter „Import/Export“ (Vorlagen-Import). Rezeptnummern und "
        "Rezeptnamen dürfen in der Zieldatenbank noch nicht vorhanden sein; importierte Rezepte starten gesperrt.",
        "Rohstoffe werden beim Import über die Nummer zugeordnet und überschrieben (mit Rückfrage).",
        "Spalten mit „(nicht importieren)“ oder „(Formel)“ dienen nur der Information.",
    ]
    for row, text in enumerate(lines, start=1):
        _put(info, row, [text])
        info.cell(row=row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    info.column_dimensions["A"].width = 120

    ws_r = _sheet(wb, "Rezepte", RECIPE_HEADER)
    ws_l = _sheet(wb, "Rezeptzeilen", LINE_HEADER)
    ws_p = _sheet(wb, "Stückgewichte", PIECE_HEADER)
    ws_b = _sheet(wb, "Chargengrößen", BATCH_HEADER)
    ws_rm = _sheet(wb, "Rohstoffe", RAW_HEADER)
    _sheet(wb, "Umrechnung", UNIT_HEADER)

    used_rm: set[int] = set()
    r_row = l_row = p_row = b_row = 2
    for recipe in recipes:
        rid = import_id(recipe["number"])
        _put(ws_r, r_row, [
            rid, recipe["number"], recipe["name"], recipe["group_name"], recipe["knead_slow_min"],
            recipe["knead_fast_min"], recipe["note"], "Beginn" if recipe["note_display"] == "start" else "Ende",
            recipe.get("internal_note"), _status(recipe), recipe["version_no"],
        ])
        ws_r.cell(row=r_row, column=7).alignment = Alignment(wrap_text=True, vertical="top")
        r_row += 1
        steps = {s["step_no"]: s["name"] for s in recipe["steps"]}
        for item in recipe["items"]:
            if item["type"] == "raw_material":
                rm = item["raw_material"]
                used_rm.add(rm["id"])
                tol_unit, tol_value = _tolerance_cells(item["tolerance_override"])
                values = [rid, recipe["name"], item["position"], steps.get(item["step_no"]), "Rohstoff",
                          rm["name"], rm["number"], None]
            else:
                sub = item["sub_recipe"]
                tol_unit = tol_value = None
                values = [rid, recipe["name"], item["position"], steps.get(item["step_no"]), "Unterrezept",
                          sub["name"], None, import_id(sub["number"])]
            values += [item["amount_g"], "g", 1, item["amount_g"], tol_unit, tol_value,
                       "*" if item["needs_review"] else None]
            _put(ws_l, l_row, values)
            # 0 g = Handzugabe: Menge ausdrücklich als 0 schreiben (leer würde ebenfalls 0 g ergeben)
            ws_l.cell(row=l_row, column=9).value = item["amount_g"]
            ws_l.cell(row=l_row, column=12).value = item["amount_g"]
            l_row += 1
        for order, piece in enumerate(recipe["piece_weights"], start=1):
            _put(ws_p, p_row, [rid, recipe["name"], piece["label"], piece["weight_g"], order])
            p_row += 1
        for order, batch in enumerate(recipe["batch_sizes"], start=1):
            _put(ws_b, b_row, [rid, recipe["name"], batch["label"],
                               "Stück" if batch["kind"] == "pieces" else "Gewicht", batch["value"],
                               batch["piece_weight_label"] if batch["kind"] == "pieces" else None, order])
            b_row += 1

    rm_row = 2
    for rm in rm_service.list_raw_materials(conn, include_archived=True):
        if rm["id"] not in used_rm:
            continue
        percent = rm["tolerance_unit"] == "percent"
        _put(ws_rm, rm_row, [
            rm["number"], rm["name"], rm["display_name"], "Mehl" if rm["type"] == "flour" else "Standard",
            float(rm["tolerance"]) if percent else int(rm["tolerance"]), "%" if percent else "g",
            rm["unit_size_g"], rm["unit_label"], "BÄKO" if rm["source"] == "baeko" else "eigen",
            "ja" if rm["archived"] else "nein",
        ])
        ws_rm.cell(row=rm_row, column=5).value = float(rm["tolerance"]) if percent else int(rm["tolerance"])
        rm_row += 1

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def file_name() -> str:
    return f"rezepte_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
