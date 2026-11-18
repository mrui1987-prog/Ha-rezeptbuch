import json
import logging
from datetime import datetime, timedelta, timezone

from app.config import StationConfig
from app.kern import format_line
from app.station import StationMonitor

T0 = datetime(2026, 11, 18, 20, 0, tzinfo=timezone.utc)


def wall(t):
    return T0 + timedelta(seconds=t)


def make(**kw):
    return StationMonitor(StationConfig(station=1, enabled=True, host="x", **kw))


def line(mon, t, text):
    mon.feed((text + "\r\n").encode(), t, wall(t))


def weights(mon, start, end, grams, step=0.1, stable=True):
    t = start
    while t < end - 1e-9:
        line(mon, round(t, 3), format_line(grams, stable))
        t += step


def pub(mon, t):
    payload = mon.poll(t, wall(t))
    return None if payload is None else json.loads(payload)


def test_start_offline():
    mon = make()
    data = pub(mon, 0.0)
    assert data["status"] == "offline"
    assert data["weight_g"] is None and data["stable"] is False
    assert data["capacity_g"] == 30000 and data["resolution_g"] == 1


def test_ok_then_stable_after_window():
    mon = make()
    weights(mon, 0.0, 0.5, 77)
    data = pub(mon, 0.4)
    assert data["status"] == "ok" and data["weight_g"] == 77
    assert data["stable"] is False and data["scale_stable"] is True and data["net"] is False
    weights(mon, 0.5, 1.1, 77)
    data = pub(mon, 1.0)
    assert data["stable"] is True


def test_last_value_reported_not_mean():
    mon = make()
    weights(mon, 0.0, 0.3, 100)
    line(mon, 0.3, format_line(101, stable=False))
    data = pub(mon, 0.3)
    assert data["weight_g"] == 101 and data["scale_stable"] is False


def test_ts_is_time_of_line():
    mon = make()
    line(mon, 0.2, format_line(5))
    assert pub(mon, 0.35)["ts"] == "2026-11-18T20:00:00.200+00:00"


def test_dashes_invalid_not_offline_and_resets_stability():
    mon = make()
    weights(mon, 0.0, 2.0, 500)
    assert pub(mon, 1.9)["stable"] is True
    line(mon, 2.0, "-----")
    data = pub(mon, 2.0)
    assert data["status"] == "invalid" and data["weight_g"] is None and data["stable"] is False
    # Dauerhaft ----- bleibt invalid, nie offline (Lebenszeichen)
    for i in range(1, 80):
        line(mon, 2.0 + i * 0.1, "-----")
    assert mon.status(9.9) == "invalid"
    weights(mon, 10.0, 10.5, 500)
    data = pub(mon, 10.4)
    assert data["status"] == "ok" and data["stable"] is False


def test_offline_after_5s_without_lines():
    mon = make()
    weights(mon, 0.0, 1.0, 300)
    assert mon.status(5.8) == "ok"
    assert mon.status(5.9) == "offline"     # letzte Zeile bei 0.9
    data = pub(mon, 6.0)
    assert data["status"] == "offline" and data["ts"] == "2026-11-18T20:00:06.000+00:00"


def test_offline_after_configurable():
    mon = make(offline_after_s=2)
    line(mon, 0.0, format_line(1))
    assert mon.status(1.9) == "ok"
    assert mon.status(2.0) == "offline"


def test_after_offline_old_values_forgotten():
    mon = make()
    weights(mon, 0.0, 2.0, 300)
    assert mon.status(10.0) == "offline"
    line(mon, 10.0, format_line(300))
    data = pub(mon, 10.0)
    assert data["status"] == "ok" and data["stable"] is False


