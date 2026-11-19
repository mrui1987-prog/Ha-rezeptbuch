"""Befund B1 (0.8.1): Protokollstufe aus log_level, Ortszeit."""

import io
import logging

from app.logsetup import LOGGER_NAMES, log_level, read_tz, setup_logging, setup_timezone


def _cleanup():
    for name in LOGGER_NAMES:
        logger = logging.getLogger(name)
        for h in list(logger.handlers):
            if getattr(h, "_rezeptbuch_handler", False):
                logger.removeHandler(h)
        logger.setLevel(logging.NOTSET)


def test_log_level_from_options():
    assert log_level({"log_level": "debug"}) == "debug"
    assert log_level({"log_level": "laut"}) == "info"
    assert log_level({}) == "info"
    assert log_level(None) == "info"


def test_info_lines_appear_with_time():
    out = io.StringIO()
    try:
        assert setup_logging({"log_level": "info"}, stream=out) == "info"
        logging.getLogger("rezeptbuch.scales").info("MQTT verbunden, Waagen-Topics abonniert")
        logging.getLogger("app.settings").debug("unsichtbar")
        text = out.getvalue()
        assert "INFO MQTT verbunden, Waagen-Topics abonniert" in text
        assert "unsichtbar" not in text
        assert text[:4].isdigit()                     # beginnt mit Datum/Uhrzeit
    finally:
        _cleanup()


def test_warning_level_hides_info_and_no_double_handler():
    out = io.StringIO()
    try:
        setup_logging({"log_level": "warning"}, stream=out)
        setup_logging({"log_level": "warning"}, stream=out)     # zweiter Start (Tests, Neustart)
        log = logging.getLogger("rezeptbuch")
        log.info("leise")
        log.warning("laut")
        assert out.getvalue().count("laut") == 1 and "leise" not in out.getvalue()
        assert sum(getattr(h, "_rezeptbuch_handler", False) for h in log.handlers) == 1
    finally:
        _cleanup()


def test_timezone(tmp_path):
    env = {}
    assert setup_timezone(env, files=(), tzset=lambda: None) == "Europe/Berlin" and env["TZ"] == "Europe/Berlin"
    f = tmp_path / "TZ"
    f.write_text("Europe/Vienna\n")
    assert read_tz({}, files=(str(f),)) == "Europe/Vienna"
    assert read_tz({"TZ": "UTC"}, files=(str(f),)) == "UTC"
