"""Schnittstelle des Rezept-Exports (Modul 05, Teil C3, docs/rezepte.md Abschnitt 6.3 und 7).

Wird in ``main.py`` vor dem Rezept-Router eingebunden, damit ``/admin/recipes/export.xlsx``
nicht als Rezept-ID gelesen wird.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Response

from ..auth.dependencies import require_admin
from ..deps import get_db
from ..errors import ValidationError
from .recipe_template import build_workbook, file_name

router = APIRouter(prefix="/api/v1/admin", tags=["export"], dependencies=[Depends(require_admin)])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/recipes/export.xlsx")
def export_recipes(include_archived: bool = False, ids: str | None = None, db: sqlite3.Connection = Depends(get_db)):
    """Alle Rezepte oder nur die Auswahl ``ids=1,2,3`` (Sammelaktion „Exportieren“, C3-E1)."""
    selected = None
    if ids is not None:
        try:
            selected = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise ValidationError("ids muss eine Liste von Zahlen sein (1,2,3).", field="ids") from None
        if not selected or len(selected) > 1000:
            raise ValidationError("Bitte 1 bis 1000 Rezepte auswählen.", field="ids")
    return Response(content=build_workbook(db, include_archived=include_archived, ids=selected), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{file_name()}"'})
