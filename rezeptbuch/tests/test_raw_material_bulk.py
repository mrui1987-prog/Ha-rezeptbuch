"""Rohstoffverwaltung R1 (Modul 03, M03-19 bis M03-23, docs/rohstoffverwaltung.md): Filter, Sammelaktionen,
Verlauf aller Rohstoffe und Quelle der Schnellerfassung."""

import pytest

from app.errors import ConflictError, ValidationError
from app.raw_materials import bulk, service, stock

from conftest import add_item, add_recipe


def mk(conn, name, **extra):
    data = {"name": name, "tolerance_unit": "g", "tolerance": "20"}
    data.update(extra)
    return service.create_raw_material(conn, data)["id"]


def ids(rows):
    return [r["id"] for r in rows]


@pytest.fixture
def rms(conn):
    a = mk(conn, "Weizenmehl", type="flour", stock_alert_kg="10")
    b = mk(conn, "Zucker", price_per_kg="1,20")
    c = mk(conn, "Salz")
    stock.receipt(conn, a, {"amount_kg": "8"})          # am Meldewert vorbei → alert
    stock.receipt(conn, b, {"amount_kg": "5"})
    stock.inventory(conn, b, {"stock_kg": "-1"})         # im Minus
    return a, b, c


# -- Filter (M03-22) -------------------------------------------------------------

def test_filters_status_type_price(conn, rms):
    a, b, c = rms
    service.archive_raw_material(conn, c)
    assert ids(service.list_raw_materials(conn, status="active")) == [a, b]
    assert ids(service.list_raw_materials(conn, status="archived")) == [c]
    assert ids(service.list_raw_materials(conn, status="all")) == [a, b, c]
    assert ids(service.list_raw_materials(conn, status="all", type_="flour")) == [a]
    assert ids(service.list_raw_materials(conn, status="all", no_price=True)) == [a, c]
    with pytest.raises(ValidationError):
        service.list_raw_materials(conn, status="x")


def test_filters_stock(conn, rms):
    a, b, c = rms
    assert ids(service.list_raw_materials(conn, stock="below_alert")) == [a]
    assert ids(service.list_raw_materials(conn, stock="negative")) == [b]
    assert ids(service.list_raw_materials(conn, stock="none")) == [c]
    assert ids(service.list_raw_materials(conn, stock="attention")) == [a, b]


def test_filter_unused_only_current_versions_of_active_recipes(conn, rms):
    a, b, c = rms
    rid, vid = add_recipe(conn, 1, "Brot")
    add_item(conn, vid, 1, raw_material_id=a)
    rid2, vid2 = add_recipe(conn, 2, "Alt")
    add_item(conn, vid2, 1, raw_material_id=b)
    conn.execute("UPDATE recipe SET archived = 1 WHERE id = ?", (rid2,))
    assert ids(service.list_raw_materials(conn, unused=True)) == [b, c]   # K03-34


def test_filter_ids_for_export(conn, rms):
    a, b, c = rms
    assert ids(service.list_raw_materials(conn, ids=[c, a])) == [a, c]
    assert service.list_raw_materials(conn, ids=[]) == []


# -- Sammelaktionen (M03-21) ---------------------------------------------------------

def test_preview_changes_nothing_and_confirm_required(conn, rms):
    a, b, c = rms
    res = bulk.run(conn, {"action": "type", "ids": [a, b], "value": {"type": "flour"}, "preview": True})
    assert res["changed"] == 1 and res["unchanged"] == 1
    assert service.get_raw_material(conn, b)["type"] == "standard"
    with pytest.raises(ConflictError):
        bulk.run(conn, {"action": "type", "ids": [b], "value": {"type": "flour"}})
    res = bulk.run(conn, {"action": "type", "ids": [b], "value": {"type": "flour"}, "confirm": True})
    assert res["changed"] == 1 and service.get_raw_material(conn, b)["type"] == "flour"


def test_type_change_names_affected_recipes(conn, rms):
    a, b, c = rms
    rid, vid = add_recipe(conn, 1, "Brot")
    add_item(conn, vid, 1, raw_material_id=b)
    res = bulk.run(conn, {"action": "type", "ids": [b], "value": {"type": "flour"}, "preview": True})
    assert "betrifft 1 Rezept" in res["items"][0]["detail"]


def test_archive_with_stock_zero_list(conn, rms):
    """K03-36: „auf Null“ nur für die angehakten Rohstoffe."""
    a, b, c = rms
    res = bulk.run(conn, {"action": "archive", "ids": [a, b, c], "confirm": True, "stock_zero_ids": [a]})
    assert res["changed"] == 3
    assert service.get_raw_material(conn, a)["stock_g"] == 0
    assert service.get_raw_material(conn, b)["stock_g"] == -1000
    assert all(service.get_raw_material(conn, i)["archived"] for i in (a, b, c))
    again = bulk.run(conn, {"action": "archive", "ids": [a], "preview": True})
    assert again["unchanged"] == 1


