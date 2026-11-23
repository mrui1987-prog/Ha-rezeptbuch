"""Tests VC03-b: Rohstoffbestand und Meldewert (docs/bestand.md).

Eingabe in kg, Bestandsführung an/aus, Zugang/Inventur mit Protokoll, Filter, Archivieren mit „auf 0“,
CSV-Export/-Import, Abzug beim Verwiegen, Rückfrage beim Start, Rückbuchung beim Abbruch, Rezeptübersicht.
"""

import pytest

from app.errors import ConflictError, ValidationError
from app.imports.raw_materials_csv import import_raw_materials_csv
from app.production import batches, orders
from app.raw_materials import create_raw_material, get_raw_material, list_raw_materials, update_raw_material
from app.raw_materials.export import build_csv
from app.raw_materials.service import archive_raw_material
from app.raw_materials.stock import inventory, kg_text, movements, parse_kg, receipt, status

from prod_helpers import clock, hub, recipes, rm, runner  # noqa: F401  (Fixtures)

TODAY = "2026-11-20"


def total(recipe_id, grams):
    return {"recipe_id": recipe_id, "basis_type": "total", "value": grams, "planned_date": TODAY}


def st(station=1, **kw):
    return {"station": station, **kw}


def import_csv(conn, data, mode="run"):
    return import_raw_materials_csv(conn, data, mode=mode, confirm_overwrite=True)


def stock_of(conn, rm_id):
    return get_raw_material(conn, rm_id)["stock_g"]


# -- Eingabe und Anzeige (B1) ---------------------------------------------------------------------

@pytest.mark.parametrize("text, grams", [("12,5", 12500), ("12.5", 12500), ("0,001", 1), ("25", 25000),
                                         ("1.234,5", 1234500), ("-3", -3000), (7, 7000)])
def test_parse_kg(text, grams):
    assert parse_kg(text, "x", allow_empty=False) == grams


@pytest.mark.parametrize("text", ["abc", "1,2345", "12 kg", "1e3"])
def test_parse_kg_rejects(text):
    with pytest.raises(ValidationError):
        parse_kg(text, "x", allow_empty=False)


def test_parse_kg_empty_and_negative():
    assert parse_kg("", "x", allow_empty=True) is None
    with pytest.raises(ValidationError):
        parse_kg("", "x", allow_empty=False)
    with pytest.raises(ValidationError):
        parse_kg("-1", "x", allow_empty=False, allow_negative=False)


def test_kg_text_and_status():
    assert [kg_text(g) for g in (12500, 1, 25000, -1500, 0, None)] == ["12,5", "0,001", "25", "-1,5", "0", ""]
    assert status(None, 1000, 500) is None                    # keine Führung
    assert status(400, None, 500) == "short"
    assert status(1500, 1000, 500) == "alert"                 # nach Abzug 1 000 ≤ Meldewert
    assert status(1600, 1000, 500) is None
    assert status(900, 1000) == "alert"                       # Liste: am/unter Meldewert


# -- Buchungen (B2, B7) -----------------------------------------------------------------------------

def test_receipt_starts_tracking_and_inventory_ends_it(conn, rm):
    mehl = rm["mehl"]
    assert stock_of(conn, mehl) is None
    receipt(conn, mehl, {"amount_kg": "25", "note": "Lieferung"})
    receipt(conn, mehl, {"amount_kg": "12,5", "station": 1})
    assert stock_of(conn, mehl) == 37500
    inventory(conn, mehl, {"stock_kg": "30"})
    assert stock_of(conn, mehl) == 30000
    inventory(conn, mehl, {"stock_kg": "0"})                  # 0 = nichts da, Führung bleibt an
    assert stock_of(conn, mehl) == 0
    inventory(conn, mehl, {"stock_kg": None})                 # leer = Führung beenden
    assert stock_of(conn, mehl) is None
    moves = movements(conn, mehl)
    assert [m["kind"] for m in moves] == ["inventory", "inventory", "inventory", "receipt", "receipt"]
    assert [m["delta_g"] for m in moves] == [None, -30000, -7500, 12500, 25000]
    assert moves[0]["stock_after_g"] is None and moves[-1]["note"] == "Lieferung"
    assert moves[1]["kind_text"] == "Bestand gesetzt" and moves[3]["station_id"] == 1


