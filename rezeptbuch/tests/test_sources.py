"""Tests: Händler, Bezugsquellen, Preis je Bezugsquelle, Massenpflege (Modul 04 Teil C1)."""

import pytest

from app.dealers import service as dealers
from app.errors import ConflictError, ValidationError
from app.raw_materials import service, sources


def rm(conn, number=1, name="Weizenmehl 550", price=None):
    data = {"number": number, "name": name, "tolerance": 20, "tolerance_unit": "g"}
    if price is not None:
        data["price_per_kg"] = price
    return service.create_raw_material(conn, data)["id"]


def dealer(conn, name="BÄKO"):
    return dealers.create_dealer(conn, {"name": name})["id"]


def price(conn, rm_id):
    return conn.execute("SELECT price_cents_per_kg, price_changed_at FROM raw_material WHERE id = ?",
                        (rm_id,)).fetchone()


# -- Händler -----------------------------------------------------------------------

def test_dealer_name_unique_and_rules(conn):
    dealer(conn, "BÄKO")
    with pytest.raises(ConflictError) as e:
        dealer(conn, "  bäko ")
    assert e.value.code == "name_taken"
    with pytest.raises(ValidationError):
        dealer(conn, "")
    with pytest.raises(ValidationError) as e:
        dealer(conn, "=HYPERLINK()")
    assert e.value.code == "formula_start"


def test_dealer_rename_archive_delete(conn):
    d = dealer(conn, "Metro")
    other = dealer(conn, "BÄKO")
    with pytest.raises(ConflictError):
        dealers.rename_dealer(conn, d, {"name": "bäko"})
    assert dealers.rename_dealer(conn, d, {"name": "Metro Cash"})["name"] == "Metro Cash"
    r = rm(conn)
    sources.add_source(conn, r, {"dealer_id": other})
    with pytest.raises(ConflictError) as e:
        dealers.delete_dealer(conn, other)
    assert e.value.code == "in_use"
    dealers.set_archived(conn, other, True)
    assert [x["name"] for x in dealers.list_dealers(conn)] == ["Metro Cash"]
    assert len(dealers.list_dealers(conn, include_archived=True)) == 2
    # archivierter Händler nicht für neue Bezugsquellen (R04-10), bestehende bleibt
    r2 = rm(conn, 2, "Roggenmehl")
    with pytest.raises(ConflictError) as e:
        sources.add_source(conn, r2, {"dealer_id": other})
    assert e.value.code == "dealer_archived"
    assert sources.list_sources(conn, r)[0]["dealer_archived"] is True
    dealers.set_archived(conn, other, False)
    dealers.delete_dealer(conn, d)


# -- Bezugsquellen und Preis -----------------------------------------------------------

def test_first_source_active_and_takes_price(conn):
    r = rm(conn, price="0,60")
    before = price(conn, r)
    d = dealer(conn)
    answer = sources.add_source(conn, r, {"dealer_id": d, "article_no": "202656", "grams_per_unit": "1030",
                                          "unit_code": "l", "commodity_group": "101"})
    src = answer["sources"][0]
    assert src["is_active"] and src["price_cents_per_kg"] == 60
    assert src["price_changed_at"] == before["price_changed_at"]          # K04-1: Datum bleibt
    assert (src["grams_per_unit"], src["unit_code"], src["commodity_group"]) == (1030, "L", "101")
    assert tuple(price(conn, r)) == tuple(before)
    item = service.get_raw_material(conn, r)
    assert item["active_source"]["dealer_name"] == "BÄKO" and item["active_source"]["article_no"] == "202656"


def test_second_source_empty_price_and_activate_mirrors(conn):
    r = rm(conn, price="0,60")
    d1, d2 = dealer(conn, "BÄKO"), dealer(conn, "Metro")
    sources.add_source(conn, r, {"dealer_id": d1})
    listed = sources.add_source(conn, r, {"dealer_id": d2, "price_per_kg": "0,55"})["sources"]
    metro = next(s for s in listed if s["dealer_id"] == d2)
    assert not metro["is_active"] and metro["price_cents_per_kg"] == 55
    assert price(conn, r)[0] == 60
    sources.activate_source(conn, r, metro["id"])
    assert price(conn, r)[0] == 55
    # Preis an der aktiven ändern → Rohstoffpreis folgt
    sources.update_source(conn, r, metro["id"], {"price_per_kg": "0,57"})
    assert price(conn, r)[0] == 57
    # Preis an der nicht aktiven ändern → Rohstoffpreis bleibt
    baeko = next(s for s in sources.list_sources(conn, r) if s["dealer_id"] == d1)
    sources.update_source(conn, r, baeko["id"], {"price_per_kg": "0,10"})
    assert price(conn, r)[0] == 57


