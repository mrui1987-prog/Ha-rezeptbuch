import json
from pathlib import Path

import pytest
import yaml

from app.config import load_options, parse_options, parse_station

ADDON = Path(__file__).resolve().parents[1]


def addon_defaults():
    return yaml.safe_load((ADDON / "config.yaml").read_text(encoding="utf-8"))


def test_defaults_match_concept():
    opts = addon_defaults()["options"]
    assert opts["scale1_enabled"] is True and opts["scale2_enabled"] is False
    assert opts["scale1_connection"] == "tcp"          # M07-1: TCP Standard
    assert opts["scale1_port"] == 8899                 # K07-9
    assert opts["scale1_raw_topic"] == "rezeptbuch/test/waage1/raw"
    assert opts["scale2_cmd_topic"] == "rezeptbuch/test/waage2/cmd"
    assert opts["scale1_mode"] == "CONT"               # Test 20:50
    assert opts["scale1_baud"] == 9600 and opts["scale1_format"] == "8n1"
    assert opts["scale1_stable_window_ms"] == 1000 and opts["scale1_stable_span_g"] == 2
    assert opts["scale1_offline_after_s"] == 5
    assert opts["scale1_capacity_g"] == 30000 and opts["scale1_resolution_g"] == 1


def test_no_ip_address_in_repo_defaults():
    opts = addon_defaults()["options"]
    assert "scale1_host" not in opts and "scale2_host" not in opts


def test_every_field_has_german_name_with_default():
    cfg = addon_defaults()
    tr = yaml.safe_load((ADDON / "translations" / "de.yaml").read_text(encoding="utf-8"))
    names = tr["configuration"]
    assert set(names) == set(cfg["schema"])
    for key, entry in names.items():
        assert "(Standard" in entry["name"], key
        assert entry["description"], key


def test_version_070():
    from app import __version__
    assert addon_defaults()["version"] == "0.7.3" == __version__


def test_parse_defaults_station1_needs_host():
    cfg = parse_options(addon_defaults()["options"])
    s1, s2 = cfg.stations
    assert s1.enabled and not s2.enabled
    assert s1.uses_tcp and s1.port == 8899
    assert not s1.ok and "host" in s1.errors[0]
    assert [s.station for s in cfg.active] == [1]


def test_parse_tcp_ok():
    opts = addon_defaults()["options"] | {"scale1_host": " 10.0.0.5 "}
    s1 = parse_options(opts).stations[0]
    assert s1.ok and s1.host == "10.0.0.5"


def test_parse_mqtt_needs_topics():
    opts = addon_defaults()["options"] | {"scale1_connection": "mqtt"}
    s1 = parse_options(opts).stations[0]
    assert s1.ok and s1.uses_mqtt
    opts["scale1_raw_topic"] = ""
    s1 = parse_options(opts).stations[0]
    assert not s1.ok and "raw_topic" in s1.errors[0]


def test_simulator_needs_no_host():
    s1 = parse_station(1, {"scale1_enabled": True, "scale1_driver": "simulator"})
    assert s1.ok and not s1.uses_tcp and not s1.uses_mqtt


def test_disabled_station_needs_nothing():
    assert parse_station(2, {}).ok


@pytest.mark.parametrize("key,value", [
    ("stable_window_ms", 100), ("stable_window_ms", 6000), ("stable_span_g", -1),
    ("offline_after_s", 1), ("offline_after_s", 31), ("port", 0), ("port", True),
    ("driver", "mettler"), ("connection", "serial"), ("mode", "ASK"), ("format", "8E1"),
])
def test_out_of_range_rejected(key, value):
    s = parse_station(1, {"scale1_enabled": True, "scale1_driver": "simulator",
                          f"scale1_{key}": value})
    assert not s.ok and any(key in e for e in s.errors)


def test_numbers_as_text_accepted():
    s = parse_station(1, {"scale1_stable_span_g": "3"})
    assert s.ok and s.stable_span_g == 3


def test_log_level():
    assert parse_options({"log_level": "debug"}).log_level == "debug"
    assert parse_options({"log_level": "laut"}).log_level == "info"


def test_load_missing_file(tmp_path):
    cfg = load_options(tmp_path / "fehlt.json")
    assert cfg.active == ()


def test_load_file(tmp_path):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({"scale2_enabled": True, "scale2_driver": "simulator"}))
    cfg = load_options(path)
    assert [s.station for s in cfg.active] == [2]
