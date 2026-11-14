"""Schutz der ändernden Aufrufe (``/api/v1/admin/...``)."""

from __future__ import annotations

from fastapi import Header, Request

from ..errors import NotAuthenticatedError

SESSION_HEADER = "X-Rezeptbuch-Session"


def require_admin(request: Request, x_rezeptbuch_session: str | None = Header(default=None)) -> None:
    """Zentrale Prüfung: ohne gültige Admin-Sitzung Fehler 401.

    Die Sitzung steht im Kopf ``X-Rezeptbuch-Session``. Jede gültige Anfrage verlängert sie.
    """
    sessions = getattr(request.app.state, "sessions", None)
    if sessions is None:
        raise NotAuthenticatedError("Nicht angemeldet oder Sitzung abgelaufen.", code="not_logged_in")
    sessions.require(x_rezeptbuch_session)
