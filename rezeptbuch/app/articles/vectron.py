"""Import der Vectron-Artikelliste (.xlsx) – Modul 10, Teil P-A, docs/planer.md 4 (K10-P1 bis K10-P4).

Ablauf wie bei den anderen Importen: ``mode=check`` (Probelauf, Bericht) → ``mode=run`` mit derselben Datei.

* Spalten werden über die Überschrift gefunden: „Nummer“, „Name“, „Warengruppe“; alles andere
  (Preise, Bon-Sortierung, Steuer, Links …) wird ignoriert (K10-P4).
* Übersprungen: Zeilen ohne Nummer oder Namen, Zwischenüberschriften (Name beginnt mit „#“), Warengruppe 0.
* Übernommen werden nur die gewählten Warengruppen, Vorgabe 1–14 (K10-P1).
* Abgleich über die Kassennummer: neu → angelegt (mit „Stück je Ganzes“ nach Warengruppe, K10-P2),
  Name/Warengruppe geändert → übernommen, in der Datei nicht mehr vorhanden → „nicht mehr in der Kasse“
  (nie gelöscht), wieder vorhanden → zurück in der Kasse.
* Doppelte Nummern in der Datei → Fehler, nichts übernommen.
"""

from __future__ import annotations

import io
import sqlite3
import zipfile

from ..db import transaction
from ..errors import ValidationError
from ..raw_materials.models import normalize_text
from . import service

DEFAULT_GROUPS = tuple(range(1, 15))
MAX_ROWS = 20000
MAX_NAME = 80
LIST_LIMIT = 200


def _cell_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        return int(text) if text.isdigit() else None
    return None


def _clean_name(value) -> str:
    if value is None:
        return ""
    name = normalize_text(str(value))
    return name.replace("%%", "%")          # die Vectron schreibt „%“ in Namen als „%%“


def read_rows(data: bytes) -> list[dict]:
    """Liest die Artikelzeilen der ersten Tabelle mit den Überschriften Nummer/Name/Warengruppe."""
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
            columns = None
            for header in rows:
                names = [normalize_text(str(c)).casefold() if c is not None else "" for c in header]
                if "nummer" in names and "name" in names:
                    columns = {"number": names.index("nummer"), "name": names.index("name"),
                               "group": names.index("warengruppe") if "warengruppe" in names else None}
                    break
            if columns is None:
                continue
            result = []
            for line_no, values in enumerate(rows, start=2):
                if len(result) >= MAX_ROWS:
                    raise ValidationError(f"Die Datei hat mehr als {MAX_ROWS} Zeilen.", code="too_many_rows")
                values = list(values) + [None] * 3

                def get(key):
                    idx = columns[key]
                    return values[idx] if idx is not None and idx < len(values) else None

                result.append({"line": line_no, "number": _cell_int(get("number")), "name": _clean_name(get("name")),
                               "group": _cell_int(get("group"))})
            return result
    finally:
        wb.close()
    raise ValidationError("In der Datei fehlen die Spalten „Nummer“ und „Name“ (Artikelliste der Vectron).",
                          code="columns_missing")


def _parse_groups(groups) -> set[int]:
    if groups is None:
        return set(DEFAULT_GROUPS)
    if isinstance(groups, str):
        try:
            return {int(x) for x in groups.split(",") if x.strip()}
        except ValueError:
            raise ValidationError("Warengruppen: Liste von Zahlen (1,2,3).", field="groups") from None
    if isinstance(groups, (list, tuple, set)) and all(isinstance(g, int) and not isinstance(g, bool) for g in groups):
        return set(groups)
    raise ValidationError("Warengruppen: Liste von Zahlen.", field="groups")


