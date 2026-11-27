"""Tests Strichcode-Scanner Teil S1 (docs/strichcode.md 11): Normierung, Zuordnen, Buchen, Rückgängig,
Lagerorte, Einkäufe, Hilfs- und Betriebsstoffe, Migration 0011."""

import shutil
import sqlite3

import pytest

from app.db import MIGRATIONS_DIR, init_database
from app.errors import ConflictError, NotFoundError, ValidationError
from app.raw_materials import scanner, service, stock

from conftest import add_item, add_raw_material, add_recipe

DEV = "geraet-a"


def material(conn, name="Weizenmehl 550", **kw):
    data = {"name": name, "type": "standard", "tolerance_unit": "g", "tolerance": "5"}
    data.update(kw)
    return service.create_raw_material(conn, data)["id"]


def purchase(conn, label="Metro"):
    return scanner.create_purchase(conn, {"label": label, "device_id": DEV})["id"]


# -- Normierung ------------------------------------------------------------------------

def test_ean13_and_gtin14_same_key():
    assert scanner.normalize("4006381333931") == "04006381333931"
    assert scanner.normalize("04006381333931") == "04006381333931"
    assert scanner.display("04006381333931") == "4006381333931"


def test_upca_and_ean8():
    assert scanner.normalize("036000291452") == "00036000291452"
    assert scanner.normalize("96385074") == "00000096385074"


def test_upce_expanded():
    # UPC-E 04252614 ↔ UPC-A 042100005264
    assert scanner.upce_to_upca("04252614") == "042100005264"
    assert scanner.normalize("04252614", "upc_e") == "00042100005264"


def test_gs1_only_gtin():
    assert scanner.normalize("(01)04006381333931(10)ABC123(17)271231") == "04006381333931"
    assert scanner.normalize("]C1010400638133393110ABC\x1d17271231", "code_128") == "04006381333931"
    assert scanner.normalize("01040063813339311727123110L1", "code_128") == "04006381333931"


def test_other_codes_stay_text():
    assert scanner.normalize(" ABC-123 ", "code_39") == "ABC-123"
    assert scanner.normalize("4006381333932") == "4006381333932"      # falsche Prüfziffer → Text
    with pytest.raises(ValidationError):
        scanner.normalize("   ")


# -- Zuordnen ----------------------------------------------------------------------------

def test_unknown_then_assign_with_pack(conn):
    rm = material(conn)
    assert scanner.lookup(conn, "4006381333931")["status"] == "unknown"
    res = scanner.assign(conn, {"code": "4006381333931", "raw_material_id": rm, "format": "ean_13",
                                "pack_g": 25000, "pack_label": "Sack"})
    assert res["status"] == "known" and res["raw_material"]["pack_g"] == 25000
    assert service.get_raw_material(conn, rm)["unit_label"] == "Sack"
    # GTIN-14-Schreibweise trifft denselben Code
    assert scanner.lookup(conn, "04006381333931")["raw_material"]["id"] == rm


def test_code_unique_reassign_needs_pin_path(conn):
    a, b = material(conn, "A"), material(conn, "B")
    scanner.assign(conn, {"code": "ABC", "raw_material_id": a})
    with pytest.raises(ConflictError) as e:
        scanner.assign(conn, {"code": "ABC", "raw_material_id": b})
    assert e.value.code == "code_taken"
    scanner.reassign(conn, "ABC", {"raw_material_id": b})
    assert scanner.lookup(conn, "ABC")["raw_material"]["id"] == b
    assert len(scanner.list_for(conn, b)) == 1 and scanner.list_for(conn, a) == []


def test_pack_only_when_empty(conn):
    rm = material(conn, unit_size_g=25000, unit_label="Sack")
    with pytest.raises(ConflictError) as e:
        scanner.set_pack(conn, rm, {"pack_g": 10000, "pack_label": "Sack"})
    assert e.value.code == "pack_set"


def test_candidates_without_code_first(conn):
    a, b = material(conn, "Mehl A"), material(conn, "Mehl B")
    scanner.assign(conn, {"code": "X1", "raw_material_id": a})
    names = [c["name"] for c in scanner.candidates(conn, "mehl")]
    assert names == ["Mehl B", "Mehl A"]


# -- Buchen ------------------------------------------------------------------------------

def test_receipt_needs_purchase(conn):
    rm = material(conn, unit_size_g=25000, unit_label="Sack")
    stock.inventory(conn, rm, {"stock_kg": "0"})
    with pytest.raises(ValidationError) as e:
        stock.scan_book(conn, rm, {"device_id": DEV}, mode="receipt")
    assert e.value.code == "purchase_required"
    p = purchase(conn)
    for _ in range(3):
        res = stock.scan_book(conn, rm, {"device_id": DEV, "purchase_id": p}, mode="receipt")
    assert res["stock_g"] == 75000
    assert scanner.list_purchases(conn)[0]["bookings"] == 3
    assert stock.movements(conn, rm)[0]["purchase_label"] == "Metro"


