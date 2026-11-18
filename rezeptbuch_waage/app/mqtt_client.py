"""Verbindung zum MQTT-Broker (Mosquitto in HA) mit Letztem Willen (K07-2).

Zugangsdaten kommen vom Supervisor (`services: mqtt:need`), nie aus dem Code
oder der Konfiguration. Eine Verbindung für das ganze Add-on; Verfügbarkeit
`online`/`offline` retained auf `rezeptbuch/v1/scale_bridge/availability`.
paho-mqtt wird erst beim Start geladen (Tests laufen auch ohne paho).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from typing import Any, Callable

from .messages import AVAILABILITY_TOPIC, OFFLINE, ONLINE

SUPERVISOR_MQTT_URL = "http://supervisor/services/mqtt"
CLIENT_ID = "rezeptbuch_waage"
KEEPALIVE_S = 30

log = logging.getLogger("rezeptbuch_waage")


class CredentialsError(RuntimeError):
    pass


TOKEN_FILES = (
    "/run/s6/container_environment/SUPERVISOR_TOKEN",
    "/var/run/s6/container_environment/SUPERVISOR_TOKEN",
)


def read_supervisor_token(environ: dict | None = None, files: tuple = TOKEN_FILES) -> str | None:
    """Token aus der Umgebung, sonst aus der s6-Umgebungsdatei (init: false)."""
    env = os.environ if environ is None else environ
    token = env.get("SUPERVISOR_TOKEN")
    if token:
        return token
    for path in files:
        try:
            with open(path, encoding="utf-8") as handle:
                token = handle.read().strip()
        except OSError:
            continue
        if token:
            return token
    return None


def fetch_credentials(
    token: str | None = None,
    url: str = SUPERVISOR_MQTT_URL,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict:
    """Fragt den Supervisor nach Adresse und Zugang des MQTT-Dienstes."""
    token = token if token is not None else read_supervisor_token()
    if not token:
        raise CredentialsError("SUPERVISOR_TOKEN fehlt (Add-on läuft nicht unter HA?)")
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with opener(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise CredentialsError(f"Supervisor nicht erreichbar: {exc}") from exc
    data = body.get("data") if isinstance(body, dict) else None
    if not data or not data.get("host"):
        raise CredentialsError("MQTT-Dienst nicht gefunden – Mosquitto installiert?")
    return {
        "host": data["host"],
        "port": int(data.get("port") or 1883),
        "username": data.get("username") or None,
        "password": data.get("password") or None,
        "ssl": bool(data.get("ssl")),
    }


def _failed(reason_code: Any) -> bool:
    flag = getattr(reason_code, "is_failure", None)
    if flag is not None:
        return bool(flag)
    return reason_code not in (0, None)


def _default_client_factory() -> Any:
    import paho.mqtt.client as mqtt  # erst hier laden

    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID)


class MqttBridge:
    def __init__(self, creds: dict, client_factory: Callable[[], Any] | None = None) -> None:
        self.creds = creds
        self._factory = client_factory or _default_client_factory
        self.client: Any = None
        self.connected = False
        self._subs: dict[str, Callable[[bytes], None]] = {}
        self._lock = threading.Lock()

    def start(self) -> None:
        client = self._factory()
        if self.creds.get("username"):
            client.username_pw_set(self.creds["username"], self.creds.get("password"))
        if self.creds.get("ssl"):
            client.tls_set()
        client.will_set(AVAILABILITY_TOPIC, OFFLINE, qos=1, retain=True)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client = client
        client.connect_async(self.creds["host"], self.creds["port"], keepalive=KEEPALIVE_S)
        client.loop_start()
        log.info("MQTT: verbinde mit %s:%s", self.creds["host"], self.creds["port"])

    # --- Rückrufe (paho-Thread) --------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if _failed(reason_code):
            log.error("MQTT: Anmeldung abgelehnt (%s)", reason_code)
            return
        self.connected = True
        client.publish(AVAILABILITY_TOPIC, ONLINE, qos=1, retain=True)
        with self._lock:
            topics = list(self._subs)
        for topic in topics:
            client.subscribe(topic, qos=0)
        log.info("MQTT: verbunden, Verfügbarkeit online")

    def _on_disconnect(self, client, userdata, flags=None, reason_code=None, properties=None) -> None:
        if self.connected:
            log.warning("MQTT: Verbindung getrennt (%s), paho baut neu auf", reason_code)
        self.connected = False

    def _on_message(self, client, userdata, msg) -> None:
        with self._lock:
            callback = self._subs.get(msg.topic)
        if callback is not None:
            callback(msg.payload)

    # --- Nutzung -----------------------------------------------------------

    def subscribe(self, topic: str, callback: Callable[[bytes], None]) -> None:
        with self._lock:
            self._subs[topic] = callback
        if self.connected and self.client is not None:
            self.client.subscribe(topic, qos=0)

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> bool:
        """Live-Werte: ohne Verbindung verworfen, kein Nachsenden (docs/waage.md 10)."""
        if not self.connected or self.client is None:
            return False
        self.client.publish(topic, payload, qos=qos, retain=retain)
        return True

    def stop(self) -> None:
        if self.client is None:
            return
        if self.connected:
            info = self.client.publish(AVAILABILITY_TOPIC, OFFLINE, qos=1, retain=True)
            try:
                info.wait_for_publish(timeout=2)
            except Exception:  # noqa: BLE001 – Beenden darf nicht scheitern
                pass
        self.client.disconnect()
        self.client.loop_stop()
        self.connected = False
