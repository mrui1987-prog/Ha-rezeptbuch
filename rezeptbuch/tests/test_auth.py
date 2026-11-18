"""Tests: PIN-Hash, Probebetrieb, Sitzungen und Sperre – Modul 03."""

import pytest

from app import settings
from app.auth import AdminSessions, DEFAULT_PIN, ensure_default_pin, hash_pin, is_default_pin, verify_hash, verify_pin
from app.auth import pin as pin_module
from app.errors import LockedError, NotAuthenticatedError


@pytest.fixture(autouse=True)
def fast_hash(monkeypatch):
    """Wenige Durchläufe, damit die Tests schnell sind (Format und Logik bleiben gleich)."""
    monkeypatch.setattr(pin_module, "ITERATIONS", 1000)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# -- Hash ------------------------------------------------------------------------

def test_hash_has_no_plaintext_and_is_salted():
    first, second = hash_pin("1234"), hash_pin("1234")
    assert "1234" not in first.split("$", 2)[2]
    assert first != second
    assert first.startswith("pbkdf2_sha256$")


def test_verify_hash():
    stored = hash_pin("4711")
    assert verify_hash("4711", stored)
    assert not verify_hash("4712", stored)
    assert not verify_hash("", stored)


@pytest.mark.parametrize("broken", ["", "abc", "md5$1$aa$bb", "pbkdf2_sha256$x$zz$yy", "pbkdf2_sha256$1$aa"])
def test_verify_hash_rejects_broken_values(broken):
    assert verify_hash("1234", broken) is False


# -- Probebetrieb ------------------------------------------------------------------

def test_default_pin_created_on_first_start(conn):
    assert is_default_pin(conn) is False
    assert ensure_default_pin(conn) is True
    assert is_default_pin(conn) is True
    assert verify_pin(conn, DEFAULT_PIN) is True
    assert verify_pin(conn, "0000") is False


def test_no_plaintext_pin_in_database(conn):
    ensure_default_pin(conn)
    values = [r["value"] for r in conn.execute("SELECT value FROM setting WHERE key = 'pin_hash'")]
    assert values and all(v != "1234" and v.startswith("pbkdf2_sha256$") for v in values)


def test_default_pin_is_not_created_twice_or_overwritten(conn):
    ensure_default_pin(conn)
    conn.execute("UPDATE setting SET value = ? WHERE key = 'pin_hash'", (hash_pin("9999"),))
    conn.execute("UPDATE setting SET value = '0' WHERE key = 'pin_is_default'")
    assert ensure_default_pin(conn) is False
    assert verify_pin(conn, "9999") and not verify_pin(conn, "1234")
    assert is_default_pin(conn) is False


def test_verify_without_stored_hash_fails(conn):
    assert verify_pin(conn, "1234") is False


# -- Sitzungen und Sperre ------------------------------------------------------------

def make_sessions(**kw):
    clock = Clock()
    return AdminSessions(timeout_minutes=5, clock=clock, **kw), clock


def ok(pin):
    return pin == "1234"


def test_login_with_correct_pin_gives_session():
    sessions, _ = make_sessions()
    token = sessions.login("1234", ok)
    assert sessions.validate(token) is True
    assert sessions.validate("anderes-zeichen") is False
    assert sessions.validate(None) is False


def test_wrong_pin_counts_down():
    sessions, _ = make_sessions()
    with pytest.raises(NotAuthenticatedError) as exc:
        sessions.login("0000", ok)
    assert exc.value.status_code == 401
    assert exc.value.extra["attempts_left"] == 4


