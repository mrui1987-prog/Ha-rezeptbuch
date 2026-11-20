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
from . import service, sources, stock
from .export import build_csv

router = APIRouter(prefix="/api/v1", tags=["raw-materials"])
admin = [Depends(require_admin)]


# -- Lesen (ohne PIN) -------------------------------------------------------------

@router.get("/raw-materials")
def list_raw_materials(search: str | None = None, include_archived: bool = False,
                       zero_percent: bool = False, below_alert: bool = False,
                       db: sqlite3.Connection = Depends(get_db)):
    return service.list_raw_materials(db, search=search, include_archived=include_archived,
                                      zero_percent=zero_percent, below_alert=below_alert)


@router.get("/raw-materials/{raw_material_id}")
def get_raw_material(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.get_raw_material(db, raw_material_id)


@router.get("/raw-materials/{raw_material_id}/stock/movements")
def stock_movements(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Buchungsverlauf (VC03-b, B8), die letzten 50."""
    return stock.movements(db, raw_material_id)


@router.post("/raw-materials/{raw_material_id}/stock/receipt")
def stock_receipt(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """„Zugang buchen“ – bewusst ohne PIN, auch an der Station (M03-13)."""
    stock.receipt(db, raw_material_id, payload)
    return service.get_raw_material(db, raw_material_id)


@router.get("/raw-materials/{raw_material_id}/sources")
def list_sources(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Bezugsquellen (Modul 04, K04-4: ohne PIN lesbar)."""
    return sources.list_sources(db, raw_material_id)


# -- Ändern (mit Admin-Sitzung); feste Pfade vor den Pfaden mit Nummer -----------------

@router.post("/admin/raw-materials/bulk-active-source", dependencies=admin)
def bulk_active_source(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """Massenpflege „als aktive Bezugsquelle setzen“ (M04-6); ``dry_run`` = Vorschau."""
    return sources.bulk_active_source(db, payload)


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
def archive(raw_material_id: int, payload: dict | None = Body(None), db: sqlite3.Connection = Depends(get_db)):
    stock_zero = isinstance(payload, dict) and payload.get("stock_zero") is True
    return service.archive_raw_material(db, raw_material_id, stock_zero=stock_zero)


@router.post("/admin/raw-materials/{raw_material_id}/stock/inventory", dependencies=admin)
def stock_inventory(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """„Bestand setzen“ (Inventur, leer = Bestandsführung beenden), mit PIN (M03-13)."""
    stock.inventory(db, raw_material_id, payload)
    return service.get_raw_material(db, raw_material_id)


@router.post("/admin/raw-materials/{raw_material_id}/restore", dependencies=admin)
def restore(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.restore_raw_material(db, raw_material_id)


@router.delete("/admin/raw-materials/{raw_material_id}", status_code=204, dependencies=admin)
def delete(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    service.delete_raw_material(db, raw_material_id)
    return Response(status_code=204)


# -- Bezugsquellen (Modul 04 Teil C1) ------------------------------------------------

@router.post("/admin/raw-materials/{raw_material_id}/sources", status_code=201, dependencies=admin)
def add_source(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return sources.add_source(db, raw_material_id, payload)


@router.patch("/admin/raw-materials/{raw_material_id}/sources/{source_id}", dependencies=admin)
def update_source(raw_material_id: int, source_id: int, payload: dict = Body(...),
                  db: sqlite3.Connection = Depends(get_db)):
    return sources.update_source(db, raw_material_id, source_id, payload)


@router.post("/admin/raw-materials/{raw_material_id}/sources/{source_id}/activate", dependencies=admin)
def activate_source(raw_material_id: int, source_id: int, db: sqlite3.Connection = Depends(get_db)):
    return sources.activate_source(db, raw_material_id, source_id)


@router.delete("/admin/raw-materials/{raw_material_id}/sources/{source_id}", dependencies=admin)
def delete_source(raw_material_id: int, source_id: int, db: sqlite3.Connection = Depends(get_db)):
    return sources.delete_source(db, raw_material_id, source_id)
