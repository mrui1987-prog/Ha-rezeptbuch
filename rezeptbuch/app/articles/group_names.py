"""Namen der Warengruppen und Hauptgruppen aus der Vectron (Michael 24.11.2026, 12:56/13:03: „Warengruppen der
Artikel benannt statt Nummern im Planer“; 13:2x: Planer nach den Hauptgruppen sortieren, Datei „Hauptgruppen.xlsx“).

Zwei Exporte der Kasse (.xlsx), beide mit den Überschriften „Nummer“ und „Name“; die Art wird erkannt:

* **Warengruppen** – zusätzlich Spalte „A-Hauptgruppe“: Namen der Warengruppen und ihre Hauptgruppe.
* **Hauptgruppen** – nur Nummer/Name: Namen der Hauptgruppen.

Gespeichert als Einstellungen (JSON, keine Migration): ``article_group_names`` (WG → Name),
``article_group_main`` (WG → Hauptgruppe), ``article_main_group_names`` (HG → Name).
Ablauf wie die anderen Importe: ``mode=check`` → ``mode=run``. Übersprungen: Zeilen ohne Nummer, Name leer
oder „-“; Hauptgruppe 0 = keine. Fehlt ein Name, zeigt die Oberfläche weiter die Nummer.
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
MAIN_KEY = "article_group_main"
MAIN_NAMES_KEY = "article_main_group_names"
MAX_NAME = 40
KIND_GROUPS, KIND_MAIN = "groups", "main_groups"


def _load(conn: sqlite3.Connection, key: str) -> dict[int, str]:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    if row is None:
        return {}
    try:
        data = json.loads(row["value"])
    except (TypeError, ValueError):
        return {}
    return {int(k): v for k, v in data.items() if str(k).isdigit() and v}


def get_names(conn: sqlite3.Connection) -> dict[int, str]:
    return {k: str(v) for k, v in _load(conn, SETTING_KEY).items()}


def get_main(conn: sqlite3.Connection) -> dict[int, int]:
    """Warengruppe → Hauptgruppe."""
    return {k: int(v) for k, v in _load(conn, MAIN_KEY).items() if str(v).isdigit() and int(v) > 0}


def get_main_names(conn: sqlite3.Connection) -> dict[int, str]:
    return {k: str(v) for k, v in _load(conn, MAIN_NAMES_KEY).items()}


def lookup(conn: sqlite3.Connection) -> dict:
    """Alle drei Zuordnungen auf einmal (für Listen)."""
    return {"names": get_names(conn), "main": get_main(conn), "main_names": get_main_names(conn)}


def describe(info: dict, group) -> dict:
    """Felder für einen Artikel: Name der Warengruppe, Hauptgruppe und deren Name."""
    main = info["main"].get(group)
    return {"register_group_name": info["names"].get(group), "main_group": main,
            "main_group_name": info["main_names"].get(main) if main is not None else None}


def label(names: dict[int, str], group) -> str:
    """„12 Kuchen“ bzw. „WG 12“ ohne Namen."""
    if group is None:
        return "ohne Warengruppe"
    name = names.get(group)
    return f"{group} {name}" if name else f"WG {group}"


def read_file(data: bytes) -> dict:
    """Liest einen der beiden Exporte: ``{"kind": "groups"|"main_groups", "rows": [{number, name, main?}]}``."""
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
                                          "Warengruppen- oder Hauptgruppen-Export der Kasse wählen.", code="wrong_file")
                i_no, i_name = names.index("nummer"), names.index("name")
                i_main = names.index("a-hauptgruppe") if "a-hauptgruppe" in names else None
                kind = KIND_GROUPS if i_main is not None else KIND_MAIN
                result, seen = [], set()
                for r in rows:
                    number = _cell_int(r[i_no] if i_no < len(r) else None)
                    name = _clean_name(r[i_name] if i_name < len(r) else None)
                    if number is None or not name or name == "-":
                        continue
                    if number in seen:
                        what = "Warengruppe" if kind == KIND_GROUPS else "Hauptgruppe"
                        raise ValidationError(f"{what} {number} steht doppelt in der Datei.", code="duplicate")
                    seen.add(number)
                    item = {"number": number, "name": name[:MAX_NAME]}
                    if i_main is not None:
                        main = _cell_int(r[i_main] if i_main < len(r) else None)
                        item["main"] = main if main and main > 0 else None
                    result.append(item)
                return {"kind": kind, "rows": result}
    finally:
        wb.close()
    raise ValidationError("Keine Tabelle mit den Überschriften „Nummer“ und „Name“ gefunden.", code="no_header")


def read_groups(data: bytes) -> list[dict]:
    return read_file(data)["rows"]


def _store(conn: sqlite3.Connection, key: str, value: dict) -> None:
    conn.execute("INSERT INTO setting (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, json.dumps({str(k): v for k, v in value.items()}, ensure_ascii=False)))


def import_groups(conn: sqlite3.Connection, data: bytes, *, mode: str = "check") -> dict:
    if mode not in ("check", "run"):
        raise ValidationError("mode: check oder run.", field="mode")
    parsed = read_file(data)
    kind, rows = parsed["kind"], parsed["rows"]
    used_wg = {r["register_group"] for r in conn.execute("SELECT DISTINCT register_group FROM sales_article")}
    if kind == KIND_GROUPS:
        old = get_names(conn)
        used = used_wg
        main_names = get_main_names(conn)
    else:
        old = get_main_names(conn)
        main = get_main(conn)
        used = {main[g] for g in used_wg if g in main}
        main_names = {}
    groups = []
    for r in rows:
        g = {**r, "old_name": old.get(r["number"]), "used": r["number"] in used}
        if kind == KIND_GROUPS:
            g["main_name"] = main_names.get(r["main"]) if r["main"] else None
        groups.append(g)
    report = {"imported": False, "kind": kind, "groups": groups,
              "counts": {"total": len(rows), "new": sum(1 for g in groups if g["old_name"] is None),
                         "changed": sum(1 for g in groups if g["old_name"] not in (None, g["name"])),
                         "used": sum(1 for g in groups if g["used"])},
              "without_name": sorted(g for g in used if g is not None and g not in {r["number"] for r in rows})}
    if kind == KIND_MAIN and not get_main(conn):
        report["hint"] = ("Noch keine Zuordnung Warengruppe → Hauptgruppe vorhanden: bitte zusätzlich den "
                          "Warengruppen-Export (mit Spalte „A-Hauptgruppe“) übernehmen.")
    if mode == "run":
        with transaction(conn):
            if kind == KIND_GROUPS:
                _store(conn, SETTING_KEY, {r["number"]: r["name"] for r in rows})
                _store(conn, MAIN_KEY, {r["number"]: r["main"] for r in rows if r["main"]})
            else:
                _store(conn, MAIN_NAMES_KEY, {r["number"]: r["name"] for r in rows})
        report["imported"] = True
    return report
