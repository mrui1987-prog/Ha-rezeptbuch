"""Anmeldung am Admin-Bereich und Systeminformationen (Modul 03, docs/rohstoffe.md Abschnitt 6)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends, Header, Request

from .. import __version__
from ..deps import get_db
from ..errors import ValidationError
from .pin import is_default_pin, verify_pin

router = APIRouter(prefix="/api/v1", tags=["admin"])


@router.get("/system/info")
def system_info(request: Request, db: sqlite3.Connection = Depends(get_db)):
    """Version und Probebetrieb-Kennzeichen (für den Balken „Probebetrieb – PIN 1234“)."""
    sessions = getattr(request.app.state, "sessions", None)
    return {
        "version": __version__,
        "pin_is_default": is_default_pin(db),
        "admin_timeout_minutes": round(sessions.timeout_seconds / 60) if sessions else None,
    }


@router.post("/admin/login")
def login(request: Request, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    pin = payload.get("pin")
    if not isinstance(pin, str) or not pin.strip() or len(pin) > 64:
        raise ValidationError("Bitte die PIN eingeben.", field="pin")
    sessions = request.app.state.sessions
    token = sessions.login(pin, lambda candidate: verify_pin(db, candidate))
    return {
        "session": token,
        "expires_in_seconds": sessions.timeout_seconds,
        "pin_is_default": is_default_pin(db),
    }


@router.post("/admin/logout")
def logout(request: Request, x_rezeptbuch_session: str | None = Header(default=None)):
    sessions = getattr(request.app.state, "sessions", None)
    if sessions is not None:
        sessions.logout(x_rezeptbuch_session)
    return {"status": "ok"}