def test_unreadable_error_after_3s_with_hint(caplog):
    mon = make()
    pub(mon, 0.0)
    weights(mon, 0.0, 1.0, 50)
    pub(mon, 0.9)
    t = 1.0
    while t < 4.05:
        line(mon, round(t, 2), "\x13\x7f@@x")
        t += 0.1
    assert mon.status(3.9) == "ok"            # unter 3 s: letzter Zustand bleibt
    with caplog.at_level(logging.WARNING, logger="rezeptbuch_waage"):
        data = pub(mon, 4.0)
    assert data["status"] == "error" and data["weight_g"] is None
    assert "Baudrate 9600 und Format 8n1" in caplog.text
    # unlesbar zählt als Lebenszeichen: nicht offline
    assert mon.status(8.5) == "error"
    line(mon, 8.6, format_line(50))
    assert mon.status(8.6) == "ok"


def test_only_unreadable_from_start():
    mon = make()
    line(mon, 0.0, "Müll")
    assert mon.status(1.0) == "offline"
    line(mon, 3.0, "Müll")
    assert mon.status(3.0) == "error"


def test_net_reported_and_resets_stability():
    mon = make()
    weights(mon, 0.0, 2.0, 1200)
    assert pub(mon, 1.9)["stable"] is True
    line(mon, 2.0, format_line(0, net=True))
    data = pub(mon, 2.0)
    assert data["net"] is True and data["weight_g"] == 0 and data["stable"] is False


def test_publish_on_change_else_every_500ms():
    mon = make()
    assert pub(mon, 0.0) is not None           # erste Meldung
    assert pub(mon, 0.1) is None
    assert pub(mon, 0.5) is not None           # Wiederholung nach 500 ms
    line(mon, 0.6, format_line(10, stable=False))
    assert pub(mon, 0.6) is not None           # Änderung sofort
    line(mon, 0.7, format_line(10, stable=False))
    assert pub(mon, 0.7) is None               # gleich → warten
    line(mon, 0.8, format_line(11, stable=False))
    assert pub(mon, 0.8)["weight_g"] == 11     # Gewicht geändert → sofort
    line(mon, 0.9, format_line(11, stable=True))
    assert pub(mon, 0.9)["scale_stable"] is True   # Merker geändert → sofort


def test_stable_change_published_immediately():
    mon = make()
    weights(mon, 0.0, 1.0, 20)
    assert pub(mon, 0.9)["stable"] is False
    line(mon, 1.0, format_line(20))
    data = pub(mon, 1.0)
    assert data is not None and data["stable"] is True


def test_rate_at_most_one_per_line_when_changing():
    mon = make()
    count = 0
    for i in range(100):                       # 10 s, jede Zeile anders
        t = i * 0.1
        line(mon, t, format_line(i, stable=False))
        if pub(mon, t) is not None:
            count += 1
    assert count == 100


def test_config_error_station_reports_error():
    cfg = StationConfig(station=2, enabled=True, errors=("scale2_host: fehlt",))
    mon = StationMonitor(cfg)
    data = json.loads(mon.poll(0.0, wall(0)))
    assert data["status"] == "error" and data["station"] == 2


def test_offline_hint_when_tcp_connected(caplog):
    mon = make()
    mon.connected = True
    pub(mon, 0.0)
    line(mon, 0.0, format_line(1))
    pub(mon, 0.0)
    with caplog.at_level(logging.WARNING, logger="rezeptbuch_waage"):
        pub(mon, 5.0)
    assert "Sendemodus CONT" in caplog.text


def test_connection_lost_drops_half_line():
    mon = make()
    mon.feed(b"ST,G    0.0", 0.0, wall(0))
    mon.connection_lost()
    mon.feed(b"-----\r\n", 0.1, wall(0.1))
    assert mon.status(0.1) == "invalid"


def test_custom_capacity_in_payload():
    mon = StationMonitor(StationConfig(station=2, enabled=True, host="x",
                                       capacity_g=15000, resolution_g=5))
    data = pub(mon, 0.0)
    assert data["station"] == 2 and data["capacity_g"] == 15000 and data["resolution_g"] == 5
