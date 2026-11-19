"""Rohstoff in Rezepten austauschen (Modul 05, Ergänzung C3-E9, Entscheidung Michael 18.11.2026).

Der Admin wählt den **alten Rohstoff**, den **neuen Rohstoff** mit Faktor und höchstens
**zwei Zusatzzutaten** mit Faktor. Angezeigt werden alle Rezepte, deren aktuelle Version den
alten Rohstoff direkt enthält; einzelne lassen sich abwählen. Entschieden (E9-1 bis E9-8):

* Neue Menge = alte Menge × Faktor, Faktor mit höchstens 3 Nachkommastellen, kaufmännisch auf
  ganze Gramm (wie Import K05-6). 0 g (Handzugabe) bleibt 0 g; ergibt eine Menge > 0
  rechnerisch 0 g, wird 1 g gesetzt.
* Zusatzzutaten: Faktor auf die **alte** Menge, direkt unter der getauschten Zeile, im selben
  Schritt, ohne eigene Toleranz. Steht die Zutat schon im Rezept: eigene Zeile (Hinweis).
* Jedes geänderte Rezept bekommt **immer eine neue Version** (alte bleibt „old (n)“).
* Rezeptauswahl: nicht archivierte Rezepte (öffentlich und gesperrt, Unterrezepte als eigene
  Rezepte), deren aktuelle Version den alten Rohstoff direkt enthält; mehrfache Zeilen werden alle
  getauscht.
* Eine eigene Zeilentoleranz der getauschten Zeile bleibt (Hinweis). Haken „geänderte Zeilen mit
  „*“ markieren“ (Standard aus). Status öffentlich/gesperrt bleibt.
* Haken „alten Rohstoff archivieren, wenn er in keiner aktuellen Version mehr vorkommt“.
* Prüfregeln: neuer ≠ alter Rohstoff, Zusatzzutat ≠ alter Rohstoff, archivierte Rohstoffe nicht
  wählbar, Faktor > 0; geänderter Bearbeitungsstand (anderes Gerät, KC2-6) → Rezept übersprungen.

Ablauf wie die Sammelaktionen (C3-E1): **Vorschau** (``mode="check"``) führt alles in einer
Transaktion aus und rollt zurück; **Ausführen** (``mode="run"``, ``confirm=True``) mit der Auswahl
``recipes = [{"id", "revision"}]``. Nicht mögliche Rezepte werden übersprungen und genannt.
"""

from __future__ import annotations

import sqlite3
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from ..errors import ConflictError, NotFoundError, ServiceError, ValidationError
from ..raw_materials import service as rm_service
from ..raw_materials import stock as stock_mod
from . import service

MAX_EXTRAS = 2
MAX_FACTOR = Decimal(1000)
MAX_RECIPES = 1000


# -- Eingabe -------------------------------------------------------------------------

def parse_factor(value, field: str, label: str = "Faktor") -> Decimal:
    """Faktor > 0 mit höchstens 3 Nachkommastellen (Komma oder Punkt)."""
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        raise ValidationError(f"{label} fehlt.", field=field)
    try:
        number = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        raise ValidationError(f"{label} muss eine Zahl sein (z. B. 0,82).", field=field) from None
    if not number.is_finite():
        raise ValidationError(f"{label} muss eine Zahl sein (z. B. 0,82).", field=field)
    if number <= 0:
        raise ValidationError(f"{label} muss größer 0 sein.", field=field)
    if number > MAX_FACTOR:
        raise ValidationError(f"{label} darf höchstens {MAX_FACTOR} sein.", field=field)
    if number != number.quantize(Decimal("0.001")):
        raise ValidationError(f"{label}: höchstens 3 Nachkommastellen.", field=field)
    return number


def _raw_material(conn: sqlite3.Connection, value, field: str, label: str, *, allow_archived: bool) -> dict:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{label}: bitte einen Rohstoff wählen.", field=field)
    try:
        item = rm_service.get_raw_material(conn, value)
    except NotFoundError:
        raise ValidationError(f"{label}: Rohstoff nicht gefunden.", field=field, code="not_found") from None
    if item["archived"] and not allow_archived:
        raise ValidationError(f"{label}: Der Rohstoff „{item['name']}“ ist archiviert und kann nicht neu "
                              "verwendet werden.", field=field, code="raw_material_archived")
    return {"id": item["id"], "number": item["number"], "name": item["name"], "archived": item["archived"]}