def test_delivery_pack_wins(conn):
    rm = material(conn, "Ei", unit_size_g=55, unit_label="Ei", delivery_pack_g=9900, delivery_pack_label="Karton")
    stock.inventory(conn, rm, {"stock_kg": "0"})
    res = stock.scan_book(conn, rm, {"device_id": DEV}, mode="correction")
    assert res["delta_g"] == 9900 and res["pack_label"] == "Karton"


def test_without_pack_blocked(conn):
    rm = material(conn)
    stock.inventory(conn, rm, {"stock_kg": "1"})
    with pytest.raises(ConflictError) as e:
        stock.scan_book(conn, rm, {"device_id": DEV, "reason": "breakage"}, mode="loss")
    assert e.value.code == "pack_missing"


def test_not_tracked_and_archived(conn):
    rm = material(conn, unit_size_g=25000, unit_label="Sack")
    p = purchase(conn)
    with pytest.raises(ConflictError) as e:
        stock.scan_book(conn, rm, {"device_id": DEV, "purchase_id": p}, mode="receipt")
    assert e.value.code == "not_tracked"
    with pytest.raises(ConflictError):
        stock.scan_book(conn, rm, {"device_id": DEV, "reason": "breakage"}, mode="loss")
    res = stock.scan_book(conn, rm, {"device_id": DEV, "purchase_id": p, "start_tracking": True}, mode="receipt")
    assert res["stock_g"] == 25000
    service.archive_raw_material(conn, rm)
    with pytest.raises(ConflictError) as e:
        stock.scan_book(conn, rm, {"device_id": DEV, "purchase_id": p}, mode="receipt")
    assert e.value.code == "archived"


def test_loss_with_reason_and_filter(conn):
    rm = material(conn, unit_size_g=25000, unit_label="Sack")
    stock.inventory(conn, rm, {"stock_kg": "50"})
    with pytest.raises(ValidationError):
        stock.scan_book(conn, rm, {"device_id": DEV}, mode="loss")
    stock.scan_book(conn, rm, {"device_id": DEV, "reason": "breakage"}, mode="loss")
    stock.loss(conn, rm, {"amount_kg": "2,5", "reason": "merchandise", "source": "quick_entry"})
    rows = stock.movements_all(conn, kind="loss")
    assert [r["reason_text"] for r in rows] == ["Handelsware", "Bruch/Verderb"]
    assert service.get_raw_material(conn, rm)["stock_g"] == 22500


def test_inventory_packs_plus_rest(conn):
    rm = material(conn, unit_size_g=25000, unit_label="Sack")
    stock.inventory(conn, rm, {"packs": 3, "rest_kg": "12,5", "source": "scan", "device_id": DEV})
    assert service.get_raw_material(conn, rm)["stock_g"] == 87500


def test_undo_own_device_once(conn):
    rm = material(conn, unit_size_g=25000, unit_label="Sack")
    stock.inventory(conn, rm, {"stock_kg": "0"})
    p = purchase(conn)
    mid = stock.scan_book(conn, rm, {"device_id": DEV, "purchase_id": p}, mode="receipt")["movement_id"]
    with pytest.raises(ConflictError) as e:
        stock.undo(conn, mid, {"device_id": "anderes"})
    assert e.value.code == "undo_not_allowed"
    assert stock.undo(conn, mid, {"device_id": DEV})["stock_g"] == 0
    with pytest.raises(ConflictError) as e:
        stock.undo(conn, mid, {"device_id": DEV})
    assert e.value.code == "undo_done"


def test_undo_expired(conn):
    rm = material(conn, unit_size_g=25000, unit_label="Sack")
    stock.inventory(conn, rm, {"stock_kg": "0"})
    mid = stock.scan_book(conn, rm, {"device_id": DEV}, mode="correction")["movement_id"]
    conn.execute("UPDATE stock_movement SET created_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-11 minutes') "
                 "WHERE id = ?", (mid,))
    with pytest.raises(ConflictError) as e:
        stock.undo(conn, mid, {"device_id": DEV})
    assert e.value.code == "undo_expired"


def test_undo_not_for_admin_bookings(conn):
    rm = material(conn)
    mid = stock.inventory(conn, rm, {"stock_kg": "5"})
    with pytest.raises(ConflictError):
        stock.undo(conn, mid, {"device_id": DEV})


# -- Lagerorte ---------------------------------------------------------------------------

def test_locations_on_material(conn):
    a = scanner.create_location(conn, {"name": "Mehllager", "code": "ORT-1"})
    b = scanner.create_location(conn, {"name": "Kühlhaus"})
    with pytest.raises(ConflictError):
        scanner.create_location(conn, {"name": "mehllager"})
    rm = material(conn, location1_id=a["id"], location2_id=b["id"], location2_label="Anbruch")
    got = service.get_raw_material(conn, rm)
    assert got["location1_name"] == "Mehllager" and got["location2_label"] == "Anbruch"
    assert scanner.lookup(conn, "ORT-1")["status"] == "location"
    with pytest.raises(ConflictError):
        scanner.assign(conn, {"code": "ORT-1", "raw_material_id": rm})
    with pytest.raises(ValidationError):
        service.update_raw_material(conn, rm, {"location2_id": a["id"]})
    service.update_raw_material(conn, rm, {"location1_id": None})
    got = service.get_raw_material(conn, rm)
    assert got["location1_name"] == "Kühlhaus" and got["location2_id"] is None


