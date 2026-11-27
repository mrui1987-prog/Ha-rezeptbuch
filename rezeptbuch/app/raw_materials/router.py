"""Schnittstellen der Rohstoffverwaltung (Modul 03, docs/rohstoffe.md Abschnitt 6).

Der Router übersetzt nur HTTP; die Regeln stehen in ``service.py``. Lesen ist ohne PIN
möglich (die Stationen brauchen das später), alle ändernden Aufrufe und der Export
verlangen eine Admin-Sitzung.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends, Request, Response
from fastapi.responses import FileResponse

from ..auth.dependencies import require_admin
from ..deps import get_db
from ..errors import PayloadTooLargeError, ValidationError
from ..imports.router import upload_body
from . import bulk, goods, sales_import, scanner, service, sources, stock
from .export import build_csv

router = APIRouter(prefix="/api/v1", tags=["raw-materials"])
admin = [Depends(require_admin)]


# -- Lesen (ohne PIN) -------------------------------------------------------------

def _ids(text: str | None) -> list[int] | None:
    """„1,2,3“ → [1, 2, 3] (Export der Auswahl); leer → None."""
    if text is None:
        return None
    parts = [p for p in text.split(",") if p.strip()]
    if not all(p.strip().isdigit() for p in parts):
        raise ValidationError("Ungültige Auswahl.", field="ids")
    return [int(p) for p in parts]


@router.get("/raw-materials")
def list_raw_materials(search: str | None = None, include_archived: bool = False,
                       zero_percent: bool = False, below_alert: bool = False,
                       status: str | None = None, type: str | None = None, stock: str | None = None,
                       no_price: bool = False, unused: bool = False, dealer_id: int | None = None,
                       no_source: bool = False, db: sqlite3.Connection = Depends(get_db)):
    """Liste mit den Filtern der Rohstoffverwaltung (M03-22); ohne PIN lesbar (R03-16, M03-13)."""
    return service.list_raw_materials(db, search=search, include_archived=include_archived,
                                      zero_percent=zero_percent, below_alert=below_alert,
                                      status=status, type_=type, stock=stock, no_price=no_price,
                                      unused=unused, dealer_id=dealer_id, no_source=no_source)


@router.get("/raw-materials/{raw_material_id}")
def get_raw_material(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.get_raw_material(db, raw_material_id)


@router.get("/raw-materials/{raw_material_id}/stock/movements")
def stock_movements(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Buchungsverlauf (VC03-b, B8), die letzten 50."""
    return stock.movements(db, raw_material_id)


