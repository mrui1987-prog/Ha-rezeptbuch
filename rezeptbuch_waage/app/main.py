"""Einstiegspunkt der Waagen-Bridge.

Stand 0.1.0: liest die Konfiguration und meldet die Stationen als 'offline'.
Der KERN-Treiber und die MQTT-Verbindung folgen in Modul 07/08.
"""

import json
import logging
import time
from pathlib import Path

from . import __version__
from .messages import state_payload, state_topic

OPTIONS_FILE = Path("/data/options.json")
log = logging.getLogger("rezeptbuch_waage")


def load_options(path: Path = OPTIONS_FILE) -> dict:
    if not path.exists():
        return {"stations": [], "log_level": "info"}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    options = load_options()
    logging.basicConfig(
        level=options.get("log_level", "info").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log.info("HA-Rezeptbuch Waage %s startet", __version__)
    for st in options.get("stations", []):
        log.info(
            "Station %s: Treiber %s, %s:%s",
            st["station"], st["driver"], st["host"], st["port"],
        )
        log.debug("%s %s", state_topic(st["station"]),
                  state_payload(st["station"], None, False, "offline"))
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