def test_receipt_rejects_zero_negative_and_bad_station(conn, rm):
    for payload in ({"amount_kg": "0"}, {"amount_kg": "-1"}, {"amount_kg": ""}, {"amount_kg": "1", "station": 9}):
        with pytest.raises(ValidationError):
            receipt(conn, rm["mehl"], payload)
    with pytest.raises(ValidationError):
        inventory(conn, rm["mehl"], {})                       # Feld fehlt ganz


def test_alert_on_create_update_and_filter(conn, rm):
    zucker = create_raw_material(conn, {"name": "Zucker", "tolerance": "5", "stock_alert_kg": "10"})
    assert zucker["stock_alert_g"] == 10000 and zucker["stock_g"] is None and zucker["stock_status"] is None
    receipt(conn, zucker["id"], {"amount_kg": "8"})
    assert get_raw_material(conn, zucker["id"])["stock_status"] == "alert"
    update_raw_material(conn, rm["mehl"], {"stock_alert_kg": "5"})
    receipt(conn, rm["mehl"], {"amount_kg": "50"})
    names = [r["name"] for r in list_raw_materials(conn, below_alert=True)]
    assert names == ["Zucker"]
    update_raw_material(conn, zucker["id"], {"stock_alert_kg": None})
    assert list_raw_materials(conn, below_alert=True) == []
    with pytest.raises(ValidationError):
        update_raw_material(conn, zucker["id"], {"stock_alert_kg": "-1"})


def test_archive_with_stock_zero(conn, rm):
    receipt(conn, rm["salz"], {"amount_kg": "2"})
    receipt(conn, rm["hefe"], {"amount_kg": "1"})
    archive_raw_material(conn, rm["salz"], stock_zero=True)
    archive_raw_material(conn, rm["hefe"])
    assert stock_of(conn, rm["salz"]) == 0 and stock_of(conn, rm["hefe"]) == 1000
    assert movements(conn, rm["salz"])[0]["note"] == "beim Archivieren auf 0 gesetzt"
    update_raw_material(conn, rm["hefe"], {"stock_alert_kg": "5"})
    assert list_raw_materials(conn, below_alert=True) == []   # archivierte nicht im Filter


# -- CSV (B8) -----------------------------------------------------------------------------------

def test_csv_export_and_import_stock(conn, rm):
    receipt(conn, rm["mehl"], {"amount_kg": "12,5"})
    update_raw_material(conn, rm["mehl"], {"stock_alert_kg": "5"})
    lines = build_csv(list_raw_materials(conn)).decode("utf-8-sig").split("\r\n")
    header = lines[0].split(";")
    assert header[-5:-3] == ["Bestand kg", "Meldewert kg"]
    first = lines[1].split(";")
    assert first[-5:-3] == ["12,5", "5"]

    head = "Nummer;Name;Toleranz;Bestand kg;Meldewert kg\r\n"
    nums = {k: get_raw_material(conn, v)["number"] for k, v in rm.items()}
    csv = (head + f"{nums['mehl']};Weizenmehl 550;20;20;6\r\n"      # Bestand geändert → Inventur
           f"{nums['wasser']};Wasser;50;;\r\n"                      # leer: keine Führung bleibt keine
           f"{nums['salz']};Speisesalz;2;3;\r\n")
    report = import_csv(conn, csv.encode("utf-8"), mode="run")
    assert not report["errors"]
    assert stock_of(conn, rm["mehl"]) == 20000 and get_raw_material(conn, rm["mehl"])["stock_alert_g"] == 6000
    assert stock_of(conn, rm["wasser"]) is None and stock_of(conn, rm["salz"]) == 3000
    assert movements(conn, rm["mehl"])[0]["note"] == "CSV-Import"
    # leere Zelle beendet die Führung; fehlt die Spalte, bleibt der Bestand
    import_csv(conn, (head + f"{nums['mehl']};Weizenmehl 550;20;;6\r\n").encode("utf-8"), mode="run")
    assert stock_of(conn, rm["mehl"]) is None
    import_csv(conn, ("Nummer;Name;Toleranz\r\n" + f"{nums['salz']};Speisesalz;2\r\n").encode("utf-8"), mode="run")
    assert stock_of(conn, rm["salz"]) == 3000