def test_same_price_keeps_changed_at(conn):
    r = rm(conn, price="1,00")
    d1, d2 = dealer(conn, "A"), dealer(conn, "B")
    sources.add_source(conn, r, {"dealer_id": d1})
    conn.execute("UPDATE raw_material SET price_changed_at = '2020-01-01T00:00:00Z' WHERE id = ?", (r,))
    sid = sources.add_source(conn, r, {"dealer_id": d2, "price_per_kg": "1,00"})["sources"]
    sid = next(s["id"] for s in sid if s["dealer_id"] == d2)
    sources.activate_source(conn, r, sid)
    assert price(conn, r)[1] == "2020-01-01T00:00:00Z"                  # K04-2


def test_dealer_once_per_raw_material(conn):
    r = rm(conn)
    d = dealer(conn)
    sources.add_source(conn, r, {"dealer_id": d})
    with pytest.raises(ConflictError) as e:
        sources.add_source(conn, r, {"dealer_id": d})
    assert e.value.code == "dealer_taken"


def test_delete_rules(conn):
    r = rm(conn, price="2,00")
    d1, d2 = dealer(conn, "A"), dealer(conn, "B")
    sources.add_source(conn, r, {"dealer_id": d1})
    listed = sources.add_source(conn, r, {"dealer_id": d2})["sources"]
    active = next(s for s in listed if s["is_active"])
    other = next(s for s in listed if not s["is_active"])
    with pytest.raises(ConflictError) as e:
        sources.delete_source(conn, r, active["id"])
    assert e.value.code == "active_source"
    sources.delete_source(conn, r, other["id"])
    sources.delete_source(conn, r, active["id"])                       # letzte: erlaubt
    assert price(conn, r)[0] == 200                                     # Preis bleibt stehen
    assert service.get_raw_material(conn, r)["active_source"] is None
    service.update_raw_material(conn, r, {"price_per_kg": "2,10"})     # wieder direkt änderbar
    assert price(conn, r)[0] == 210


def test_price_on_raw_material_goes_to_active_source(conn):
    r = rm(conn, price="1,00")
    d = dealer(conn)
    sid = sources.add_source(conn, r, {"dealer_id": d})["sources"][0]["id"]
    answer = service.update_raw_material(conn, r, {"price_per_kg": "1,25"})
    assert answer["price_cents_per_kg"] == 125
    assert any(w["code"] == "price_on_source" for w in answer["warnings"])
    assert sources.list_sources(conn, r)[0]["price_cents_per_kg"] == 125
    assert sources.list_sources(conn, r)[0]["id"] == sid


def test_source_input_checked(conn):
    r = rm(conn)
    d = dealer(conn)
    with pytest.raises(ValidationError):
        sources.add_source(conn, r, {"dealer_id": d, "grams_per_unit": "0"})
    with pytest.raises(ValidationError):
        sources.add_source(conn, r, {"dealer_id": d, "price_per_kg": "-1"})
    with pytest.raises(ValidationError):
        sources.add_source(conn, r, {"dealer_id": d, "article_no": "@123"})
    with pytest.raises(ValidationError):
        sources.add_source(conn, r, {"dealer_id": "BÄKO"})
    sid = sources.add_source(conn, r, {"dealer_id": d})["sources"][0]["id"]
    with pytest.raises(ValidationError) as e:
        sources.update_source(conn, r, sid, {"dealer_id": d + 1})
    assert e.value.code == "dealer_fixed"
    answer = sources.update_source(conn, r, sid, {"price_per_kg": "1,234"})
    assert answer["warnings"][0]["code"] == "price_rounded"


def test_change_log_written(conn):
    r = rm(conn)
    d = dealer(conn)
    sources.add_source(conn, r, {"dealer_id": d})
    entities = {row[0] for row in conn.execute("SELECT entity FROM change_log")}
    assert {"dealer", "raw_material_source", "raw_material"} <= entities


