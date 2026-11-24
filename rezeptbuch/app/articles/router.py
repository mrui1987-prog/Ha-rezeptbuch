"""Schnittstellen der Verkaufsartikel (Modul 10, Teil P-A, docs/planer.md 13).

Lesen ohne PIN (Planer an der Station, K10-P5), Pflege, Import und Export nur mit Admin-Sitzung.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends, Response

from ..auth.dependencies import require_admin
from ..deps import get_db
from ..imports.router import upload_body
from . import export, group_names, service, vectron

router = APIRouter(prefix="/api/v1", tags=["articles"])
admin = [Depends(require_admin)]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/articles")
def list_articles(q: str | None = None, group: int | None = None, status: str = "active",
                  without_lines: bool = False, not_planned: bool = False, db: sqlite3.Connection = Depends(get_db)):
    return service.list_articles(db, search=q, group=group, status=status, without_lines=without_lines,
                                 not_planned=not_planned)


@router.get("/articles/groups")
def article_groups(db: sqlite3.Connection = Depends(get_db)):
    return service.groups(db)


@router.get("/articles/group-names")
def article_group_names(db: sqlite3.Connection = Depends(get_db)):
    """Namen der Warengruppen (Nummer → Name), ohne PIN lesbar."""
    return {str(k): v for k, v in group_names.get_names(db).items()}


@router.post("/admin/articles/group-names/import", dependencies=admin)
def import_group_names(mode: str = "check", body: bytes = Depends(upload_body),
                       db: sqlite3.Connection = Depends(get_db)):
    """Warengruppen-Export der Vectron (.xlsx, Spalten Nummer/Name): ``mode=check`` → ``mode=run``."""
    return group_names.import_groups(db, body, mode=mode)


@router.get("/articles/{article_id}")
def get_article(article_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.get_article(db, article_id)


@router.get("/admin/articles/export.xlsx", dependencies=admin)
def export_articles(status: str = "all", db: sqlite3.Connection = Depends(get_db)):
    return Response(content=export.build_workbook(db, status=status), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{export.file_name()}"'})


@router.post("/admin/articles/import", dependencies=admin)
def import_articles(mode: str = "check", groups: str | None = None, body: bytes = Depends(upload_body),
                    db: sqlite3.Connection = Depends(get_db)):
    """Vectron-Artikelliste (.xlsx): ``mode=check`` (Probelauf) → ``mode=run``; ``groups=1,2,…`` (Vorgabe 1–14)."""
    return vectron.import_articles(db, body, mode=mode, groups=groups)


@router.post("/admin/articles/replace", dependencies=admin)
def replace_in_lines(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.replace_in_lines(db, payload)


@router.post("/admin/articles/bulk", dependencies=admin)
def bulk(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.bulk(db, payload)


@router.patch("/admin/articles/{article_id}", dependencies=admin)
def update(article_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.update_article(db, article_id, payload)


@router.put("/admin/articles/{article_id}/lines", dependencies=admin)
def set_lines(article_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.set_lines(db, article_id, payload.get("lines"))


@router.post("/admin/articles/{article_id}/copy-lines", dependencies=admin)
def copy_lines(article_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.copy_lines(db, article_id, payload.get("from_article_id"))
