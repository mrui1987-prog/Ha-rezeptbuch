"""Schnittstelle des Wiegeablaufs (Modul 09, docs/ablauf.md Abschnitt 11).

Ohne PIN (Stationsbedienung, K09-6), außer dem Ändern der Einstellungen. Jede ändernde Anfrage
nennt die Station. Nach jeder Änderung geht eine Nachricht über den Live-Kanal ``/api/v1/live``
(Typen ``batch`` und ``orders``; ``weigh`` sendet der Runner laufend).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends, Request, Response

from ..auth.dependencies import require_admin
from ..deps import get_db
from . import batches, orders
from .runner import ProductionRunner
from .settings import describe_settings, save_settings

router = APIRouter(prefix="/api/v1", tags=["Wiegeablauf"])


def get_runner(request: Request) -> ProductionRunner:
    runner = getattr(request.app.state, "production", None)
    if runner is None:
        scales = getattr(request.app.state, "scales", None)
        runner = ProductionRunner(scales.hub if scales is not None else None)
        request.app.state.production = runner
    return runner


def _batch_event(runner: ProductionRunner, data: dict, event: str) -> dict:
    runner.broadcast({"type": "batch", "batch_id": data["id"], "status": data["status"],
                      "owner_station": data["owner_station"], "current_position": data["current_position"],
                      "event": event})
    if event in ("started", "finished_dough", "cancelled", "finished"):
        runner.broadcast({"type": "orders"})
    return data


# -- Aufträge -----------------------------------------------------------------------

@router.get("/orders")
def list_orders(date: str | None = None, db: sqlite3.Connection = Depends(get_db)):
    return orders.list_orders(db, date)


@router.post("/orders", status_code=201)
def create_order(request: Request, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    data = orders.create_order(db, payload)
    get_runner(request).broadcast({"type": "orders"})
    return data


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: sqlite3.Connection = Depends(get_db)):
    return orders.get_order(db, order_id)


@router.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: int, request: Request, payload: dict | None = Body(default=None),
                 db: sqlite3.Connection = Depends(get_db)):
    orders.delete_order(db, order_id, payload or {})
    get_runner(request).broadcast({"type": "orders"})
    return Response(status_code=204)


@router.get("/orders/{order_id}/stock")
def order_stock(order_id: int, dough_index: int | None = None, db: sqlite3.Connection = Depends(get_db)):
    """Bestandsstatus je Rohstoff für die Rezeptübersicht (VC03-b, B6)."""
    return batches.order_stock(db, order_id, dough_index)


@router.post("/orders/{order_id}/start", status_code=201)
def start(order_id: int, request: Request, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    runner = get_runner(request)
    return _batch_event(runner, batches.start_dough(db, order_id, payload, runner), "started")


# -- Chargen ----------------------------------------------------------------------------

@router.get("/batches")
def list_batches(station: int | None = None, db: sqlite3.Connection = Depends(get_db)):
    return {"batches": batches.list_batches(db, station)}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, request: Request, db: sqlite3.Connection = Depends(get_db)):
    return batches.get_batch(db, batch_id, get_runner(request))


def _action(name: str, func, event: str, **kw):
    def endpoint(batch_id: int, request: Request, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
        runner = get_runner(request)
        data = func(db, batch_id, payload, runner, **kw)
        if event == "acked" and data["status"] == "done":
            return _batch_event(runner, data, "finished_dough")
        return _batch_event(runner, data, event)
    endpoint.__name__ = name
    router.add_api_route(f"/batches/{{batch_id}}/{name}", endpoint, methods=["POST"])


_action("select", batches.select_item, "selected")
_action("units", batches.ack_units, "acked")
_action("ack", batches.ack_weighed, "acked")
_action("hand", batches.ack_hand, "acked")
_action("skip", batches.skip_item, "acked")
_action("sub-check", batches.check_sub, "acked")
_action("tare", batches.tare, "tared")
_action("pause", batches.pause, "paused")
_action("hand-scale", batches.pause, "paused", reason="hand_scale")
_action("resume", batches.resume, "resumed")
_action("cancel", batches.cancel, "cancelled")
_action("finish", batches.finish, "finished")
_action("container", batches.container, "container")


# -- Station: Waage im Ablauf und Handbetrieb (Abschnitt 9) ------------------------------------

@router.get("/stations/{station}/weigh")
def station_weigh(station: int, request: Request):
    """Stand der Waage im Ablauf: Anzeige, Bezug, Ist, Gesamtlast, Tara läuft, Behälter-Schritt."""
    return get_runner(request).reading(station).to_dict()


@router.post("/stations/{station}/hand/tare")
def hand_tare(station: int, request: Request, db: sqlite3.Connection = Depends(get_db)):
    return batches.hand_tare(db, station, get_runner(request))


@router.post("/stations/{station}/hand/zero")
def hand_zero(station: int, request: Request, db: sqlite3.Connection = Depends(get_db)):
    return batches.hand_zero(db, station, get_runner(request))


# -- Einstellungen ---------------------------------------------------------------------------

@router.get("/production-settings")
@router.get("/admin/production-settings")
def read_settings(db: sqlite3.Connection = Depends(get_db)):
    return {"settings": describe_settings(db)}


@router.put("/admin/production-settings", dependencies=[Depends(require_admin)])
def write_settings(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    save_settings(db, payload)
    return {"settings": describe_settings(db)}
