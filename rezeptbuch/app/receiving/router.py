"""Schnittstellen Wareneingang W1 (docs/wareneingang.md 9). Hochladen/Löschen/Archiv mit PIN,
Lieferungen abhaken und buchen ohne PIN (W1, K03-21)."""

from __future__ import annotations

import sqlite3
from urllib.parse import unquote

from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import FileResponse

from ..auth.dependencies import require_admin
from ..deps import get_db
from ..errors import PayloadTooLargeError
from . import service

router = APIRouter(prefix="/api/v1", tags=["receiving"])
admin = [Depends(require_admin)]
MAX_PDF = 10 * 1024 * 1024


async def pdf_body(request: Request) -> bytes:
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_PDF:
            raise PayloadTooLargeError("PDF größer als 10 MB.", code="file_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/admin/receiving/upload", dependencies=admin)
def upload(request: Request, body: bytes = Depends(pdf_body), db: sqlite3.Connection = Depends(get_db)):
    """Ein PDF im Anfragekörper (Kopf X-Dateiname) → Probelauf mit Zuordnung."""
    name = request.headers.get("x-dateiname")
    return service.upload(db, body, unquote(name)[:200] if name else None)


@router.post("/admin/receiving/commit", status_code=201, dependencies=admin)
def commit(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.commit(db, payload)


@router.get("/admin/receiving/documents", dependencies=admin)
def documents(db: sqlite3.Connection = Depends(get_db)):
    return service.list_documents(db)


@router.get("/admin/receiving/documents/{doc_id}.pdf", dependencies=admin)
def document_pdf(doc_id: int, db: sqlite3.Connection = Depends(get_db)):
    path = service.document_pdf(db, doc_id)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.delete("/admin/receiving/documents/{doc_id}", status_code=204, dependencies=admin)
def delete_document(doc_id: int, db: sqlite3.Connection = Depends(get_db)):
    service.delete_document(db, doc_id)
    return Response(status_code=204)


@router.get("/receiving/deliveries")
def deliveries(db: sqlite3.Connection = Depends(get_db)):
    return service.list_deliveries(db)


@router.get("/receiving/deliveries/{doc_id}")
def delivery(doc_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.get_delivery(db, doc_id)


@router.post("/receiving/deliveries/{doc_id}/unexpected")
def unexpected(doc_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.add_unexpected(db, doc_id, payload)


@router.post("/receiving/deliveries/{doc_id}/book")
def book(doc_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.book(db, doc_id, payload)


@router.get("/admin/other-articles", dependencies=admin)
def other_articles(include_archived: bool = False, db: sqlite3.Connection = Depends(get_db)):
    return service.list_other_articles(db, include_archived)


@router.patch("/admin/other-articles/{other_id}", dependencies=admin)
def other_article_update(other_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.update_other_article(db, other_id, payload)
