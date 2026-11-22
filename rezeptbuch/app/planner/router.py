"""Schnittstellen des Planers P-B (docs/planer.md 13).

Planen, Planläufe, Aufträge anlegen und Abbuchen bewusst ohne PIN (K10-P5, wie „Zugang buchen“);
nur der Schalter „Planer in der Vorwahl“ braucht die Admin-Sitzung.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends

from ..auth.dependencies import require_admin
from ..deps import get_db
from . import service

router = APIRouter(prefix="/api/v1", tags=["planner"])


@router.get("/plans")
def plan_days(date_from: str, date_to: str, db: sqlite3.Connection = Depends(get_db)):
    return service.plan_days(db, date_from, date_to)


@router.get("/plans/{day}")
def get_plan(day: str, db: sqlite3.Connection = Depends(get_db)):
    return service.get_plan(db, day)


@router.put("/plans/{day}")
def save_plan(day: str, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.save_plan(db, day, payload)


@router.post("/plans/{day}/add")
def add_to_plan(day: str, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.add_to_plan(db, day, payload)


@router.get("/plans/{day}/stock")
def stock_needs(day: str, db: sqlite3.Connection = Depends(get_db)):
    return service.stock_needs(db, day)


@router.post("/plans/{day}/stock-booking")
def book_stock(day: str, payload: dict = Body(default={}), db: sqlite3.Connection = Depends(get_db)):
    return service.book_stock(db, day, payload)


@router.post("/plan-runs")
def create_run(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.create_run(db, payload)


@router.get("/plan-runs/{run_id}")
def get_run(run_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.get_run(db, run_id)


@router.put("/plan-runs/{run_id}")
def update_run(run_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.update_run(db, run_id, payload)


@router.post("/plan-runs/{run_id}/commit")
def commit_run(run_id: int, payload: dict = Body(default={}), db: sqlite3.Connection = Depends(get_db)):
    return service.commit_run(db, run_id, payload)


@router.get("/orders/{order_id}/articles")
def order_articles(order_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.order_articles(db, order_id)


@router.get("/settings/planner")
def get_settings(db: sqlite3.Connection = Depends(get_db)):
    return service.get_settings(db)


@router.put("/admin/settings/planner", dependencies=[Depends(require_admin)])
def save_settings(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.save_settings(db, payload)