def test_restore_skips_name_conflict(conn, rms):
    a, b, c = rms
    service.archive_raw_material(conn, c)
    mk(conn, "Salz")                                   # neuer aktiver Rohstoff mit demselben Namen
    res = bulk.run(conn, {"action": "restore", "ids": [c, a], "confirm": True})
    by = {i["raw_material_id"]: i for i in res["items"]}
    assert by[c]["status"] == "skipped" and "denselben Namen" in by[c]["detail"]
    assert by[a]["status"] == "unchanged"


def test_tolerance_and_alert(conn, rms):
    a, b, c = rms
    res = bulk.run(conn, {"action": "tolerance", "ids": [a, b], "confirm": True,
                          "value": {"tolerance": "2,5", "tolerance_unit": "percent"}})
    assert res["changed"] == 2 and "20 g → 2,5 %" in res["items"][0]["detail"]
    assert service.get_raw_material(conn, b)["tolerance"] == 2.5
    res = bulk.run(conn, {"action": "tolerance", "ids": [a], "preview": True,
                          "value": {"tolerance": "abc", "tolerance_unit": "g"}})
    assert res["skipped"] == 1
    res = bulk.run(conn, {"action": "alert", "ids": [a, c], "confirm": True, "value": {"value": ""}})
    assert service.get_raw_material(conn, a)["stock_alert_g"] is None
    assert res["items"][1]["status"] == "unchanged"


def test_stock_end_and_zero(conn, rms):
    a, b, c = rms
    res = bulk.run(conn, {"action": "stock", "ids": [a, c], "confirm": True, "value": {"mode": "zero"}})
    assert res["changed"] == 1 and res["unchanged"] == 1
    assert service.get_raw_material(conn, a)["stock_g"] == 0
    moves = stock.movements(conn, a)
    assert moves[0]["kind"] == "inventory" and moves[0]["note"] == "Sammelaktion"
    bulk.run(conn, {"action": "stock", "ids": [a, b], "confirm": True, "value": {"mode": "end"}})
    assert service.get_raw_material(conn, b)["stock_g"] is None


def test_active_source_bulk(conn, rms):
    from app.dealers import service as dealers
    a, b, c = rms
    d = dealers.create_dealer(conn, {"name": "BÄKO"})["id"]
    res = bulk.run(conn, {"action": "active_source", "ids": [a, b], "confirm": True, "value": {"dealer_id": d}})
    assert res["changed"] == 2
    assert service.get_raw_material(conn, b)["active_source"]["dealer_name"] == "BÄKO"
    assert ids(service.list_raw_materials(conn, dealer_id=d)) == [a, b]
    assert ids(service.list_raw_materials(conn, no_source=True)) == [c]


def test_input_checks(conn, rms):
    a, b, c = rms
    for data in ({"action": "x", "ids": [a]}, {"action": "archive", "ids": []},
                 {"action": "type", "ids": [a], "value": {"type": "x"}},
                 {"action": "stock", "ids": [a], "value": {}},
                 {"action": "archive", "ids": list(range(1, 1003))}):
        with pytest.raises(ValidationError):
            bulk.run(conn, dict(data, preview=True))
    res = bulk.run(conn, {"action": "archive", "ids": [9999], "preview": True})
    assert res["skipped"] == 1


# -- Verlauf aller Rohstoffe und Schnellerfassung (6.1, 6.3) ------------------------

def test_movements_all_and_quick_entry_source(conn, rms):
    a, b, c = rms
    stock.receipt(conn, c, {"amount_kg": "2", "source": "quick_entry"})
    stock.inventory(conn, c, {"stock_kg": "1,5", "source": "quick_entry"})
    moves = stock.movements_all(conn)
    assert moves[0]["name"] == "Salz" and moves[0]["source"] == "quick_entry" and moves[0]["kind"] == "inventory"
    assert [m["kind"] for m in stock.movements_all(conn, raw_material_id=c)] == ["inventory", "receipt"]
    assert all(m["kind"] == "receipt" for m in stock.movements_all(conn, kind="receipt"))
    assert stock.movements_all(conn, date_from="2000-01-01", date_to="2000-01-02") == []
    assert len(stock.movements_all(conn, date_from="2000-01-01")) == len(moves)
    with pytest.raises(ValidationError):
        stock.movements_all(conn, date_from="1.1.2026")
    with pytest.raises(ValidationError):
        stock.movements_all(conn, kind="x")
