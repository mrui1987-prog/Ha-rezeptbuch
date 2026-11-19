"""MQTT-Verbindung von Add-on 1 (M08-2, docs/schnittstellen.md Abschnitt 5).

paho-mqtt läuft in seinem eigenen Thread (``loop_start``). Die Rückrufe geben
Nachrichten und den Verbindungsstand nur weiter; der Aufrufer (``service``)
reicht sie mit ``call_soon_threadsafe`` an die asyncio-Schleife. paho wird erst
beim Start geladen, damit die übrigen Tests ohne paho laufen.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .messages import AVAILABILITY_TOPIC, STATE_TOPIC_FILTER

CLIENT_ID = "rezeptbuch-addon1"
KEEPALIVE_S = 30

log = logging.getLogger("rezeptbuch.scales")


def _failed(reason_code: Any) -> bool:
    flag = getattr(reason_code, "is_failure", None)
    if flag is not None:
        return bool(flag)
    return reason_code not in (0, None)


def _default_client_factory() -> Any:
    import paho.mqtt.client as mqtt  # erst hier laden

    return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID)


class MqttLink:
    def __init__(
        self,
        creds: dict,
        on_message: Callable[[str, bytes], None],
        on_connection: Callable[[bool], None],
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.creds = creds
        self._on_message_cb = on_message
        self._on_connection_cb = on_connection
        self._factory = client_factory or _default_client_factory
        self.client: Any = None
        self.connected = False

    def start(self) -> None:
        client = self._factory()
        if self.creds.get("username"):
            client.username_pw_set(self.creds["username"], self.creds.get("password"))
        if self.creds.get("ssl"):
            client.tls_set()
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
        client.subscribe(STATE_TOPIC_FILTER, qos=0)
        client.subscribe(AVAILABILITY_TOPIC, qos=1)
        log.info("MQTT verbunden, Waagen-Topics abonniert")
        self._on_connection_cb(True)

    def _on_disconnect(self, client, userdata, flags=None, reason_code=None, properties=None) -> None:
        if self.connected:
            log.warning("MQTT: Verbindung getrennt (%s), paho baut neu auf", reason_code)
        self.connected = False
        self._on_connection_cb(False)

    def _on_message(self, client, userdata, msg) -> None:
        self._on_message_cb(msg.topic, msg.payload)

    # --- Nutzung -----------------------------------------------------------

    def publish(self, topic: str, payload: str) -> bool:
        """Befehl senden: QoS 1, **nie retained** (K08-1)."""
        if not self.connected or self.client is None:
            return False
        self.client.publish(topic, payload, qos=1, retain=False)
        return True

    def stop(self) -> None:
        if self.client is None:
            return
        try:
            self.client.disconnect()
            self.client.loop_stop()
        except Exception:  # noqa: BLE001 – Beenden darf nicht scheitern
            log.debug("MQTT: Fehler beim Beenden ignoriert", exc_info=True)
        self.connected = False
