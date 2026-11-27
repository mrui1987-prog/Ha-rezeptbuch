"""Schnittstellen der Inventur (docs/strichcode.md 10, Teil I1).

Zählen ohne PIN (K03-59), blind: die Zählansicht zeigt weder Buchbestand noch Preise. Anlegen, Vorschau,
Abschluss, Verwerfen, Zählliste und Export mit PIN (S4, M03-13).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends, Response

from ..auth.dependencies import require_admin
from ..deps import get_db
from ..errors import ValidationError
from . import service

router = APIRouter(prefix="/api/v1", tags=["stocktake"])
admin = [Depends(require_admin)]


def _ids(text: str | None) -> list[int] | None:
    if text is None or text == "":
        return None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not all(p.isdigit() for p in parts):
        raise ValidationError("Ungültige Auswahl.", field="zero_ids")
    return [int(p) for p in parts]


# -- Zählen (ohne PIN) ---------------------------------------------------------------

@router.get("/stocktakes/open")
def open_stocktake(db: sqlite3.Connection = Depends(get_db)):
    """Offene Inventur mit Zählständen je Rohstoff und Lagerort; ``stocktake`` = null, wenn keine offen ist."""
    return service.open_view(db)


@router.post("/stocktakes/open/counts", status_code=201)
def add_count(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.add_count(db, payload)


@router.delete("/stocktakes/open/counts/{count_id}")
def delete_count(count_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.delete_count(db, count_id)


@router.post("/stocktakes/open/location-done")
def location_done(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """„Ort fertig“ (O-4): die gewählten, hier noch nicht gezählten Einträge mit 0."""
    return service.location_done(db, payload)


# -- Verwalten (PIN) -----------------------------------------------------------------

@router.get("/admin/stocktakes", dependencies=admin)
def list_stocktakes(db: sqlite3.Connection = Depends(get_db)):
    return service.list_stocktakes(db)


@router.post("/admin/stocktakes", status_code=201, dependencies=admin)
def create(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.create(db, payload)


@router.get("/admin/stocktakes/{stocktake_id}.xlsx", dependencies=admin)
def export_xlsx(stocktake_id: int, db: sqlite3.Connection = Depends(get_db)):
    data, name = service.export_xlsx(db, stocktake_id)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/admin/stocktakes/{stocktake_id}/countlist", dependencies=admin)
def countlist(stocktake_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Zählliste zum Drucken (nach Lagerort, ohne Preise und Buchbestand); gedruckt wird in der Seite."""
    return service.countlist(db, stocktake_id)


@router.get("/admin/stocktakes/{stocktake_id}", dependencies=admin)
def detail(stocktake_id: int, zero_ids: str | None = None, db: sqlite3.Connection = Depends(get_db)):
    """Vorschau (offen: gezählt, Buchbestand, Differenz, Wert) bzw. Ergebnis (abgeschlossen)."""
    return service.detail(db, stocktake_id, _ids(zero_ids))


@router.post("/admin/stocktakes/{stocktake_id}/close", dependencies=admin)
def close(stocktake_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.close(db, stocktake_id, payload)


@router.post("/admin/stocktakes/{stocktake_id}/cancel", dependencies=admin)
def cancel(stocktake_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.cancel(db, stocktake_id)
