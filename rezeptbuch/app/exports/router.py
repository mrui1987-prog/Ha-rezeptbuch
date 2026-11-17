"""Schnittstelle des Rezept-Exports (Modul 05, Teil C3, docs/rezepte.md Abschnitt 6.3 und 7).

Wird in ``main.py`` vor dem Rezept-Router eingebunden, damit ``/admin/recipes/export.xlsx``
nicht als Rezept-ID gelesen wird.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Response

from ..auth.dependencies import require_admin
from ..deps import get_db
from .recipe_template import build_workbook, file_name

router = APIRouter(prefix="/api/v1/admin", tags=["export"], dependencies=[Depends(require_admin)])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/recipes/export.xlsx")
def export_recipes(include_archived: bool = False, db: sqlite3.Connection = Depends(get_db)):
    return Response(content=build_workbook(db, include_archived=include_archived), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{file_name()}"'})
