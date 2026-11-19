"""MQTT-Zugangsdaten vom Supervisor (M08-2, K08-3: aus Add-on 2 übernommen).

Zugangsdaten kommen über ``services: mqtt:need`` vom Supervisor, nie aus dem
Code oder der Konfiguration. Der Token steht in der Umgebung oder – bei
``init: false`` unter s6 – in der Umgebungsdatei (Erfahrung Add-on 2, 0.7.1).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

SUPERVISOR_MQTT_URL = "http://supervisor/services/mqtt"

TOKEN_FILES = (
    "/run/s6/container_environment/SUPERVISOR_TOKEN",
    "/var/run/s6/container_environment/SUPERVISOR_TOKEN",
)


class CredentialsError(RuntimeError):
    pass


def read_supervisor_token(environ: dict | None = None, files: tuple = TOKEN_FILES) -> str | None:
    """Token aus der Umgebung, sonst aus der s6-Umgebungsdatei."""
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