# -- Hilfs- und Betriebsstoffe -------------------------------------------------------------

def test_aid_counts_units(conn):
    rm = service.create_raw_material(conn, {"name": "Brötchentüten", "type": "aid", "unit_label": "Karton"})
    assert rm["unit_size_g"] == 1000 and rm["tolerance"] == 0
    stock.inventory(conn, rm["id"], {"packs": 4, "source": "scan", "device_id": DEV})
    res = stock.scan_book(conn, rm["id"], {"device_id": DEV, "reason": "own_use"}, mode="loss")
    assert res["stock_g"] == 3000          # 3 Karton
    with pytest.raises(ValidationError):
        service.create_raw_material(conn, {"name": "Folie", "type": "aid"})


def test_aid_not_in_recipe_and_type_lock(conn):
    from app.recipes import service as recipes
    aid = service.create_raw_material(conn, {"name": "Tüten", "type": "aid", "unit_label": "Karton"})["id"]
    rm = add_raw_material(conn, 50, "Salz")
    _, version = add_recipe(conn, 10)
    add_item(conn, version, 1, rm, 100)
    with pytest.raises(ConflictError) as e:
        service.update_raw_material(conn, rm, {"type": "aid", "unit_label": "Sack"})
    assert e.value.code == "type_locked_aid"
    with pytest.raises(ValidationError) as e:
        recipes._check_references(conn, None, {"items": [{"position": 1, "item_type": "raw_material",
                                                          "raw_material_id": aid}]}, [])
    assert e.value.code == "raw_material_aid"


# -- Migration 0011 auf befüllter Datenbank -----------------------------------------------

def test_migration_0011_keeps_movements(tmp_path):
    old_dir = tmp_path / "migrations"
    old_dir.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(path.name[:4]) <= 10:
            shutil.copy(path, old_dir / path.name)
    db = tmp_path / "x.db"
    conn = init_database(db, migrations_dir=old_dir)
    rm = add_raw_material(conn, 7, "Roggenmehl 1150")
    conn.execute("UPDATE raw_material SET stock_g = 25000, unit_size_g = 25000, unit_label = 'Sack' WHERE id = ?",
                 (rm,))
    conn.execute("INSERT INTO stock_movement (raw_material_id, kind, delta_g, stock_after_g) "
                 "VALUES (?, 'receipt', 25000, 25000)", (rm,))
    conn.execute("INSERT INTO plan_stock_booking (production_date, raw_material_id, amount_g, stock_movement_id) "
                 "VALUES ('2026-11-22', ?, 100, 1)", (rm,))
    conn.close()
    conn = init_database(db, backup_dir=tmp_path / "backups")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    row = conn.execute("SELECT * FROM raw_material WHERE id = ?", (rm,)).fetchone()
    assert row["stock_g"] == 25000 and row["delivery_pack_g"] is None and row["location1_id"] is None
    assert conn.execute("SELECT kind, delta_g FROM stock_movement").fetchall()[0][:] == ("receipt", 25000)
    conn.execute("DELETE FROM stock_movement WHERE id = 1")          # Fremdschlüssel greift weiter (SET NULL)
    assert conn.execute("SELECT stock_movement_id FROM plan_stock_booking").fetchone()[0] is None
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO stock_movement (raw_material_id, kind) VALUES (?, 'loss')", (rm,))


# -- Zuordnung zurücknehmen (Befund Michael 27.11.2026) -----------------------------------

def test_release_fresh_code_without_pin(conn):
    a, b = material(conn, "A"), material(conn, "B")
    scanner.assign(conn, {"code": "4006381333931", "raw_material_id": a})
    with pytest.raises(NotFoundError):                                   # falscher Artikel
        scanner.release(conn, {"code": "4006381333931", "raw_material_id": b})
    assert scanner.release(conn, {"code": "04006381333931", "raw_material_id": a})["status"] == "released"
    assert scanner.lookup(conn, "4006381333931")["status"] == "unknown"


def test_release_refused_when_old_or_reassigned(conn):
    a, b = material(conn, "A"), material(conn, "B")
    scanner.assign(conn, {"code": "OLD", "raw_material_id": a})
    conn.execute("UPDATE raw_material_barcode SET created_at = '2026-01-01T00:00:00Z', "
                 "updated_at = '2026-01-01T00:00:00Z' WHERE code = 'OLD'")
    conn.commit()
    with pytest.raises(ConflictError) as e:
        scanner.release(conn, {"code": "OLD", "raw_material_id": a})
    assert e.value.code == "release_too_late"
    scanner.assign(conn, {"code": "NEU", "raw_material_id": a})
    conn.execute("UPDATE raw_material_barcode SET updated_at = '2099-01-01T00:00:00Z' WHERE code = 'NEU'")
    conn.commit()
    with pytest.raises(ConflictError):
        scanner.release(conn, {"code": "NEU", "raw_material_id": a})
