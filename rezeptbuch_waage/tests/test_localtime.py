"""Ortszeit im Protokoll (Befund O1, 0.7.5)."""

from app.localtime import DEFAULT_TZ, read_tz, setup_timezone


def test_tz_from_environment_wins(tmp_path):
    f = tmp_path / "TZ"
    f.write_text("America/New_York\n")
    env = {"TZ": "Europe/Vienna"}
    assert setup_timezone(env, files=(str(f),), tzset=lambda: None) == "Europe/Vienna"


def test_tz_from_s6_file_when_env_missing(tmp_path):
    f = tmp_path / "TZ"
    f.write_text("Europe/Berlin\n")
    env: dict = {}
    calls = []
    tz = setup_timezone(env, files=(str(tmp_path / "fehlt"), str(f)),
                        tzset=lambda: calls.append(1))
    assert tz == "Europe/Berlin" and env["TZ"] == "Europe/Berlin" and calls == [1]


def test_default_when_nothing_found(tmp_path):
    env = {"TZ": "  "}
    assert setup_timezone(env, files=(str(tmp_path / "fehlt"),),
                          tzset=lambda: None) == DEFAULT_TZ == "Europe/Berlin"
    assert env["TZ"] == "Europe/Berlin"


def test_empty_file_ignored(tmp_path):
    f = tmp_path / "TZ"
    f.write_text("")
    assert read_tz({}, files=(str(f),)) is None


def test_real_tzset_gives_local_offset(tmp_path):
    import os
    import time
    old = os.environ.get("TZ")
    try:
        os.environ.pop("TZ", None)
        setup_timezone(files=(str(tmp_path / "fehlt"),))
        # 19.11.2026, 05:24 UTC → 06:24 Ortszeit (MEZ)
        assert time.strftime("%H:%M", time.localtime(1795065840)) == "06:24"
    finally:
        if old is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old
        time.tzset()
