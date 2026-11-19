"""Gemeinsame Hilfen des Wiegeablaufs (Modul 09): Zeit, Stationen, Prüfungen."""

from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timezone

from ..errors import ConflictError, NotFoundError, ValidationError

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_today() -> str:
    """Heutiges Datum in Ortszeit (TZ des Add-ons, logsetup.setup_timezone)."""
    return date.today().isoformat()


def check_date(value, field: str = "planned_date") -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _DATE.match(value):
        raise ValidationError("Bitte ein Datum im Format JJJJ-MM-TT angeben.", field=field, code="date_invalid")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("Bitte ein gültiges Datum angeben.", field=field, code="date_invalid") from exc
    return value


def whole(value, field: str, label: str, minimum: int = 1, required: bool = True) -> int | None:
    """Ganze Zahl aus JSON (int oder Ziffern-Text)."""
    if value is None or value == "":
        if required:
            raise ValidationError(f"Bitte {label} angeben.", field=field, code="missing")
        return None
    if isinstance(value, bool):
        raise ValidationError(f"{label}: bitte eine ganze Zahl angeben.", field=field, code="not_whole")
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or value < minimum:
        raise ValidationError(f"{label}: bitte eine ganze Zahl ab {minimum} angeben.", field=field, code="not_whole")
    return value


def station_row(conn: sqlite3.Connection, station) -> sqlite3.Row:
    """Station muss es geben und eingerichtet (aktiv) sein (M08-9)."""
    number = whole(station, "station", "die Station")
    row = conn.execute("SELECT id, name, active FROM station WHERE id = ?", (number,)).fetchone()
    if row is None:
        raise NotFoundError(f"Station {number} gibt es nicht.", field="station", code="unknown_station")
    if not row["active"]:
        raise ConflictError(f"{row['name']} ist nicht eingerichtet.", field="station", code="not_configured")
    return row


def station_busy(conn: sqlite3.Connection, station: int) -> sqlite3.Row | None:
    """Charge, die die Station belegt: laufend, mit Handwaage reserviert (K09-11) oder fertig, aber der
    Behälter steht noch auf der Waage (K09-10)."""
    return conn.execute(
        "SELECT b.id, b.batch_no, b.status, b.pause_reason FROM batch b "
        "WHERE b.owner_station_id = ? AND (b.status = 'running' "
        "  OR (b.status = 'paused' AND b.pause_reason = 'hand_scale') "
        "  OR (b.status = 'done' AND b.finish_ack_at IS NULL)) "
        "ORDER BY b.id LIMIT 1", (station,)).fetchone()


def require_confirm(payload: dict, text: str, code: str = "confirm_required") -> None:
    if not isinstance(payload, dict) or payload.get("confirm") is not True:
        raise ConflictError(text, field="confirm", code=code)
