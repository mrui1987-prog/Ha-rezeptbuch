"""Schnittstellen Buchführung (Teil B1, docs/buchfuehrung-export.md) – alles mit PIN (K03-84: Prüfung macht ein Admin)."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends, Query, Response

from ..auth.dependencies import require_admin
from ..deps import get_db
from ..receiving import service as receiving
from . import service

router = APIRouter(prefix="/api/v1/admin", tags=["booking"], dependencies=[Depends(require_admin)])


@router.get("/booking/groups")
def groups(all: bool = False, db: sqlite3.Connection = Depends(get_db)):
    return service.list_groups(db, include_archived=all)


@router.post("/booking/groups", status_code=201)
def add_group(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.save_group(db, payload)


@router.patch("/booking/groups/{group_id}")
def edit_group(group_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.save_group(db, payload, group_id)


@router.post("/booking/groups/{group_id}/move")
def move_group(group_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.move_group(db, group_id, payload.get("direction"))


@router.get("/booking/unchecked")
def unchecked(db: sqlite3.Connection = Depends(get_db)):
    return service.unchecked(db)


@router.post("/booking/confirm")
def confirm(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return {"confirmed": service.confirm(db, payload.get("items"))}


@router.get("/booking/month")
def month(month: str = Query(...), db: sqlite3.Connection = Depends(get_db)):
    return service.month_rows(db, month)


@router.get("/booking/export.xlsx")
def export(month: str = Query(...), db: sqlite3.Connection = Depends(get_db)):
    data = service.export_xlsx(db, month)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="Wareneingang_{month}.xlsx"'})


@router.get("/receiving/substitutes")
def substitutes(db: sqlite3.Connection = Depends(get_db)):
    """M03-35: Rohstoffe mit Marke „Ersatzware im Bestand – Pass prüfen“."""
    return receiving.list_substitutes(db)


@router.post("/receiving/substitutes/{rm_id}/clear", status_code=204)
def clear_substitute(rm_id: int, db: sqlite3.Connection = Depends(get_db)):
    receiving.clear_substitute(db, rm_id)
    return Response(status_code=204)