def _parse(conn: sqlite3.Connection, payload) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("Ungültige Eingabe.")
    old = _raw_material(conn, payload.get("old_raw_material_id"), "old_raw_material_id",
                        "Auszutauschender Rohstoff", allow_archived=True)
    new = _raw_material(conn, payload.get("new_raw_material_id"), "new_raw_material_id", "Neuer Rohstoff",
                        allow_archived=False)
    if new["id"] == old["id"]:
        raise ValidationError("Der neue Rohstoff muss sich vom alten unterscheiden.", field="new_raw_material_id")
    factor = parse_factor(payload.get("factor", 1), "factor")
    extras_raw = payload.get("extras") or []
    if not isinstance(extras_raw, list):
        raise ValidationError("Zusatzzutaten müssen eine Liste sein.", field="extras")
    extras_raw = [e for e in extras_raw if not (isinstance(e, dict) and e.get("raw_material_id") in (None, ""))]
    if len(extras_raw) > MAX_EXTRAS:
        raise ValidationError(f"Höchstens {MAX_EXTRAS} Zusatzzutaten.", field="extras")
    extras = []
    for index, raw in enumerate(extras_raw, start=1):
        if not isinstance(raw, dict):
            raise ValidationError(f"Zusatzzutat {index}: ungültige Angabe.", field=f"extras.{index}")
        item = _raw_material(conn, raw.get("raw_material_id"), f"extras.{index}.raw_material_id",
                             f"Zusatzzutat {index}", allow_archived=False)
        if item["id"] == old["id"]:
            raise ValidationError(f"Zusatzzutat {index} darf nicht der auszutauschende Rohstoff sein.",
                                  field=f"extras.{index}.raw_material_id")
        item["factor"] = parse_factor(raw.get("factor"), f"extras.{index}.factor", f"Zusatzzutat {index}: Faktor")
        extras.append(item)

    selection = payload.get("recipes")
    revisions: dict[int, int | None] | None = None
    if selection is not None:
        if not isinstance(selection, list):
            raise ValidationError("Rezeptauswahl muss eine Liste sein.", field="recipes")
        if len(selection) > MAX_RECIPES:
            raise ValidationError(f"Höchstens {MAX_RECIPES} Rezepte auf einmal.", field="recipes")
        revisions = {}
        for entry in selection:
            rid = entry.get("id") if isinstance(entry, dict) else entry
            if isinstance(rid, bool) or not isinstance(rid, int) or rid <= 0:
                raise ValidationError("Ungültige Rezept-ID in der Auswahl.", field="recipes")
            rev = entry.get("revision") if isinstance(entry, dict) else None
            revisions[rid] = rev if isinstance(rev, int) and not isinstance(rev, bool) else None
    return {"old": old, "new": new, "factor": factor, "extras": extras, "revisions": revisions,
            "mark_review": payload.get("mark_review") is True, "archive_old": payload.get("archive_old") is True}


# -- Rechnen ---------------------------------------------------------------------------

