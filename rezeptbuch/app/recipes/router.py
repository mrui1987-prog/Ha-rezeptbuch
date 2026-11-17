"""Schnittstellen der Rezeptverwaltung (Modul 05, docs/rezepte.md Abschnitt 7).

Der Router übersetzt nur HTTP; die Regeln stehen in ``service.py`` und ``groups.py``.
Lesen ist ohne PIN möglich (die Stationen brauchen das in Modul 09/10), alle ändernden
Aufrufe verlangen eine Admin-Sitzung.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Body, Depends, Response

from ..auth.dependencies import require_admin
from ..deps import get_db
from . import bulk as bulk_module
from . import groups, service

router = APIRouter(prefix="/api/v1", tags=["recipes"])
admin = [Depends(require_admin)]


def _confirm(payload: dict, key: str) -> bool:
    return isinstance(payload, dict) and payload.get(key) is True


# -- Lesen (ohne PIN) -------------------------------------------------------------

@router.get("/recipes")
def list_recipes(search: str | None = None, group_id: int | None = None, include_locked: bool = False,
                 include_archived: bool = False, archived_raw_materials: bool = False,
                 include_public: bool = True, never_weighed: bool = False, has_sub_recipes: bool = False,
                 db: sqlite3.Connection = Depends(get_db)):
    return service.list_recipes(db, search=search, group_id=group_id, include_locked=include_locked,
                                include_archived=include_archived, archived_raw_materials=archived_raw_materials,
                                include_public=include_public, never_weighed=never_weighed,
                                has_sub_recipes=has_sub_recipes)


@router.get("/recipes/{recipe_id}")
def get_recipe(recipe_id: int, db: sqlite3.Connection = Depends(get_db)):
    # ohne interne Notiz: die Stationen zeigen sie nie (KC2-2)
    return service.get_recipe(db, recipe_id, include_internal=False)


@router.get("/recipes/{recipe_id}/versions/{version_no}")
def get_version(recipe_id: int, version_no: int, db: sqlite3.Connection = Depends(get_db)):
    return service.get_version(db, recipe_id, version_no)


@router.get("/recipe-groups")
def list_groups(db: sqlite3.Connection = Depends(get_db)):
    return groups.list_groups(db)


# -- Rezepte ändern (mit Admin-Sitzung); feste Pfade vor den Pfaden mit Nummer -------

@router.get("/admin/recipes/next-number", dependencies=admin)
def next_number(db: sqlite3.Connection = Depends(get_db)):
    return {"number": service.next_number(db)}


@router.post("/admin/recipes/bulk", dependencies=admin)
def bulk(body: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    """Sammelaktion für angehakte Rezepte (C3-E1): Vorschau oder Ausführung."""
    return bulk_module.bulk_action(db, body.get("action"), body.get("ids"), mode=body.get("mode", "check"),
                                   confirm=body.get("confirm") is True)


@router.get("/admin/recipes/{recipe_id}", dependencies=admin)
def get_recipe_admin(recipe_id: int, db: sqlite3.Connection = Depends(get_db)):
    """Wie ``/recipes/{id}``, zusätzlich mit interner Notiz (nur Admin-Bereich)."""
    return service.get_recipe(db, recipe_id)


@router.post("/admin/recipes", status_code=201, dependencies=admin)
def create(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.create_recipe(db, payload)


@router.put("/admin/recipes/{recipe_id}", dependencies=admin)
def save(recipe_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    data = dict(payload)
    revision = data.pop("revision", None)
    version_mode = data.pop("version_mode", None)
    return service.save_recipe(db, recipe_id, data, revision=revision, version_mode=version_mode)


@router.put("/admin/recipes/{recipe_id}/piece-weights", dependencies=admin)
def piece_weights(recipe_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.set_piece_weights(db, recipe_id, payload.get("piece_weights"),
                                     revision=payload.get("revision"),
                                     confirm_delete_batch_sizes=_confirm(payload, "confirm_delete_batch_sizes"))


@router.put("/admin/recipes/{recipe_id}/batch-sizes", dependencies=admin)
def batch_sizes(recipe_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return service.set_batch_sizes(db, recipe_id, payload.get("batch_sizes"), revision=payload.get("revision"))


@router.post("/admin/recipes/{recipe_id}/unlock", dependencies=admin)
def unlock(recipe_id: int, payload: dict | None = Body(default=None), db: sqlite3.Connection = Depends(get_db)):
    return service.unlock_recipe(db, recipe_id, confirm=_confirm(payload or {}, "confirm"))


@router.post("/admin/recipes/{recipe_id}/lock", dependencies=admin)
def lock(recipe_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.lock_recipe(db, recipe_id)


@router.post("/admin/recipes/{recipe_id}/archive", dependencies=admin)
def archive(recipe_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.archive_recipe(db, recipe_id)


@router.post("/admin/recipes/{recipe_id}/restore", dependencies=admin)
def restore(recipe_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.restore_recipe(db, recipe_id)


@router.post("/admin/recipes/{recipe_id}/copy", status_code=201, dependencies=admin)
def copy(recipe_id: int, db: sqlite3.Connection = Depends(get_db)):
    return service.copy_recipe(db, recipe_id)


@router.delete("/admin/recipes/{recipe_id}", status_code=204, dependencies=admin)
def delete(recipe_id: int, db: sqlite3.Connection = Depends(get_db)):
    service.delete_recipe(db, recipe_id)
    return Response(status_code=204)


# -- Gruppen (mit Admin-Sitzung) ------------------------------------------------------

@router.post("/admin/recipe-groups", status_code=201, dependencies=admin)
def create_group(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return groups.create_group(db, payload.get("name"))


@router.put("/admin/recipe-groups/order", dependencies=admin)
def reorder_groups(payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return groups.reorder_groups(db, payload.get("group_ids"))


@router.patch("/admin/recipe-groups/{group_id}", dependencies=admin)
def rename_group(group_id: int, payload: dict = Body(...), db: sqlite3.Connection = Depends(get_db)):
    return groups.rename_group(db, group_id, payload.get("name"))


@router.delete("/admin/recipe-groups/{group_id}", status_code=204, dependencies=admin)
def delete_group(group_id: int, db: sqlite3.Connection = Depends(get_db)):
    groups.delete_group(db, group_id)
    return Response(status_code=204)
