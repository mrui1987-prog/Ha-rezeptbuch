"""Fehler der Fachschicht mit HTTP-Statuscode und deutscher Meldung (Modul 03).

Die Fachschichten (``raw_materials``, ``auth``) kennen kein FastAPI. Sie lösen
diese Fehler aus; der Webserver wandelt sie in eine JSON-Antwort um
(``main.py``, Handler für ``ServiceError``).
"""

from __future__ import annotations


class ServiceError(Exception):
    """Grundklasse: Meldung, HTTP-Statuscode, optional Feld und Code für die Oberfläche."""

    status_code = 400

    def __init__(self, message: str, *, field: str | None = None, code: str | None = None, **extra):
        super().__init__(message)
        self.message = message
        self.field = field
        self.code = code
        self.extra = extra

    def to_dict(self) -> dict:
        body: dict = {"detail": self.message}
        if self.field:
            body["field"] = self.field
        if self.code:
            body["code"] = self.code
        body.update(self.extra)
        return body


class ValidationError(ServiceError):
    """400 – Eingabe ungültig."""

    status_code = 400


class NotAuthenticatedError(ServiceError):
    """401 – nicht angemeldet, Sitzung abgelaufen oder PIN falsch."""

    status_code = 401


class NotFoundError(ServiceError):
    """404 – Eintrag nicht gefunden."""

    status_code = 404


class ConflictError(ServiceError):
    """409 – Konflikt mit vorhandenen Daten (Name doppelt, Nummer gesperrt, verwendet …)."""

    status_code = 409


class PayloadTooLargeError(ServiceError):
    """413 – hochgeladene Datei zu groß (Import, Modul 05)."""

    status_code = 413


class LockedError(ServiceError):
    """423 – PIN-Eingabe vorübergehend gesperrt."""

    status_code = 423


class DatabaseNotReadyError(ServiceError):
    """503 – Datenbank nicht betriebsbereit."""

    status_code = 503
