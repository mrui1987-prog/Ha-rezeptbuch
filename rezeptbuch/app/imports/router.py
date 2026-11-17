"""Schnittstellen der Importe (Modul 05, docs/rezepte.md Abschnitt 7).

Rohstoff-CSV (Teil C1) und Importvorlage .xlsx (Teil C3). Die Datei kommt als Rohdaten im Anfragekörper (keine Bibliothek für Formular-Uploads
nötig). Ablauf: ``mode=check`` (Probelauf, Bericht) → ``mode=run`` mit derselben Datei;
werden vorhandene Rohstoffe überschrieben, zusätzlich ``confirm_overwrite=true``.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request

from ..auth.dependencies import require_admin
from ..deps import get_db
from ..errors import PayloadTooLargeError
from .raw_materials_csv import MAX_BYTES, import_raw_materials_csv
from .recipe_template import import_recipe_template

router = APIRouter(prefix="/api/v1/admin/import", tags=["import"], dependencies=[Depends(require_admin)])


async def upload_body(request: Request) -> bytes:
    """Liest den Anfragekörper, höchstens 5 MB (sonst 413)."""
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BYTES:
        raise PayloadTooLargeError("Die Datei ist zu groß (höchstens 5 MB).", code="file_too_large")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise PayloadTooLargeError("Die Datei ist zu groß (höchstens 5 MB).", code="file_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/raw-materials")
def import_raw_materials(mode: str = "check", confirm_overwrite: bool = False,
                         body: bytes = Depends(upload_body), db: sqlite3.Connection = Depends(get_db)):
    return import_raw_materials_csv(db, body, mode=mode, confirm_overwrite=confirm_overwrite)


@router.post("/recipes")
def import_recipes(mode: str = "check", confirm_overwrite: bool = False,
                   body: bytes = Depends(upload_body), db: sqlite3.Connection = Depends(get_db)):
    """Vorlagen-Import (.xlsx, Teil C3): Probelauf → Bericht → Import, alles oder nichts."""
    return import_recipe_template(db, body, mode=mode, confirm_overwrite=confirm_overwrite)
