"""Schnittstellen der Rohstoffverwaltung (Modul 03, docs/rohstoffe.md Abschnitt 6).

Der Router übersetzt nur HTTP; die Regeln stehen in ``service.py``. Lesen ist ohne PIN
möglich (die Stationen brauchen das später), alle ändernden Aufrufe und der Export
verlangen eine Admin-Sitzung.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends, Response

from ..auth.dependencies import require_admin
from ..deps import get_db
from . import service
from .export import build_csv

router = APIRouter(prefix="/api/v1", tags=["raw-materials"])
admin = [Depends(require_admin)]


# -- Lesen (ohne PIN) -------------------------------------------------------------

@router.get("/raw-materials")
def list_raw_materials(search: str | None = None, include_archived: bool = False,
                       zero_percent: bool = False, db: sqlite3.Connection = Depends(get_db)):
    return service.list_raw_materials(db, search=search, include_archived=include_archived,
                                      zero_percent=zero_percent)


@router.get("/raw-materials/{raw_material_id}")
def get_raw_material(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.get_raw_material(db, raw_material_id)


# -- Ändern (mit Admin-Sitzung); feste Pfade vor den Pfaden mit Nummer -----------------

@router.get("/admin/raw-materials/next-number", dependencies=admin)
def next_number(db: sqlite3.Connection = Depends(get_db)):
    return {"number": service.next_number(db)}


@router.get("/admin/raw-materials/similar", dependencies=admin)
def similar(name: str = "", exclude_id: int | None = None, db: sqlite3.Connection = Depends(get_db)):
    return service.similar_names(db, name, exclude_id=exclude_id)


@router.get("/admin/raw-materials/export.csv", dependencies=admin)
def export_csv(db: sqlite3.Connection = Depends(get_db)):
    data = build_csv(service.list_raw_materials(db, include_archived=True))
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rohstoffe.csv"'},
    )


@router.post("/admin/raw-materials", status_code=201, dependencies=admin)
def create(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.create_raw_material(db, payload)


@router.patch("/admin/raw-materials/{raw_material_id}", dependencies=admin)
def update(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    data = dict(payload)
    confirm = data.pop("confirm_type_change", False) is True
    return service.update_raw_material(db, raw_material_id, data, confirm_type_change=confirm)


@router.post("/admin/raw-materials/{raw_material_id}/archive", dependencies=admin)
def archive(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.archive_raw_material(db, raw_material_id)


@router.post("/admin/raw-materials/{raw_material_id}/restore", dependencies=admin)
def restore(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.restore_raw_material(db, raw_material_id)


@router.delete("/admin/raw-materials/{raw_material_id}", status_code=204, dependencies=admin)
def delete(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    service.delete_raw_material(db, raw_material_id)
    return Response(status_code=204)
