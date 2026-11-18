"""MQTT-Weg (Roh-Topic des Waveshare) mit nachgebildeter Verbindung."""

import asyncio
import threading

from app.config import StationConfig
from app.station import StationMonitor
from app.transport_mqtt import MqttRawTransport


class FakeBridge:
    def __init__(self):
        self.subs = {}

    def subscribe(self, topic, callback):
        self.subs[topic] = callback


def test_packets_from_paho_thread_reach_station():
    async def body():
        cfg = StationConfig(station=1, enabled=True, connection="mqtt",
                            raw_topic="rezeptbuch/test/waage1/raw",
                            cmd_topic="rezeptbuch/test/waage1/cmd")
        mon = StationMonitor(cfg)
        mon.connected = True
        bridge = FakeBridge()
        MqttRawTransport(mon, bridge, asyncio.get_running_loop()).start()
        assert mon.connected is None
        callback = bridge.subs["rezeptbuch/test/waage1/raw"]

        # Pakete wie beim Waveshare: halbe und gebündelte Zeilen, aus fremdem Thread
        packets = [b"ST,G    0.0", b"77kg\r\nUS,G    0.080kg\r\n-----\r\nST,G", b"    0.081kg\r\n"]
        thread = threading.Thread(target=lambda: [callback(p) for p in packets])
        thread.start()
        thread.join()
        for _ in range(20):
            await asyncio.sleep(0)
        assert mon._last_reading.weight_g == 81
        assert mon.status(asyncio.get_running_loop().time()) in ("ok", "offline")

    asyncio.run(body())
