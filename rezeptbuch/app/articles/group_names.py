"""Namen der Warengruppen aus der Vectron (Michael 24.11.2026, 12:56/13:03: „Warengruppen der Artikel benannt
statt Nummern im Planer“).

Quelle: Export der Warengruppen aus der Kasse (.xlsx) mit den Überschriften „Nummer“ und „Name“ (die übrigen
Spalten wie „A-Hauptgruppe“, Preistyp, Steuer … werden ignoriert). Gespeichert als eine Einstellung
``article_group_names`` (JSON, keine Migration). Ablauf wie die anderen Importe: ``mode=check`` → ``mode=run``.
Übersprungen: Zeilen ohne Nummer, Name leer oder „-“. Fehlt ein Name, zeigt die Oberfläche weiter die Nummer.
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile

from ..db import transaction
from ..errors import ValidationError
from ..raw_materials.models import normalize_text
from .vectron import _cell_int, _clean_name

SETTING_KEY = "article_group_names"
MAX_NAME = 40


def get_names(conn: sqlite3.Connection) -> dict[int, str]:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (SETTING_KEY,)).fetchone()
    if row is None:
        return {}
    try:
        data = json.loads(row["value"])
    except (TypeError, ValueError):
        return {}
    return {int(k): str(v) for k, v in data.items() if str(k).isdigit() and v}


def label(names: dict[int, str], group) -> str:
    """„12 Kuchen“ bzw. „WG 12“ ohne Namen."""
    if group is None:
        return "ohne Warengruppe"
    name = names.get(group)
    return f"{group} {name}" if name else f"WG {group}"


def read_groups(data: bytes) -> list[dict]:
    from openpyxl import load_workbook

    if not data:
        raise ValidationError("Die Datei ist leer.", code="empty_file")
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ValidationError("Die Datei ist keine lesbare Excel-Datei (.xlsx).", code="not_xlsx") from exc
    try:
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            for header in rows:
                names = [normalize_text(str(c)).casefold() if c is not None else "" for c in header]
                if "nummer" not in names or "name" not in names:
                    continue
                if "warengruppe" in names:
                    raise ValidationError("Das ist die Artikelliste, nicht die Liste der Warengruppen – bitte den "
                                          "Warengruppen-Export der Kasse wählen.", code="wrong_file")
                i_no, i_name = names.index("nummer"), names.index("name")
                result, seen = [], set()
                for r in rows:
                    number = _cell_int(r[i_no] if i_no < len(r) else None)
                    name = _clean_name(r[i_name] if i_name < len(r) else None)
                    if number is None or not name or name == "-":
                        continue
                    if number in seen:
                        raise ValidationError(f"Warengruppe {number} steht doppelt in der Datei.", code="duplicate")
                    seen.add(number)
                    result.append({"number": number, "name": name[:MAX_NAME]})
                return result
    finally:
        wb.close()
    raise ValidationError("Keine Tabelle mit den Überschriften „Nummer“ und „Name“ gefunden.", code="no_header")


def import_groups(conn: sqlite3.Connection, data: bytes, *, mode: str = "check") -> dict:
    if mode not in ("check", "run"):
        raise ValidationError("mode: check oder run.", field="mode")
    rows = read_groups(data)
    old = get_names(conn)
    used = {r["register_group"] for r in conn.execute("SELECT DISTINCT register_group FROM sales_article")}
    groups = [{**r, "old_name": old.get(r["number"]), "used": r["number"] in used} for r in rows]
    report = {"imported": False, "groups": groups,
              "counts": {"total": len(rows), "new": sum(1 for g in groups if g["old_name"] is None),
                         "changed": sum(1 for g in groups if g["old_name"] not in (None, g["name"])),
                         "used": sum(1 for g in groups if g["used"])},
              "without_name": sorted(g for g in used if g is not None and g not in {r["number"] for r in rows})}
    if mode == "run":
        value = json.dumps({str(r["number"]): r["name"] for r in rows}, ensure_ascii=False)
        with transaction(conn):
            conn.execute("INSERT INTO setting (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (SETTING_KEY, value))
        report["imported"] = True
    return report
