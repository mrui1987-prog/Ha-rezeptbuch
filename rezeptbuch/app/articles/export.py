"""Export der Verkaufsartikel mit Stücklisten als .xlsx (docs/planer.md 4, K10-P14) – Sicherung und Überblick.

Ein Re-Import der Stücklisten kommt später als eigener Teil (K10-P14).
"""

from __future__ import annotations

import io
import sqlite3
from datetime import datetime

from . import service

ARTICLE_HEADER = ["Nummer", "Name", "Warengruppe", "Stück je Ganzes", "Planen", "In der Kasse", "Bemerkung",
                  "Zeilen Stückliste", "Summe g je Stück/Ganzes"]
LINE_HEADER = ["Artikelnummer", "Artikel", "Zeile", "Art", "Rezept-/Rohstoffnummer", "Name", "Menge g",
               "Stückgewicht", "Stück", "g gesamt", "Hinweis"]


def _put(ws, row: int, values: list) -> None:
    for column, value in enumerate(values, start=1):
        if value is None or value == "":
            continue
        cell = ws.cell(row=row, column=column)
        cell.value = value
        if isinstance(value, str):
            cell.data_type = "s"          # nie als Formel (B2)


def _header(ws, values: list, widths: list[int]) -> None:
    from openpyxl.styles import Font, PatternFill

    _put(ws, 1, values)
    for column, width in enumerate(widths, start=1):
        cell = ws.cell(row=1, column=column)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDDDDD")
        ws.column_dimensions[cell.column_letter].width = width
    ws.freeze_panes = "A2"


def build_workbook(conn: sqlite3.Connection, status: str = "all") -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws_a = wb.active
    ws_a.title = "Artikel"
    _header(ws_a, ARTICLE_HEADER, [10, 34, 12, 14, 8, 12, 30, 12, 18])
    ws_l = wb.create_sheet("Stückliste")
    _header(ws_l, LINE_HEADER, [12, 30, 6, 9, 20, 30, 10, 18, 8, 10, 20])
    row_a, row_l = 2, 2
    for item in service.list_articles(conn, status=status):
        art = service.get_article(conn, item["id"])
        _put(ws_a, row_a, [art["register_no"], art["name"], art["register_group"], art["pieces_per_whole"],
                           "ja" if art["plan_enabled"] else "nein", "ja" if art["in_register"] else "nein",
                           art["note"], len(art["lines"]), art["sum_g"] if art["lines"] else None])
        row_a += 1
        for ln in art["lines"]:
            if ln["kind"] == "recipe":
                piece = (f"{ln['piece_weight_label']} ({ln['piece_weight_g']} g)" if ln["piece_weight_id"] else None)
                values = [art["register_no"], art["name"], ln["position"], "Rezept", ln["recipe_number"], ln["name"],
                          ln["amount_g"], piece, None, ln["grams"], ln["warning"]]
            else:
                values = [art["register_no"], art["name"], ln["position"], "Rohstoff", ln["raw_number"], ln["name"],
                          ln["amount_g"], None, ln["amount_pieces"], ln["grams"], ln["warning"]]
            _put(ws_l, row_l, values)
            row_l += 1
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def file_name() -> str:
    return f"verkaufsartikel_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
