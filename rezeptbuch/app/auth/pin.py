"""PIN-Speicherung und -Prüfung (Modul 03, docs/rohstoffe.md Abschnitt 5).

* Gespeichert wird nur ein Hash (PBKDF2-SHA256 mit zufälligem Salz), nie die PIN.
* Probebetrieb: Fehlt beim Start ein Hash, wird der Hash von ``1234`` angelegt und
  ``pin_is_default = 1`` gesetzt. Solange das gilt, zeigt die Oberfläche
  „Probebetrieb – PIN 1234“. PIN ändern und Probebetrieb beenden folgt in Modul 12.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import sqlite3

from ..db import transaction

logger = logging.getLogger(__name__)

# Probebetrieb-PIN (Werkseinstellung, bewusst öffentlich dokumentiert, M03-7)
DEFAULT_PIN = "1234"

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000

KEY_HASH = "pin_hash"
KEY_IS_DEFAULT = "pin_is_default"


def hash_pin(pin: str, *, salt: bytes | None = None, iterations: int | None = None) -> str:
    """Erzeugt den Hash im Format ``pbkdf2_sha256$Durchläufe$Salz$Hash`` (Salz und Hash hexadezimal)."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    iterations = iterations if iterations is not None else ITERATIONS
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_hash(pin: str, stored: str) -> bool:
    """Prüft eine PIN gegen den gespeicherten Hash (zeitkonstanter Vergleich)."""
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def ensure_default_pin(conn: sqlite3.Connection) -> bool:
    """Legt beim ersten Start den Probebetrieb an. Gibt True zurück, wenn dabei etwas angelegt wurde."""
    with transaction(conn):
        if _get(conn, KEY_HASH) is not None:
            return False
        conn.execute("INSERT INTO setting (key, value) VALUES (?, ?)", (KEY_HASH, hash_pin(DEFAULT_PIN)))
        conn.execute(
            "INSERT INTO setting (key, value) VALUES (?, '1') "
            "ON CONFLICT (key) DO UPDATE SET value = '1', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
            (KEY_IS_DEFAULT,),
        )
    logger.warning("Probebetrieb: Es gilt die Werks-PIN %s. Vor dem Echtbetrieb ändern (Modul 12).", DEFAULT_PIN)
    return True


def is_default_pin(conn: sqlite3.Connection) -> bool:
    """True, solange der Probebetrieb mit der Werks-PIN läuft."""
    return _get(conn, KEY_IS_DEFAULT) == "1"


def verify_pin(conn: sqlite3.Connection, pin: str) -> bool:
    """Prüft die eingegebene PIN gegen den in der Datenbank gespeicherten Hash."""
    stored = _get(conn, KEY_HASH)
    if stored is None:
        return False
    return verify_hash(pin, stored)