# -- Massenpflege ---------------------------------------------------------------------

def test_bulk_preview_and_apply(conn):
    a = rm(conn, 1, "A", price="1,00")
    b = rm(conn, 2, "B", price="2,00")
    c = rm(conn, 3, "C")
    baeko, metro = dealer(conn, "BÄKO"), dealer(conn, "Metro")
    sources.add_source(conn, b, {"dealer_id": metro})
    sources.add_source(conn, b, {"dealer_id": baeko, "price_per_kg": "1,80"})
    preview = sources.bulk_active_source(conn, {"raw_material_ids": [a, b, c], "dealer_id": baeko, "dry_run": True})
    assert preview["dry_run"] is True
    by = {i["raw_material_id"]: i for i in preview["items"]}
    assert by[a]["action"] == "created" and not by[a]["price_changes"]   # erste Bezugsquelle übernimmt Preis
    assert by[b]["action"] == "activated" and by[b]["new_price_cents_per_kg"] == 180
    assert by[b]["old_dealer"] == "Metro"
    assert by[c]["action"] == "created"
    # Vorschau ändert nichts
    assert sources.list_sources(conn, a) == []
    assert price(conn, b)[0] == 200
    done = sources.bulk_active_source(conn, {"raw_material_ids": [a, b, c], "dealer_id": baeko})
    assert done["changed"] == 3 and done["price_changes"] == 1
    assert price(conn, b)[0] == 180
    again = sources.bulk_active_source(conn, {"raw_material_ids": [a], "dealer_id": baeko})
    assert again["items"][0]["action"] == "unchanged"


def test_bulk_input_checked(conn):
    with pytest.raises(ValidationError):
        sources.bulk_active_source(conn, {"raw_material_ids": [], "dealer_id": 1})
    r = rm(conn)
    with pytest.raises(ValidationError):
        sources.bulk_active_source(conn, {"raw_material_ids": [r], "dealer_id": 999})


def test_restore_refused_on_same_datenlink_id(conn):
    a = rm(conn, 1, "A")
    b = rm(conn, 2, "B")
    conn.execute("UPDATE raw_material SET source = 'datenlink', datenlink_id = 'DL-1', archived = 1 WHERE id = ?",
                 (a,))
    conn.execute("UPDATE raw_material SET source = 'datenlink', datenlink_id = 'DL-1' WHERE id = ?", (b,))
    with pytest.raises(ConflictError) as e:
        service.restore_raw_material(conn, a)
    assert e.value.code == "datenlink_taken"


def test_delete_raw_material_with_sources(conn):
    r = rm(conn)
    d = dealer(conn)
    sources.add_source(conn, r, {"dealer_id": d})
    service.delete_raw_material(conn, r)
    assert conn.execute("SELECT COUNT(*) FROM raw_material_source").fetchone()[0] == 0
    dealers.delete_dealer(conn, d)


# -- CSV (K04-3, M04-14) -------------------------------------------------------------

def test_csv_export_reimport_with_source(conn):
    from app.imports import import_raw_materials_csv
    from app.raw_materials import build_csv
    r = rm(conn, 1, "Mehl", price="0,60")
    d = dealer(conn)
    sources.add_source(conn, r, {"dealer_id": d, "article_no": "202656"})
    data = build_csv(service.list_raw_materials(conn, include_archived=True))
    text = data.decode("utf-8-sig").split("\r\n")
    assert text[0].endswith("Händler (aktiv);Artikelnummer (aktiv);datenlink-ID")
    assert text[1].endswith(";BÄKO;202656;") and ";eigen;" in text[1]
    report = import_raw_materials_csv(conn, data, mode="run", confirm_overwrite=False)
    assert report["imported"] and report["counts"]["unchanged"] == 1
    # geänderter Preis geht an die aktive Bezugsquelle, Hinweis im Bericht
    changed = data.decode("utf-8-sig").replace(";0,60;", ";0,65;").encode("utf-8")
    report = import_raw_materials_csv(conn, changed, mode="run", confirm_overwrite=True)
    assert report["imported"]
    assert sources.list_sources(conn, r)[0]["price_cents_per_kg"] == 65
    assert price(conn, r)[0] == 65
    assert any("Bezugsquelle „BÄKO“" in h["message"] for h in report["hints"])
