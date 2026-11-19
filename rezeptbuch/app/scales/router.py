"""Waagen-Schnittstelle des Rezeptservers (M08-5, M08-6, docs/schnittstellen.md 6 und 7).

REST ``/api/v1/stations…`` und Live-Kanal ``/api/v1/live`` – beide **ohne PIN**
(Stationsbedienung, K08-4). Alle Abfragen gehen an den Mittelsmann.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from . import hub as hub_mod
from .hub import ScaleHub

router = APIRouter(tags=["Waagen"])

PING_S = 15.0     # Herzschlag des Live-Kanals (K08-2)

_SENT_TEXT = ("Befehl gesendet. Ob die Waage ihn ausführt, zeigt der nächste Wert "
              "(Nullstellen nur bei leerer Waage bis ±50 g).")


def get_hub(app) -> ScaleHub | None:
    service = getattr(app.state, "scales", None)
    return service.hub if service is not None else None


def _not_started() -> JSONResponse:
    return JSONResponse(status_code=503, content={
        "detail": "Die Waagen-Anbindung ist nicht gestartet.", "code": "mqtt_down"})


@router.get("/api/v1/stations")
def list_stations(request: Request):
    hub = get_hub(request.app)
    if hub is None:
        return {"mqtt": hub_mod.MQTT_UNAVAILABLE, "bridge": "unknown", "stations": []}
    return {**hub.link(), "stations": [s.to_dict() for s in hub.snapshot()]}


@router.get("/api/v1/stations/{station}/scale")
def station_scale(station: int, request: Request):
    hub = get_hub(request.app)
    if hub is None:
        return _not_started()
    state = hub.current_state(station)
    if state is None:
        return JSONResponse(status_code=404, content={
            "detail": f"Station {station} ist nicht bekannt.", "code": "unknown_station"})
    return state.to_dict()


def _command(station: int, cmd: str, request: Request) -> JSONResponse:
    hub = get_hub(request.app)
    if hub is None:
        return _not_started()
    result = hub.send_command(station, cmd)
    if result == hub_mod.RESULT_SENT:
        return JSONResponse(status_code=202, content={"result": "sent", "detail": _SENT_TEXT})
    if result == hub_mod.RESULT_UNKNOWN:
        return JSONResponse(status_code=404, content={
            "detail": f"Station {station} ist nicht bekannt.", "code": "unknown_station"})
    if result == hub_mod.RESULT_NOT_CONFIGURED:
        return JSONResponse(status_code=409, content={
            "detail": f"Station {station} ist im Rezeptbuch nicht eingerichtet – Befehl nicht gesendet.",
            "code": "not_configured"})
    if result == hub_mod.RESULT_OFFLINE:
        return JSONResponse(status_code=409, content={
            "detail": f"Waage {station} ist offline – Befehl nicht gesendet.", "code": "offline"})
    return JSONResponse(status_code=503, content={
        "detail": "Waage nicht verbunden (MQTT) – Befehl nicht gesendet.", "code": "mqtt_down"})


@router.post("/api/v1/stations/{station}/scale/tare", status_code=202)
def tare(station: int, request: Request):
    return _command(station, "tare", request)


@router.post("/api/v1/stations/{station}/scale/zero", status_code=202)
def zero(station: int, request: Request):
    return _command(station, "zero", request)


@router.websocket("/api/v1/live")
async def live(ws: WebSocket):
    """Schnappschuss beim Verbinden, danach jede Änderung, Herzschlag alle 15 s (K08-2).

    Der Client sendet nichts (Befehle laufen über REST); gelesen wird nur, um ein
    Schließen sofort zu bemerken.
    """
    hub = get_hub(ws.app)
    await ws.accept()
    if hub is None:
        await ws.send_json({"type": "link", "mqtt": hub_mod.MQTT_UNAVAILABLE, "bridge": "unknown"})
        await ws.close(code=1011)
        return
    queue = hub.subscribe()
    closed = asyncio.Event()

    async def reader() -> None:
        try:
            while True:
                message = await ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
        except Exception:  # noqa: BLE001 – jede Störung heißt: Verbindung weg
            pass
        finally:
            closed.set()

    reader_task = asyncio.create_task(reader())
    try:
        await ws.send_json({"type": "link", **hub.link()})
        for state in hub.snapshot():
            await ws.send_json({"type": "scale", **state.to_dict()})
        while not closed.is_set():
            getter = asyncio.ensure_future(queue.get())
            closer = asyncio.ensure_future(closed.wait())
            done, _ = await asyncio.wait({getter, closer}, timeout=PING_S,
                                         return_when=asyncio.FIRST_COMPLETED)
            closer.cancel()
            if getter in done:
                event = getter.result()
            else:
                getter.cancel()
                event = {"type": "ping"}
            if closed.is_set():
                break
            await ws.send_json(event)
    except (WebSocketDisconnect, RuntimeError, ConnectionError):
        pass
    finally:
        hub.unsubscribe(queue)
        reader_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await reader_task
