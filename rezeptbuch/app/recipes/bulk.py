"""Sammelaktionen in der Rezeptliste (Modul 05, Ergänzung C3-E1, Wunsch Michael 17.11.2026).

Mehrere angehakte Rezepte auf einmal **freischalten, sperren, archivieren oder löschen**
(Exportieren der Auswahl läuft über den Export, ``ids``). Es gelten dieselben Regeln wie
für ein einzelnes Rezept – die Sammelaktion ruft die Funktionen der Service-Schicht auf.

Ablauf wie beim Import: **Vorschau** (``mode="check"``) führt alles in einer Transaktion aus
und rollt zurück; sie meldet, was ausgeführt würde, was übersprungen wird (mit Grund) und
die Warnungen beim Freischalten („*“, Toleranz 0 %). Danach **Ausführen** (``mode="run"``,
``confirm=True``) mit derselben Auswahl.

Anders als der Import gilt hier **nicht** „alles oder nichts“: Rezepte, für die die Aktion
nicht erlaubt ist (z. B. ohne Zeilen freischalten, als Unterrezept verwendet archivieren,
verwendetes Rezept löschen), werden übersprungen und im Ergebnis mit Grund genannt; die
übrigen werden ausgeführt. Die Vorschau zeigt das vor der Bestätigung.

Reihenfolge: Beim Archivieren und Löschen wird so lange wiederholt, bis nichts mehr geht.
So lassen sich ein Rezept und sein Unterrezept gemeinsam archivieren bzw. löschen, wenn
beide angehakt sind.
"""

from __future__ import annotations

import sqlite3

from ..errors import ConflictError, NotFoundError, ServiceError, ValidationError
from . import service

ACTIONS = ("unlock", "lock", "archive", "delete")
MAX_IDS = 1000
ACTION_LABEL = {"unlock": "freigeschaltet", "lock": "gesperrt", "archive": "archiviert", "delete": "gelöscht"}


def _clean_ids(ids) -> list[int]:
    if not isinstance(ids, list) or not ids:
        raise ValidationError("Bitte mindestens ein Rezept auswählen.", field="ids")
    if len(ids) > MAX_IDS:
        raise ValidationError(f"Höchstens {MAX_IDS} Rezepte auf einmal.", field="ids")
    result: list[int] = []
    for value in ids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValidationError("Ungültige Rezept-ID in der Auswahl.", field="ids")
        if value not in result:
            result.append(value)
    return result


def _head(conn: sqlite3.Connection, recipe_id: int) -> dict:
    row = conn.execute(
        "SELECT r.id, r.number, v.name FROM recipe r LEFT JOIN recipe_version v ON v.id = r.current_version_id "
        "WHERE r.id = ?", (recipe_id,)).fetchone()
    if row is None:
        raise NotFoundError("Rezept nicht gefunden.")
    return {"id": row["id"], "number": row["number"], "name": row["name"]}


def _apply(conn: sqlite3.Connection, action: str, recipe_id: int, source: str):
    """Eine Aktion für ein Rezept. Rückgabe: (geändert?, Warnungen)."""
    if action == "unlock":
        before = conn.execute("SELECT locked FROM recipe WHERE id = ?", (recipe_id,)).fetchone()
        warnings = service.unlock_in_tx(conn, recipe_id, confirm=True, source=source)
        return bool(before and before["locked"]), warnings
    if action == "lock":
        return service.lock_in_tx(conn, recipe_id, source=source), None
    if action == "archive":
        service.archive_in_tx(conn, recipe_id, source=source)
        return True, None
    service.delete_in_tx(conn, recipe_id, source=source)
    return True, None


def bulk_action(conn: sqlite3.Connection, action: str, ids, *, mode: str = "check", confirm: bool = False,
                source: str = "admin") -> dict:
    """Vorschau oder Ausführung einer Sammelaktion. Ergebnis siehe Moduldoku."""
    if action not in ACTIONS:
        raise ValidationError("Aktion muss unlock, lock, archive oder delete sein.", field="action")
    if mode not in ("check", "run"):
        raise ValidationError("mode muss „check“ oder „run“ sein.", field="mode")
    recipe_ids = _clean_ids(ids)

    done: list[dict] = []
    unchanged: list[dict] = []
    skipped: list[dict] = []
    warnings: list[dict] = []
    conn.execute("BEGIN IMMEDIATE")
    try:
        heads = {}
        for rid in recipe_ids:
            try:
                heads[rid] = _head(conn, rid)
            except NotFoundError:
                skipped.append({"id": rid, "number": None, "name": None, "reason": "Rezept nicht gefunden."})
        pending = [rid for rid in recipe_ids if rid in heads]
        # Archivieren/Löschen: wiederholen, solange etwas vorangeht (Haupt- und Unterrezept gemeinsam)
        while pending:
            failed: dict[int, str] = {}
            progress = False
            for rid in pending:
                conn.execute("SAVEPOINT bulk_one")
                try:
                    changed, warn = _apply(conn, action, rid, source)
                except ServiceError as exc:
                    conn.execute("ROLLBACK TO bulk_one")
                    failed[rid] = exc.message
                except sqlite3.IntegrityError:
                    conn.execute("ROLLBACK TO bulk_one")
                    failed[rid] = "Wird noch verwendet."
                else:
                    progress = True
                    entry = dict(heads[rid])
                    (done if changed else unchanged).append(entry)
                    if warn:
                        warnings.append({**entry, "review_count": len(warn["review_items"]),
                                         "zero_percent_count": len(warn["zero_percent_items"]),
                                         **warn})
                finally:
                    conn.execute("RELEASE bulk_one")
            pending = [rid for rid in pending if rid in failed]
            if not progress or action not in ("archive", "delete"):
                skipped.extend({**heads[rid], "reason": failed[rid]} for rid in pending)
                break

        needs_confirm = mode == "run" and not confirm
        if mode == "run" and not needs_confirm:
            conn.execute("COMMIT")
        else:
            conn.execute("ROLLBACK")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    order = {rid: i for i, rid in enumerate(recipe_ids)}
    for group in (done, unchanged, skipped):
        group.sort(key=lambda e: order.get(e["id"], 0))
    result = {
        "action": action, "mode": mode, "executed": mode == "run" and not needs_confirm,
        "done": done, "unchanged": unchanged, "skipped": skipped, "warnings": warnings,
        "counts": {"selected": len(recipe_ids), "done": len(done), "unchanged": len(unchanged),
                   "skipped": len(skipped), "warnings": len(warnings)},
    }
    verb = ACTION_LABEL[action]
    n = len(done)
    result["summary"] = (f"{n} Rezept{'e' if n != 1 else ''} {'werden' if not result['executed'] else ''} {verb}"
                         .replace("  ", " ").strip()
                         + (f", {len(skipped)} übersprungen" if skipped else "")
                         + (f", {len(unchanged)} unverändert" if unchanged else "") + ".")
    if needs_confirm:
        raise ConflictError("Bitte die Sammelaktion bestätigen.", code="confirmation_required", result=result)
    return result