@router.post("/raw-materials/{raw_material_id}/stock/receipt")
def stock_receipt(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """„Zugang buchen“ – bewusst ohne PIN, auch an der Station (M03-13). ``movement_id`` für das Beleg-Foto."""
    movement_id = stock.receipt(db, raw_material_id, payload)
    return dict(service.get_raw_material(db, raw_material_id), movement_id=movement_id)


async def photo_body(request: Request) -> bytes:
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > stock.PHOTO_MAX_BYTES:
            raise PayloadTooLargeError("Foto größer als 8 MB.", code="file_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/stock/movements/{movement_id}/photo")
def stock_photo_upload(movement_id: int, body: bytes = Depends(photo_body), db: sqlite3.Connection = Depends(get_db)):
    """Beleg-Foto an einen Zugang hängen (M03-37) – ohne PIN wie der Zugang; Bild im Anfragekörper."""
    return stock.attach_photo(db, movement_id, body)


@router.get("/admin/stock/movements/{movement_id}/photo", dependencies=admin)
def stock_photo(movement_id: int, db: sqlite3.Connection = Depends(get_db)):
    path, mime = stock.photo_path(db, movement_id)
    return FileResponse(path, media_type=mime)


@router.post("/raw-materials/{raw_material_id}/stock/loss")
def stock_loss(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """Abgang mit Grund (docs/strichcode.md 7), ohne PIN wie der Zugang."""
    stock.loss(db, raw_material_id, payload)
    return service.get_raw_material(db, raw_material_id)


# -- Scanner (docs/strichcode.md 10, Teil S1) --------------------------------------------

@router.get("/barcodes/candidates")
def barcode_candidates(search: str = "", location_id: int | None = None, limit: int = 30,
                       db: sqlite3.Connection = Depends(get_db)):
    return scanner.candidates(db, search, location_id, limit)


@router.get("/barcodes/lookup")
def barcode_lookup(code: str, format: str | None = None, db: sqlite3.Connection = Depends(get_db)):
    """Code nachschlagen (Code als Abfragewert, weil Codes Schrägstriche enthalten können)."""
    return scanner.lookup(db, code, format)


@router.post("/barcodes", status_code=201)
def barcode_assign(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """Erstes Zuordnen ohne PIN (S4), Gebinde beim ersten Scan."""
    return scanner.assign(db, payload)


@router.get("/raw-materials/{raw_material_id}/barcodes")
def barcodes_of(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    return scanner.list_for(db, raw_material_id)


@router.post("/raw-materials/{raw_material_id}/pack")
def set_pack(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """Gebinde einmal abfragen (nur wenn leer, H-F)."""
    return scanner.set_pack(db, raw_material_id, payload)


@router.post("/raw-materials/{raw_material_id}/scan/receipt")
def scan_receipt(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """+1 Einkauf – nur mit Beleg (O-1 geändert, Michael 22.11.2026)."""
    return stock.scan_book(db, raw_material_id, payload, mode="receipt")


@router.post("/raw-materials/{raw_material_id}/scan/loss")
def scan_loss(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return stock.scan_book(db, raw_material_id, payload, mode="loss")


@router.post("/stock/movements/{movement_id}/undo")
def undo_movement(movement_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """Rückgängig: eigenes Gerät, 10 Minuten (docs/strichcode.md 3)."""
    return stock.undo(db, movement_id, payload)


@router.get("/purchases")
def purchases(db: sqlite3.Connection = Depends(get_db)):
    return scanner.list_purchases(db)


@router.post("/purchases", status_code=201)
def purchase_create(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return scanner.create_purchase(db, payload)


@router.get("/storage-locations")
def storage_locations(include_archived: bool = False, db: sqlite3.Connection = Depends(get_db)):
    return scanner.list_locations(db, include_archived)


@router.post("/admin/storage-locations", status_code=201, dependencies=admin)
def storage_location_create(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return scanner.create_location(db, payload)


@router.patch("/admin/storage-locations/{location_id}", dependencies=admin)
def storage_location_update(location_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return scanner.update_location(db, location_id, payload)


@router.post("/admin/barcodes/reassign", dependencies=admin)
def barcode_reassign(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """Code umhängen (PIN, S4)."""
    return scanner.reassign(db, payload.get("code"), payload)


@router.delete("/admin/barcodes/{barcode_id}", status_code=204, dependencies=admin)
def barcode_delete(barcode_id: int, db: sqlite3.Connection = Depends(get_db)):
    scanner.delete_code(db, barcode_id)
    return Response(status_code=204)


@router.post("/admin/raw-materials/{raw_material_id}/scan/correction", dependencies=admin)
def scan_correction(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """+1 Korrektur ohne Beleg, mit PIN (O-1 geändert)."""
    return stock.scan_book(db, raw_material_id, payload, mode="correction")


@router.get("/raw-materials/{raw_material_id}/sources")
def list_sources(raw_material_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Bezugsquellen (Modul 04, K04-4: ohne PIN lesbar)."""
    return sources.list_sources(db, raw_material_id)


# -- Ändern (mit Admin-Sitzung); feste Pfade vor den Pfaden mit Nummer -----------------

@router.post("/admin/raw-materials/bulk-active-source", dependencies=admin)
def bulk_active_source(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """Massenpflege „als aktive Bezugsquelle setzen“ (M04-6); ``dry_run`` = Vorschau."""
    return sources.bulk_active_source(db, payload)


@router.post("/admin/raw-materials/bulk", dependencies=admin)
def bulk_action(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """Sammelaktionen der Rohstoffliste (M03-21): ``preview`` = Vorschau, Ausführen mit ``confirm``."""
    return bulk.run(db, payload)


@router.get("/admin/stock/movements", dependencies=admin)
def all_stock_movements(date_from: str | None = None, date_to: str | None = None,
                        raw_material_id: int | None = None, kind: str | None = None, limit: int = 500,
                        db: sqlite3.Connection = Depends(get_db)):
    """Buchungsverlauf aller Rohstoffe (Unterreiter „Bestand“, docs/rohstoffverwaltung.md 6.3)."""
    return stock.movements_all(db, date_from=date_from, date_to=date_to, raw_material_id=raw_material_id,
                               kind=kind, limit=limit)


@router.get("/admin/raw-materials/next-number", dependencies=admin)
def next_number(db: sqlite3.Connection = Depends(get_db)):
    return {"number": service.next_number(db)}


@router.get("/admin/raw-materials/similar", dependencies=admin)
def similar(name: str = "", exclude_id: int | None = None, db: sqlite3.Connection = Depends(get_db)):
    return service.similar_names(db, name, exclude_id=exclude_id)


@router.get("/admin/raw-materials/export.csv", dependencies=admin)
def export_csv(ids: str | None = None, include_archived: bool = True, db: sqlite3.Connection = Depends(get_db)):
    """CSV-Export; ``ids`` = nur die gewählten (Sammelaktion 7, K03-37), sonst alle (mit archivierten)."""
    chosen = _ids(ids)
    data = build_csv(service.list_raw_materials(db, include_archived=include_archived or chosen is not None,
                                                ids=chosen))
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
    """„Bestand setzen“ (Inventur, leer = Bestandsführung beenden), mit PIN (M03-13); auch „3 Sack + 12,5 kg“."""
    movement_id = stock.inventory(db, raw_material_id, payload)
    return dict(service.get_raw_material(db, raw_material_id), movement_id=movement_id)


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


# -- Handelsware und Pfand, Teil H1 (docs/handelsware.md) ------------------------------------

@router.post("/admin/raw-materials/{raw_material_id}/move", dependencies=admin)
def move_article(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """„Verschieben nach …“ (K03-89): Art desselben Artikels ändern."""
    return goods.move(db, raw_material_id, payload)


@router.post("/admin/raw-materials/{raw_material_id}/copy", status_code=201, dependencies=admin)
def copy_article(raw_material_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """„Kopieren nach …“ (K03-89, K03-93)."""
    return goods.copy(db, raw_material_id, payload)


@router.post("/admin/other-articles/{other_id}/move", dependencies=admin)
def move_other(other_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return goods.other_to(db, other_id, payload, keep=False)


@router.post("/admin/other-articles/{other_id}/copy", status_code=201, dependencies=admin)
def copy_other(other_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return goods.other_to(db, other_id, payload, keep=True)


@router.get("/admin/deposit-overview", dependencies=admin)
def deposit_overview(date_from: str | None = None, date_to: str | None = None,
                     db: sqlite3.Connection = Depends(get_db)):
    """Pfand BÄKO / Pfand Kunden / Pfand gesamt in Euro (K03-87)."""
    return goods.deposit_overview(db, date_from, date_to)


@router.post("/admin/sales-imports", dependencies=admin)
def import_sales(request: Request, mode: str = "check", date_from: str | None = None, date_to: str | None = None,
                 body: bytes = Depends(upload_body), db: sqlite3.Connection = Depends(get_db)):
    """Kassenimport Vectron-Abverkauf (.xlsx): ``mode=check`` (Probelauf) → ``mode=run`` (K03-86)."""
    from urllib.parse import unquote
    name = unquote(request.headers.get("x-dateiname") or "") or None
    return sales_import.import_sales(db, body, mode=mode, date_from=date_from, date_to=date_to, file_name=name)


@router.get("/admin/sales-imports", dependencies=admin)
def sales_imports(db: sqlite3.Connection = Depends(get_db)):
    return sales_import.list_imports(db)


@router.get("/admin/sales-imports/{import_id}", dependencies=admin)
def sales_import_detail(import_id: int, db: sqlite3.Connection = Depends(get_db)):
    return sales_import.get_import(db, import_id)


@router.delete("/admin/sales-imports/{import_id}", dependencies=admin)
def sales_import_delete(import_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Kassenimport zurücknehmen (Gegenbuchungen), der Zeitraum ist danach wieder frei."""
    return sales_import.delete_import(db, import_id)