# -- Verwiegen (B4, B5, B6) ----------------------------------------------------------------------

def test_weighing_consumes_stock(conn, recipes, rm, runner, hub):
    # Kuchen: Mehl 1 000 g, Ei 21 × 55 g + 5 g, Vanille nach Bedarf, Hefe 30 g (Sollhandzugabe)
    for key in ("mehl", "ei", "vanille", "hefe"):
        receipt(conn, rm[key], {"amount_kg": "10"})
    order = orders.create_order(conn, total(recipes["kuchen"], 2190))
    hub.put(1, 0)
    bid = batches.start_dough(conn, order["id"], st(), runner, today=TODAY)["id"]
    hub.put(1, 1005)
    batches.ack_weighed(conn, bid, st(), runner)
    batches.ack_units(conn, bid, st(), runner)
    hub.put(1, 1011)
    batches.ack_weighed(conn, bid, st(), runner)                    # Rest 6 g
    batches.ack_hand(conn, bid, st(), runner)                       # Vanille nach Bedarf: nichts
    batches.ack_hand(conn, bid, st(), runner)                       # Hefe: Soll 30 g
    assert stock_of(conn, rm["mehl"]) == 10000 - 1005
    assert stock_of(conn, rm["ei"]) == 10000 - (21 * 55 + 6)
    assert stock_of(conn, rm["vanille"]) == 10000
    assert stock_of(conn, rm["hefe"]) == 10000 - 30
    move = movements(conn, rm["mehl"])[0]
    assert move["kind"] == "consumption" and move["batch_no"] and move["station_id"] == 1


def test_untracked_and_skipped_are_not_booked(conn, recipes, rm, runner, hub):
    receipt(conn, rm["hefe"], {"amount_kg": "1"})
    order = orders.create_order(conn, total(recipes["kuchen"], 2190))
    hub.put(1, 0)
    bid = batches.start_dough(conn, order["id"], st(), runner, today=TODAY)["id"]
    hub.put(1, 1000)
    batches.ack_weighed(conn, bid, st(), runner)                    # Mehl ohne Führung
    assert stock_of(conn, rm["mehl"]) is None and movements(conn, rm["mehl"]) == []
    batches.select_item(conn, bid, st(position=4), runner)
    batches.skip_item(conn, bid, st(confirm=True, position=4), runner)
    assert stock_of(conn, rm["hefe"]) == 1000


def test_start_asks_when_stock_short_and_negative_allowed(conn, recipes, rm, runner, hub):
    receipt(conn, rm["mehl"], {"amount_kg": "0,5"})                 # Brot braucht 1 kg
    update_raw_material(conn, rm["wasser"], {"stock_alert_kg": "10"})
    receipt(conn, rm["wasser"], {"amount_kg": "10,5"})
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    overview = batches.order_stock(conn, order["id"])
    by_id = {i["raw_material_id"]: i for i in overview["items"]}
    assert by_id[rm["mehl"]]["stock_status"] == "short" and by_id[rm["mehl"]]["need_g"] == 1000
    assert by_id[rm["wasser"]]["stock_status"] == "alert"
    assert by_id[rm["salz"]]["stock_status"] is None
    hub.put(1, 0)
    with pytest.raises(ConflictError) as exc:
        batches.start_dough(conn, order["id"], st(), runner, today=TODAY)
    assert exc.value.code == "stock_short" and "Weizenmehl 550" in exc.value.message
    assert orders.get_order(conn, order["id"])["status"] == "open"  # Abbrechen: nichts gestartet
    bid = batches.start_dough(conn, order["id"], st(confirm_stock=True), runner, today=TODAY)["id"]
    hub.put(1, 1000)
    batches.ack_weighed(conn, bid, st(), runner)
    assert stock_of(conn, rm["mehl"]) == -500                       # negativ erlaubt (M03-14)
    assert batches.order_stock(conn, order["id"])["items"] == []    # gestarteter Teig zählt nicht mehr


