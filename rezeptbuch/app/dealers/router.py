"""Schnittstellen der Händlerliste (Modul 04, docs/kennzeichnungspass-import.md 8).

Lesen ohne PIN (K04-4), Ändern mit Admin-Sitzung.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends, Response

from ..auth.dependencies import require_admin
from ..deps import get_db
from . import service

router = APIRouter(prefix="/api/v1", tags=["dealers"])
admin = [Depends(require_admin)]


@router.get("/dealers")
def list_dealers(include_archived: bool = False, db: sqlite3.Connection = Depends(get_db)):
    return service.list_dealers(db, include_archived=include_archived)


@router.post("/admin/dealers", status_code=201, dependencies=admin)
def create(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.create_dealer(db, payload)


@router.patch("/admin/dealers/{dealer_id}", dependencies=admin)
def rename(dealer_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.rename_dealer(db, dealer_id, payload)


@router.post("/admin/dealers/{dealer_id}/archive", dependencies=admin)
def archive(dealer_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.set_archived(db, dealer_id, True)


@router.post("/admin/dealers/{dealer_id}/restore", dependencies=admin)
def restore(dealer_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.set_archived(db, dealer_id, False)


@router.delete("/admin/dealers/{dealer_id}", status_code=204, dependencies=admin)
def delete(dealer_id: int, db: sqlite3.Connection = Depends(get_db)):
    service.delete_dealer(db, dealer_id)
    return Response(status_code=204)