def import_articles(conn: sqlite3.Connection, data: bytes, *, mode: str = "check", groups=None,
                    source: str = "import") -> dict:
    """Probelauf (``check``) oder Import (``run``) der Artikelliste; Ergebnis ist in beiden Fällen der Bericht."""
    if mode not in ("check", "run"):
        raise ValidationError("mode: check oder run.", field="mode")
    selected = _parse_groups(groups)
    rows = read_rows(data)

    skipped = {"heading": 0, "empty": 0, "group_0": 0}
    articles: dict[int, dict] = {}
    duplicates: dict[int, list[int]] = {}
    for r in rows:
        if r["number"] is None and not r["name"]:
            skipped["empty"] += 1
            continue
        if r["name"].startswith("#"):
            skipped["heading"] += 1
            continue
        if r["number"] is None or r["number"] <= 0 or not r["name"]:
            skipped["empty"] += 1
            continue
        if not r["group"]:
            skipped["group_0"] += 1
            continue
        if r["number"] in articles:
            duplicates.setdefault(r["number"], [articles[r["number"]]["line"]]).append(r["line"])
            continue
        articles[r["number"]] = {**r, "name": r["name"][:MAX_NAME]}
    if duplicates:
        listed = "; ".join(f"Nr. {n} (Zeilen {', '.join(map(str, lines))})" for n, lines in sorted(duplicates.items()))
        raise ValidationError(f"Doppelte Artikelnummern in der Datei: {listed}. Es wurde nichts übernommen.",
                              code="duplicate_numbers")

    found_groups: dict[int, int] = {}
    for a in articles.values():
        found_groups[a["group"]] = found_groups.get(a["group"], 0) + 1

    existing = {r["register_no"]: r for r in conn.execute("SELECT * FROM sales_article")}
    new, renamed, unchanged, returned = [], [], [], []
    for number in sorted(articles):
        a = articles[number]
        if a["group"] not in selected:
            continue
        old = existing.get(number)
        if old is None:
            new.append(a)
        elif old["name"] != a["name"] or old["register_group"] != a["group"]:
            renamed.append({**a, "old_name": old["name"], "old_group": old["register_group"],
                            "returned": not old["in_register"]})
        elif not old["in_register"]:
            returned.append(a)
        else:
            unchanged.append(a)
    missing = [r for no, r in sorted(existing.items()) if r["in_register"] and no not in articles]

    by_name: dict[str, list[int]] = {}
    for a in articles.values():
        if a["group"] in selected:
            by_name.setdefault(a["name"].casefold(), []).append(a["number"])
    same_names = [{"name": articles[nums[0]]["name"], "numbers": nums} for nums in by_name.values() if len(nums) > 1]

    def short(items, fields=("number", "name", "group")):
        return [{k: i[k] for k in fields if k in i} for i in items[:LIST_LIMIT]]

    report = {
        "mode": mode,
        "groups": [{"group": g, "count": c, "selected": g in selected} for g, c in sorted(found_groups.items())],
        "selected_groups": sorted(selected),
        "counts": {"new": len(new), "changed": len(renamed), "unchanged": len(unchanged), "returned": len(returned),
                   "missing": len(missing), "skipped_headings": skipped["heading"], "skipped_empty": skipped["empty"],
                   "skipped_group_0": skipped["group_0"]},
        "new": short(new),
        "changed": short(renamed, ("number", "name", "group", "old_name", "old_group")),
        "returned": short(returned),
        "missing": [{"number": r["register_no"], "name": r["name"]} for r in missing[:LIST_LIMIT]],
        "same_names": same_names[:LIST_LIMIT],
        "imported": False,
    }
    if mode == "check":
        return report

    now = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
    with transaction(conn):
        for a in new:
            ppw = service.DEFAULT_PIECES_PER_WHOLE.get(a["group"])
            article_id = conn.execute(
                "INSERT INTO sales_article (register_no, name, register_group, pieces_per_whole) VALUES (?, ?, ?, ?)",
                (a["number"], a["name"], a["group"], ppw)).lastrowid
            service.log(conn, "create", article_id, None,
                        {"register_no": a["number"], "name": a["name"], "register_group": a["group"],
                         "pieces_per_whole": ppw}, source)
        for a in renamed:
            old = existing[a["number"]]
            conn.execute(f"UPDATE sales_article SET name = ?, register_group = ?, in_register = 1, updated_at = {now} "
                         "WHERE id = ?", (a["name"], a["group"], old["id"]))
            service.log(conn, "update", old["id"],
                        {"name": old["name"], "register_group": old["register_group"],
                         "in_register": bool(old["in_register"])},
                        {"name": a["name"], "register_group": a["group"], "in_register": True}, source)
        for a in returned:
            old = existing[a["number"]]
            conn.execute(f"UPDATE sales_article SET in_register = 1, updated_at = {now} WHERE id = ?", (old["id"],))
            service.log(conn, "restore", old["id"], {"in_register": False}, {"in_register": True}, source)
        for old in missing:
            conn.execute(f"UPDATE sales_article SET in_register = 0, updated_at = {now} WHERE id = ?", (old["id"],))
            service.log(conn, "archive", old["id"], {"in_register": True}, {"in_register": False}, source)
    report["imported"] = True
    return report