def scaled(amount_g: int, factor: Decimal) -> int:
    """Alte Menge × Faktor, kaufmännisch gerundet; 0 bleibt 0, sonst mindestens 1 g (E9-2)."""
    if amount_g == 0:
        return 0
    grams = int((Decimal(amount_g) * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return max(grams, 1)


def _factor_text(value: Decimal) -> str:
    return format(value.normalize(), "f").replace(".", ",")


def candidates(conn: sqlite3.Connection, raw_material_id: int) -> list[int]:
    """Nicht archivierte Rezepte, deren aktuelle Version den Rohstoff direkt enthält (E9-5)."""
    return [r["id"] for r in conn.execute(
        "SELECT DISTINCT r.id, r.number FROM recipe r JOIN recipe_item i ON i.recipe_version_id = r.current_version_id "
        "WHERE i.raw_material_id = ? AND r.archived = 0 ORDER BY r.number", (raw_material_id,))]


def _tolerance_input(tol: dict | None) -> dict:
    if tol is None:
        return {}
    return {"tolerance": str(tol["value"]), "tolerance_unit": tol["unit"]}


def _plan(recipe: dict, spec: dict) -> tuple[dict, list[dict], list[str]]:
    """Neue Eingabe für ``save_in_tx``, Änderungen je getauschter Zeile und Hinweise."""
    old_id, new = spec["old"]["id"], spec["new"]
    steps = {s["step_no"]: s["name"] for s in recipe["steps"]}
    present = {i["raw_material"]["id"] for i in recipe["items"] if i["type"] == "raw_material"}
    items, changes, hints = [], [], []
    for item in recipe["items"]:
        base = {"type": item["type"], "amount_g": item["amount_g"], "step_no": item["step_no"],
                "needs_review": item["needs_review"]}
        if item["type"] == "sub_recipe":
            items.append({**base, "sub_recipe_id": item["sub_recipe"]["id"]})
            continue
        if item["raw_material"]["id"] != old_id:
            items.append({**base, "raw_material_id": item["raw_material"]["id"],
                          **_tolerance_input(item["tolerance_override"])})
            continue
        old_g = item["amount_g"]
        new_g = scaled(old_g, spec["factor"])
        items.append({**base, "raw_material_id": new["id"], "amount_g": new_g,
                      "needs_review": item["needs_review"] or spec["mark_review"],
                      **_tolerance_input(item["tolerance_override"])})
        added = []
        for extra in spec["extras"]:
            grams = scaled(old_g, extra["factor"])
            items.append({"type": "raw_material", "raw_material_id": extra["id"], "amount_g": grams,
                          "step_no": item["step_no"], "needs_review": spec["mark_review"]})
            added.append({"name": extra["name"], "number": extra["number"], "amount_g": grams})
        changes.append({"position": item["position"], "step": steps.get(item["step_no"]), "old_g": old_g,
                        "new_g": new_g, "extras": added, "tolerance_override": item["tolerance_override"]})
        if item["tolerance_override"] is not None:
            tol = item["tolerance_override"]
            shown = (f"{tol['value']:g} %".replace(".", ",") if tol["unit"] == "percent" else f"{tol['value']} g")
            hints.append(f"Zeile {item['position']} behält ihre eigene Toleranz ({shown}).")
        if old_g == 0:
            hints.append(f"Zeile {item['position']} ist eine Handzugabe (0 g) und bleibt 0 g"
                         + (", ebenso die Zusatzzutaten." if spec["extras"] else "."))
    if new["id"] in present:
        hints.append(f"„{new['name']}“ steht schon im Rezept – die getauschte Zeile bleibt eine eigene Zeile.")
    for extra in spec["extras"]:
        if extra["id"] in present:
            hints.append(f"„{extra['name']}“ steht schon im Rezept – kommt als eigene Zeile dazu.")
    data = {"name": recipe["name"], "knead_slow_min": recipe["knead_slow_min"],
            "knead_fast_min": recipe["knead_fast_min"], "note": recipe["note"], "note_display": recipe["note_display"],
            "steps": [s["name"] for s in recipe["steps"]], "items": items}
    return data, changes, hints


def _archive_old(conn: sqlite3.Connection, old: dict, source: str) -> dict:
    """E9-7: alten Rohstoff archivieren, wenn er in keiner aktuellen Version eines aktiven Rezepts mehr steht."""
    if old["archived"]:
        return {"requested": True, "done": False, "reason": "Der Rohstoff ist bereits archiviert."}
    left = len(candidates(conn, old["id"]))
    if left:
        return {"requested": True, "done": False,
                "reason": f"„{old['name']}“ steht noch in {left} Rezept{'en' if left != 1 else ''} und wird nicht "
                          "archiviert."}
    rm_service.archive_in_tx(conn, old["id"], source=source)
    return {"requested": True, "done": True, "reason": f"„{old['name']}“ wird archiviert."}


# -- Ablauf ----------------------------------------------------------------------------

def replace_raw_material(conn: sqlite3.Connection, payload, *, source: str = "admin") -> dict:
    """Vorschau (``mode="check"``) oder Ausführung (``mode="run"``, ``confirm``) des Austauschs."""
    if not isinstance(payload, dict):
        raise ValidationError("Ungültige Eingabe.")
    mode = payload.get("mode", "check")
    if mode not in ("check", "run"):
        raise ValidationError("mode muss „check“ oder „run“ sein.", field="mode")
    confirm = payload.get("confirm") is True

    conn.execute("BEGIN IMMEDIATE")
    try:
        spec = _parse(conn, payload)
        if mode == "run" and spec["revisions"] is None:
            raise ValidationError("Bitte die Rezepte auswählen.", field="recipes")
        found = candidates(conn, spec["old"]["id"])
        selected = list(spec["revisions"]) if spec["revisions"] is not None else list(found)

        entries: list[dict] = []
        done: list[dict] = []
        skipped: list[dict] = []
        for rid in found:
            recipe = service.get_recipe(conn, rid)
            data, changes, hints = _plan(recipe, spec)
            entry = {"id": rid, "number": recipe["number"], "name": recipe["name"], "locked": recipe["locked"],
                     "revision": recipe["revision"], "version_no": recipe["version_no"], "frozen": recipe["frozen"],
                     "selected": rid in selected, "changes": changes, "hints": hints, "status": "not_selected"}
            entries.append(entry)
            if rid not in selected:
                continue
            wanted = spec["revisions"].get(rid) if spec["revisions"] is not None else None
            if wanted is not None and wanted != recipe["revision"]:
                entry["status"] = "skipped"
                entry["reason"] = "Das Rezept wurde inzwischen an einem anderen Gerät geändert – bitte neu laden."
                skipped.append({"id": rid, "number": recipe["number"], "name": recipe["name"], "reason": entry["reason"]})
                continue
            conn.execute("SAVEPOINT replace_one")
            try:
                service.save_in_tx(conn, rid, data, revision=recipe["revision"], version_mode="new", source=source,
                                   keep_review=True)
                after = conn.execute("SELECT v.version_no FROM recipe r JOIN recipe_version v "
                                     "ON v.id = r.current_version_id WHERE r.id = ?", (rid,)).fetchone()
            except ServiceError as exc:
                conn.execute("ROLLBACK TO replace_one")
                entry["status"], entry["reason"] = "skipped", exc.message
                skipped.append({"id": rid, "number": recipe["number"], "name": recipe["name"], "reason": exc.message})
            except sqlite3.IntegrityError as exc:
                conn.execute("ROLLBACK TO replace_one")
                entry["status"], entry["reason"] = "skipped", f"Konnte nicht gespeichert werden: {exc}"
                skipped.append({"id": rid, "number": recipe["number"], "name": recipe["name"], "reason": entry["reason"]})
            else:
                entry["status"] = "done"
                entry["new_version_no"] = after["version_no"]
                done.append({"id": rid, "number": recipe["number"], "name": recipe["name"],
                             "old_version": recipe["version_no"], "new_version": after["version_no"]})
            finally:
                conn.execute("RELEASE replace_one")
        for rid in selected:
            if rid not in found:
                row = conn.execute("SELECT r.number, v.name FROM recipe r LEFT JOIN recipe_version v "
                                   "ON v.id = r.current_version_id WHERE r.id = ?", (rid,)).fetchone()
                skipped.append({"id": rid, "number": row["number"] if row else None, "name": row["name"] if row else None,
                                "reason": "Das Rezept enthält den Rohstoff nicht (mehr) oder ist archiviert."})

        archive = {"requested": False, "done": False, "reason": None}
        if spec["archive_old"]:
            archive = _archive_old(conn, spec["old"], source)
        # VC03-b, B9: „Bestand auf Null setzen?“ – Antwort im Feld stock_zero; nichts geht auf den neuen über
        old_stock = conn.execute("SELECT stock_g FROM raw_material WHERE id = ?", (spec["old"]["id"],)).fetchone()[0]
        stock_zeroed = payload.get("stock_zero") is True and stock_mod.zero_in_tx(
            conn, spec["old"]["id"], note="beim Austauschen auf 0 gesetzt", source=source)

        needs_confirm = mode == "run" and not confirm
        executed = mode == "run" and not needs_confirm
        if executed:
            conn.execute("COMMIT")
        else:
            conn.execute("ROLLBACK")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    n = len(done)
    verb = "bekommen" if n != 1 else "bekommt"
    summary = (f"{n} Rezept{'e' if n != 1 else ''} {verb} eine neue Version"
               + ("" if executed else " (Vorschau)")
               + (f", {len(skipped)} übersprungen" if skipped else "") + ".")
    result = {
        "mode": mode, "executed": executed,
        "old": spec["old"], "new": spec["new"], "factor": _factor_text(spec["factor"]),
        "extras": [{"id": e["id"], "number": e["number"], "name": e["name"], "factor": _factor_text(e["factor"])}
                   for e in spec["extras"]],
        "mark_review": spec["mark_review"], "archive_old": archive,
        "old_stock_g": old_stock, "stock_zeroed": bool(stock_zeroed) and executed,
        "recipes": entries, "done": done, "skipped": skipped, "summary": summary,
        "counts": {"found": len(found), "selected": len(selected), "done": n, "skipped": len(skipped)},
    }
    if needs_confirm:
        raise ConflictError("Bitte den Austausch bestätigen.", code="confirmation_required", result=result)
    return result