def test_cancel_asks_and_reverses(conn, recipes, rm, runner, hub):
    receipt(conn, rm["mehl"], {"amount_kg": "5"})
    receipt(conn, rm["wasser"], {"amount_kg": "5"})
    for keep in (True, False):
        order = orders.create_order(conn, total(recipes["brot"], 1620))
        hub.put(1, 0)
        bid = batches.start_dough(conn, order["id"], st(), runner, today=TODAY)["id"]
        hub.put(1, 1000)
        batches.ack_weighed(conn, bid, st(), runner)
        hub.put(1, 1600)
        batches.ack_weighed(conn, bid, st(), runner)
        with pytest.raises(ConflictError) as exc:
            batches.cancel(conn, bid, st(confirm=True), runner)
        assert exc.value.code == "stock_question" and "2 Zutaten, 1,6 kg" in exc.value.message
        batches.cancel(conn, bid, st(confirm=True, stock_keep=keep), runner)
        hub.offset[1] = 0                                          # Waage für den nächsten Teig leer
    assert stock_of(conn, rm["mehl"]) == 5000 - 1000                 # erster Teig bleibt abgezogen
    assert stock_of(conn, rm["wasser"]) == 5000 - 600
    assert movements(conn, rm["mehl"])[0]["kind"] == "reversal"


def test_cancel_without_bookings_needs_no_question(conn, recipes, runner, hub):
    order = orders.create_order(conn, total(recipes["brot"], 1620))
    hub.put(1, 0)
    bid = batches.start_dough(conn, order["id"], st(), runner, today=TODAY)["id"]
    assert batches.cancel(conn, bid, st(confirm=True), runner)["status"] == "cancelled"


def test_migration_0008_columns(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(raw_material)")}
    assert {"stock_g", "stock_alert_g"} <= cols
    with pytest.raises(Exception):
        conn.execute("INSERT INTO stock_movement (raw_material_id, kind) VALUES (1, 'unknown')")


# -- Beleg-Foto zu „Zugang buchen“ (M03-37) -----------------------------------------------------------

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


@pytest.fixture
def photos(db_path, monkeypatch):
    monkeypatch.setenv("REZEPTBUCH_DB", str(db_path))
    from app.raw_materials.stock import photo_dir
    return photo_dir()


def test_receipt_returns_movement_and_photo_is_attached(conn, rm, photos):
    from app.raw_materials.stock import attach_photo, photo_path
    mid = receipt(conn, rm["mehl"], {"amount_kg": "25"})
    assert isinstance(mid, int)
    assert movements(conn, rm["mehl"])[0]["has_photo"] == 0
    assert attach_photo(conn, mid, JPEG) == {"movement_id": mid, "has_photo": True}
    path, mime = photo_path(conn, mid)
    assert path.read_bytes() == JPEG and mime == "image/jpeg" and path.parent == photos
    assert movements(conn, rm["mehl"])[0]["has_photo"] == 1
    assert not list(photos.glob("*.part"))


def test_photo_only_for_receipt_once_and_in_time(conn, rm, photos):
    from datetime import datetime, timedelta, timezone

    from app.errors import NotFoundError
    from app.raw_materials.stock import attach_photo, photo_path
    mid = receipt(conn, rm["mehl"], {"amount_kg": "5"})
    with pytest.raises(ValidationError):
        attach_photo(conn, mid, b"GIF89a" + b"\x00" * 20)               # kein Foto-Format
    with pytest.raises(ValidationError):
        attach_photo(conn, mid, b"")
    late = datetime.now(timezone.utc) + timedelta(minutes=61)
    with pytest.raises(ConflictError):
        attach_photo(conn, mid, JPEG, now=late)                          # später als 60 Minuten
    attach_photo(conn, mid, PNG)
    assert photo_path(conn, mid)[1] == "image/png"
    with pytest.raises(ConflictError):
        attach_photo(conn, mid, JPEG)                                    # nur ein Foto
    inventory(conn, rm["mehl"], {"stock_kg": "3"})
    inv_id = movements(conn, rm["mehl"])[0]["id"]
    with pytest.raises(ValidationError):
        attach_photo(conn, inv_id, JPEG)                                 # nur zu Zugängen
    with pytest.raises(NotFoundError):
        attach_photo(conn, 99999, JPEG)
    with pytest.raises(NotFoundError):
        photo_path(conn, inv_id)


def test_migration_0013_attachment_column(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(stock_movement)")}
    assert "attachment" in cols
