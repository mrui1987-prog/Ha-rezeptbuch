"""Admin-Sitzungen mit Sperre nach Fehlversuchen (Modul 03, docs/rohstoffe.md Abschnitt 5).

* Eine erfolgreiche Anmeldung liefert ein zufälliges Sitzungszeichen. Die Sitzungen
  liegen nur im Arbeitsspeicher; nach einem Neustart des Add-ons ist neu anzumelden.
* Jede geprüfte Anfrage verlängert die Sitzung um die eingestellte Dauer
  (Add-on-Option ``admin_timeout_minutes``, K03-2).
* Nach 5 Fehlversuchen ist die PIN-Eingabe 5 Minuten gesperrt. Da es keine
  Benutzer gibt, gilt die Sperre für alle Geräte.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from typing import Callable

from ..errors import LockedError, NotAuthenticatedError

MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 5


class AdminSessions:
    def __init__(
        self,
        timeout_minutes: int = 5,
        *,
        max_attempts: int = MAX_ATTEMPTS,
        lockout_minutes: int = LOCKOUT_MINUTES,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.timeout_seconds = timeout_minutes * 60
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_minutes * 60
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}   # Sitzungszeichen -> Ablaufzeit
        self._failures = 0
        self._locked_until: float | None = None

    # -- Anmeldung -------------------------------------------------------------

    def login(self, pin: str, verify: Callable[[str], bool]) -> str:
        """Prüft die PIN mit ``verify`` und gibt bei Erfolg ein Sitzungszeichen zurück.

        Der Aufruf läuft unter einer Sperre, damit gleichzeitige Versuche die
        Zählung der Fehlversuche nicht umgehen können.
        """
        with self._lock:
            now = self._clock()
            if self._locked_until is not None:
                if now < self._locked_until:
                    raise self._locked_error(self._locked_until - now)
                self._locked_until = None
                self._failures = 0

            if verify(pin):
                self._failures = 0
                self._purge(now)
                token = secrets.token_urlsafe(32)
                self._sessions[token] = now + self.timeout_seconds
                return token

            self._failures += 1
            if self._failures >= self.max_attempts:
                self._locked_until = now + self.lockout_seconds
                self._failures = 0
                raise self._locked_error(self.lockout_seconds)
            left = self.max_attempts - self._failures
            raise NotAuthenticatedError(
                f"PIN falsch. Noch {left} Versuch{'e' if left != 1 else ''} bis zur Sperre.",
                code="pin_wrong",
                attempts_left=left,
            )

    def _locked_error(self, seconds: float) -> LockedError:
        seconds = max(1, math.ceil(seconds))
        minutes = math.ceil(seconds / 60)
        return LockedError(
            f"PIN-Eingabe gesperrt. Bitte in {minutes} Minute{'n' if minutes != 1 else ''} erneut versuchen.",
            code="pin_locked",
            retry_after_seconds=seconds,
        )

    # -- Sitzung ---------------------------------------------------------------

    def validate(self, token: str | None) -> bool:
        """True, wenn die Sitzung gültig ist. Eine gültige Sitzung wird verlängert."""
        if not token:
            return False
        with self._lock:
            now = self._clock()
            expires = self._sessions.get(token)
            if expires is None:
                return False
            if now >= expires:
                del self._sessions[token]
                return False
            self._sessions[token] = now + self.timeout_seconds
            return True

    def require(self, token: str | None) -> None:
        """Wie ``validate``, löst bei ungültiger Sitzung aber den Fehler 401 aus."""
        if not self.validate(token):
            raise NotAuthenticatedError("Nicht angemeldet oder Sitzung abgelaufen.", code="not_logged_in")

    def logout(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._sessions.pop(token, None)

    def _purge(self, now: float) -> None:
        for token in [t for t, expires in self._sessions.items() if now >= expires]:
            del self._sessions[token]
