import io
import json
import urllib.error

import pytest

from app.messages import AVAILABILITY_TOPIC
from app.mqtt_client import CredentialsError, MqttBridge, fetch_credentials


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(body):
    def opener(request, timeout):
        assert request.headers["Authorization"] == "Bearer tok"
        if isinstance(body, Exception):
            raise body
        return FakeResponse(json.dumps(body).encode())
    return opener


def test_fetch_credentials():
    body = {"result": "ok", "data": {"host": "core-mosquitto", "port": 1883,
                                     "username": "addons", "password": "geheim", "ssl": False}}
    creds = fetch_credentials("tok", opener=opener_for(body))
    assert creds == {"host": "core-mosquitto", "port": 1883, "username": "addons",
                     "password": "geheim", "ssl": False}


def test_fetch_credentials_errors():
    with pytest.raises(CredentialsError, match="SUPERVISOR_TOKEN"):
        fetch_credentials("")
    with pytest.raises(CredentialsError, match="Mosquitto"):
        fetch_credentials("tok", opener=opener_for({"result": "error", "data": {}}))
    with pytest.raises(CredentialsError, match="nicht erreichbar"):
        fetch_credentials("tok", opener=opener_for(urllib.error.URLError("weg")))


class Info:
    def wait_for_publish(self, timeout=None):
        pass


class FakeClient:
    def __init__(self):
        self.calls = []
        self.published = []
        self.subscribed = []

    def __getattr__(self, name):
        def record(*a, **kw):
            self.calls.append((name, a, kw))
        return record

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return Info()

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)


class RC:
    def __init__(self, failure):
        self.is_failure = failure


def make_bridge():
    client = FakeClient()
    bridge = MqttBridge({"host": "core-mosquitto", "port": 1883, "username": "u",
                         "password": "p", "ssl": False}, client_factory=lambda: client)
    bridge.start()
    return bridge, client


def test_last_will_and_connect():
    bridge, client = make_bridge()
    names = [c[0] for c in client.calls]
    assert ("will_set", (AVAILABILITY_TOPIC, "offline"), {"qos": 1, "retain": True}) in client.calls
    assert names.index("will_set") < names.index("connect_async")
    assert ("username_pw_set", ("u", "p"), {}) in client.calls
    assert "loop_start" in names


def test_online_and_resubscribe_on_connect():
    bridge, client = make_bridge()
    received = []
    bridge.subscribe("rezeptbuch/test/waage1/raw", received.append)
    assert client.subscribed == []                  # noch nicht verbunden
    assert bridge.publish("x", "y") is False        # Live-Werte ohne Verbindung verworfen
    bridge._on_connect(client, None, {}, RC(False), None)
    assert client.published[0] == (AVAILABILITY_TOPIC, "online", 1, True)
    assert client.subscribed == ["rezeptbuch/test/waage1/raw"]

    class Msg:
        topic = "rezeptbuch/test/waage1/raw"
        payload = b"-----\r\n"
    bridge._on_message(client, None, Msg)
    assert received == [b"-----\r\n"]
    assert bridge.publish("rezeptbuch/v1/station/1/scale/state", "{}") is True
    assert client.published[-1] == ("rezeptbuch/v1/station/1/scale/state", "{}", 0, False)


def test_refused_connect():
    bridge, client = make_bridge()
    bridge._on_connect(client, None, {}, RC(True), None)
    assert not bridge.connected and client.published == []


def test_disconnect_and_stop():
    bridge, client = make_bridge()
    bridge._on_connect(client, None, {}, RC(False), None)
    bridge._on_disconnect(client, None, {}, RC(True), None)
    assert not bridge.connected
    bridge._on_connect(client, None, {}, RC(False), None)
    bridge.stop()
    assert client.published[-1] == (AVAILABILITY_TOPIC, "offline", 1, True)
    assert "disconnect" in [c[0] for c in client.calls]


def test_real_paho_client_if_installed():
    pytest.importorskip("paho.mqtt.client")
    from app.mqtt_client import _default_client_factory
    client = _default_client_factory()
    client.will_set(AVAILABILITY_TOPIC, "offline", qos=1, retain=True)