def test_lock_after_five_failures_for_five_minutes():
    sessions, clock = make_sessions()
    for _ in range(4):
        with pytest.raises(NotAuthenticatedError):
            sessions.login("0000", ok)
    with pytest.raises(LockedError) as exc:
        sessions.login("0000", ok)
    assert exc.value.status_code == 423
    assert exc.value.extra["retry_after_seconds"] == 300

    # während der Sperre wird auch die richtige PIN abgelehnt
    clock.advance(120)
    with pytest.raises(LockedError) as exc:
        sessions.login("1234", ok)
    assert exc.value.extra["retry_after_seconds"] == 180

    # nach Ablauf geht es wieder, die Zählung beginnt neu
    clock.advance(181)
    assert sessions.validate(sessions.login("1234", ok))


def test_counter_restarts_after_lock_expired():
    sessions, clock = make_sessions()
    for _ in range(4):
        with pytest.raises(NotAuthenticatedError):
            sessions.login("0000", ok)
    with pytest.raises(LockedError):
        sessions.login("0000", ok)
    clock.advance(301)
    with pytest.raises(NotAuthenticatedError) as exc:
        sessions.login("0000", ok)
    assert exc.value.extra["attempts_left"] == 4


def test_success_resets_failures():
    sessions, _ = make_sessions()
    for _ in range(3):
        with pytest.raises(NotAuthenticatedError):
            sessions.login("0000", ok)
    sessions.login("1234", ok)
    with pytest.raises(NotAuthenticatedError) as exc:
        sessions.login("0000", ok)
    assert exc.value.extra["attempts_left"] == 4


def test_session_expires_and_is_extended_by_use():
    sessions, clock = make_sessions()
    token = sessions.login("1234", ok)
    clock.advance(200)
    assert sessions.validate(token) is True       # verlängert um 5 Minuten ab jetzt
    clock.advance(200)
    assert sessions.validate(token) is True
    clock.advance(301)
    assert sessions.validate(token) is False      # abgelaufen
    with pytest.raises(NotAuthenticatedError, match="abgelaufen"):
        sessions.require(token)


def test_is_valid_does_not_extend_session():
    # Sitzungsprüfung beim Öffnen/Reiterwechsel (Modul 06 Teil C2, docs/berechnung.md 17.14)
    sessions, clock = make_sessions()
    token = sessions.login("1234", ok)
    clock.advance(200)
    assert sessions.is_valid(token) is True       # prüft nur, verlängert nicht
    clock.advance(101)
    assert sessions.is_valid(token) is False      # 301 s nach der Anmeldung abgelaufen
    assert sessions.is_valid(None) is False and sessions.is_valid("falsch") is False


def test_logout_ends_session():
    sessions, _ = make_sessions()
    token = sessions.login("1234", ok)
    sessions.logout(token)
    assert sessions.validate(token) is False
    sessions.logout(token)       # nochmaliges Abmelden ist harmlos
    sessions.logout(None)


def test_sessions_are_independent():
    sessions, _ = make_sessions()
    first, second = sessions.login("1234", ok), sessions.login("1234", ok)
    assert first != second
    sessions.logout(first)
    assert sessions.validate(second) is True


# -- Einstellungen -------------------------------------------------------------------

def test_admin_timeout_default_and_option(tmp_path):
    assert settings.admin_timeout_minutes({}) == 5
    assert settings.admin_timeout_minutes({"admin_timeout_minutes": 12}) == 12
    for bad in (0, 61, -3, "10", True, None, 2.5):
        assert settings.admin_timeout_minutes({"admin_timeout_minutes": bad}) == 5


def test_load_options(tmp_path, monkeypatch):
    path = tmp_path / "options.json"
    assert settings.load_options(path) == {}                   # Datei fehlt
    path.write_text('{"admin_timeout_minutes": 9}', encoding="utf-8")
    assert settings.admin_timeout_minutes(settings.load_options(path)) == 9
    path.write_text("kein json", encoding="utf-8")
    assert settings.load_options(path) == {}
    path.write_text("[1, 2]", encoding="utf-8")
    assert settings.load_options(path) == {}
    monkeypatch.setenv("REZEPTBUCH_OPTIONS", str(path))
    assert settings.options_path() == path
