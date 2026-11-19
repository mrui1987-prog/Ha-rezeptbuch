"""Modul 08: Supervisor-Zugang, MQTT-Verbindung (nachgebildet) und Dienst (M08-2, M08-10, K08-1)."""

import asyncio
import io
import json

import pytest

from app.db import init_database
from app.scales import hub as h
from app.scales.mqtt_link import MqttLink
from app.scales.service import ScaleService, load_stations
from app.scales.supervisor import CredentialsError, fetch_credentials, read_supervisor_token

# ------------------------------------------------------------ Supervisor


def test_token_from_env_and_file(tmp_path):
    assert read_supervisor_token({"SUPERVISOR_TOKEN": "abc"}, files=()) == "abc"
    f = tmp_path / "tok"
    f.write_text("xyz\n")
    assert read_supervisor_token({}, files=(str(tmp_path / "fehlt"), str(f))) == "xyz"
    assert read_supervisor_token({}, files=()) is None


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_credentials():
    body = {"data": {"host": "core-mosquitto", "port": 1883, "username": "u", "password": "p", "ssl": False}}
    seen = {}

    def opener(req, timeout):
        seen["auth"] = req.headers.get("Authorization")
        return Resp(json.dumps(body).encode())

    creds = fetch_credentials(token="t", opener=opener)
    assert creds == {"host": "core-mosquitto", "port": 1883, "username": "u", "password": "p", "ssl": False}
    assert seen["auth"] == "Bearer t"


def test_fetch_credentials_errors():
    with pytest.raises(CredentialsError, match="SUPERVISOR_TOKEN"):
        fetch_credentials(token="")
    with pytest.raises(CredentialsError, match="Mosquitto"):
        fetch_credentials(token="t", opener=lambda r, timeout: Resp(b'{"data": {}}'))

    def broken(r, timeout):
        raise OSError("weg")
    with pytest.raises(CredentialsError, match="nicht erreichbar"):
        fetch_credentials(token="t", opener=broken)


# ------------------------------------------------------------ MQTT-Verbindung


class FakeClient:
    def __init__(self):
        self.calls = []

    def username_pw_set(self, u, p):
        self.calls.append(("auth", u, p))

    def tls_set(self):
        self.calls.append(("tls",))

    def reconnect_delay_set(self, **kw):
        pass

    def connect_async(self, host, port, keepalive):
        self.calls.append(("connect", host, port))

    def loop_start(self):
        self.calls.append(("loop_start",))

    def loop_stop(self):
        self.calls.append(("loop_stop",))

    def disconnect(self):
        self.calls.append(("disconnect",))

    def subscribe(self, topic, qos):
        self.calls.append(("sub", topic, qos))

    def publish(self, topic, payload, qos, retain):
        self.calls.append(("pub", topic, payload, qos, retain))


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = topic, payload


def make_link():
    client = FakeClient()
    got, conn = [], []
    link = MqttLink({"host": "h", "port": 1883, "username": "u", "password": "p"},
                    on_message=lambda t, p: got.append((t, p)), on_connection=conn.append,
                    client_factory=lambda: client)
    return link, client, got, conn


def test_link_subscribes_on_connect():
    link, client, got, conn = make_link()
    link.start()
    assert ("auth", "u", "p") in client.calls and ("connect", "h", 1883) in client.calls
    assert link.publish("x", "y") is False                       # noch nicht verbunden
    link._on_connect(client, None, None, 0)
    assert ("sub", "rezeptbuch/v1/station/+/scale/state", 0) in client.calls
    assert ("sub", "rezeptbuch/v1/scale_bridge/availability", 1) in client.calls
    assert conn == [True]


def test_link_publish_qos1_never_retained():
    link, client, got, conn = make_link()
    link.start()
    link._on_connect(client, None, None, 0)
    assert link.publish("rezeptbuch/v1/station/1/scale/cmd", '{"v":2,"cmd":"tare"}') is True
    assert client.calls[-1] == ("pub", "rezeptbuch/v1/station/1/scale/cmd", '{"v":2,"cmd":"tare"}', 1, False)


def test_link_message_and_disconnect():
    link, client, got, conn = make_link()
    link.start()
    link._on_connect(client, None, None, 0)
    link._on_message(client, None, Msg("t", b"p"))
    assert got == [("t", b"p")]
    link._on_disconnect(client, None)
    assert conn == [True, False] and link.publish("x", "y") is False
    link.stop()
    assert ("loop_stop",) in client.calls


def test_link_refused_login():
    link, client, got, conn = make_link()
    link.start()

    class RC:
        is_failure = True
    link._on_connect(client, None, None, RC())
    assert conn == [] and link.connected is False


# ------------------------------------------------------------ Stationen und Dienst


def test_load_stations(tmp_path):
    db = tmp_path / "r.db"
    init_database(db).close()
    assert load_stations(db) == {1: ("Waage 1", True), 2: ("Waage 2", False)}
    assert load_stations(None) == {}


class FakeLink:
    instances = []

    def __init__(self, creds, on_message, on_connection):
        self.creds, self.on_message, self.on_connection = creds, on_message, on_connection
        self.started = self.stopped = False
        self.sent = []
        FakeLink.instances.append(self)

    def start(self):
        self.started = True

    def publish(self, topic, payload):
        self.sent.append((topic, payload))
        return True

    def stop(self):
        self.stopped = True


def test_service_without_mqtt_keeps_running(tmp_path):
    db = tmp_path / "r.db"
    init_database(db).close()
    calls = []

    def fetch():
        calls.append(1)
        raise CredentialsError("MQTT-Dienst nicht gefunden – Mosquitto installiert?")

    async def run():
        svc = ScaleService(db_path=db, fetch=fetch, link_factory=FakeLink, credentials_retry_s=0.01)
        await svc.start()
        await asyncio.sleep(0.05)
        state = svc.hub.current_state(1)
        await svc.stop()
        return svc, state

    svc, state = asyncio.run(run())
    assert len(calls) >= 2                                         # neuer Versuch
    assert svc.hub.mqtt_state == h.MQTT_UNAVAILABLE
    assert state.status == "offline" and state.offline_reason == "broker" and state.configured


def test_service_connects_and_passes_messages(tmp_path):
    db = tmp_path / "r.db"
    init_database(db).close()
    FakeLink.instances = []

    async def run():
        svc = ScaleService(db_path=db, fetch=lambda: {"host": "h", "port": 1883}, link_factory=FakeLink)
        await svc.start()
        await asyncio.sleep(0.05)
        link = FakeLink.instances[-1]
        # aus dem „paho-Thread“
        link.on_connection(True)
        link.on_message("rezeptbuch/v1/scale_bridge/availability", b"online")
        link.on_message("rezeptbuch/v1/station/1/scale/state", json.dumps(
            {"v": 2, "station": 1, "status": "ok", "weight_g": 42, "stable": False,
             "scale_stable": False, "net": False, "capacity_g": 30000, "resolution_g": 1,
             "ts": "2026-11-19T08:00:00.000+00:00"}).encode())
        await asyncio.sleep(0.05)
        state = svc.hub.current_state(1)
        result = svc.hub.send_command(1, "zero")
        await svc.stop()
        return link, state, result

    link, state, result = asyncio.run(run())
    assert link.started and link.stopped
    assert state.status == "ok" and state.weight_g == 42
    assert result == "sent" and link.sent[0][0] == "rezeptbuch/v1/station/1/scale/cmd"
