"""Schnittstellen der Rezeptberechnung (Modul 06, docs/berechnung.md Abschnitt 7.1).

Nur lesend und **ohne PIN**: Die Stationen brauchen die Berechnung in der Vorwahl
(Modul 09/10). Die Regeln stehen in ``service.py`` und ``engine.py``.
POST statt GET, weil die Eingabe Listen enthält; die Anfrage ändert nichts.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends

from ..deps import get_db
from . import service

router = APIRouter(prefix="/api/v1", tags=["calculation"])


@router.get("/recipes/{recipe_id}/basis-options")
def basis_options(recipe_id: int, version_no: int | None = None, db: sqlite3.Connection = Depends(get_db)):
    return service.basis_options(db, recipe_id, version_no=version_no)


@router.post("/calculation")
def calculation(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.calculate(db, payload)
