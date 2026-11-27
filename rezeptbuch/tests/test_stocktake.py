"""Inventur, Teil I1 (docs/strichcode.md 5): Fachlogik ohne HTTP."""

import pytest

from app.db import transaction
from app.errors import ConflictError, ValidationError
from app.raw_materials import stock
from app.stocktake import service as st

from conftest import add_raw_material


def tracked(conn, number, name, grams, *, price=None, unit=(25000, "Sack"), type_="standard", loc1=None, loc2=None):
    tol = 0 if type_ == "aid" else 20
    rid = add_raw_material(conn, number, name, type_=type_, tolerance_value=tol,
                           unit_size_g=unit[0] if unit else None, unit_label=unit[1] if unit else None)
    conn.execute("UPDATE raw_material SET stock_g = ?, price_cents_per_kg = ?, location1_id = ?, location2_id = ? "
                 "WHERE id = ?", (grams, price, loc1, loc2, rid))
    return rid


def location(conn, name):
    return conn.execute("INSERT INTO storage_location (name) VALUES (?)", (name,)).lastrowid


def book(conn, rid, kind, delta):
    with transaction(conn):
        before = conn.execute("SELECT stock_g FROM raw_material WHERE id = ?", (rid,)).fetchone()[0]
        stock._book(conn, rid, kind, before, before + delta, source="test")


def stock_of(conn, rid):
    return conn.execute("SELECT stock_g FROM raw_material WHERE id = ?", (rid,)).fetchone()[0]


def test_only_one_open_and_scope(conn):
    a = tracked(conn, 1, "Weizenmehl 550", 50000)
    b = add_raw_material(conn, 2, "Salz")                      # ohne Bestandsführung
    s = st.create(conn, {"name": "Jahresinventur 2026", "stichtag": "2026-12-31"})
    assert s["status"] == "open" and s["scope"] == "stocked"
    with pytest.raises(ConflictError):
        st.create(conn, {"name": "Noch eine"})
    ids = [it["id"] for it in st.open_view(conn)["items"]]
    assert ids == [a]
    st.cancel(conn, s["id"])
    s2 = st.create(conn, {"name": "Alle", "scope": "active"})
    assert [it["id"] for it in st.open_view(conn)["items"]] == [a, b]
    assert s2["id"] != s["id"]
    with pytest.raises(ValidationError):
        st.create(conn, {"name": ""})


def test_blind_view_has_no_book_stock_or_price(conn):
    tracked(conn, 1, "Weizenmehl 550", 50000, price=60)
    st.create(conn, {"name": "Inventur"})
    item = st.open_view(conn)["items"][0]
    assert "stock_g" not in item and "price_cents_per_kg" not in item and "book_at_count" not in str(item)


def test_counts_add_up_over_locations_and_done_rule(conn):
    l1, l2 = location(conn, "Mehllager"), location(conn, "Backstube")
    rid = tracked(conn, 1, "Weizenmehl 550", 100000, loc1=l1, loc2=l2)
    st.create(conn, {"name": "Inventur"})
    r = st.add_count(conn, {"raw_material_id": rid, "location_id": l1, "packs": 3, "rest_kg": "12,5"})
    assert r["item"]["counted"] == 87500 and r["item"]["done"] is False and r["open"] == 1
    r = st.add_count(conn, {"raw_material_id": rid, "location_id": l2, "packs": 1, "source": "scan"})
    assert r["item"]["counted"] == 112500 and r["item"]["done"] is True and r["open"] == 0
    # einzeln löschbar, solange offen
    r = st.delete_count(conn, r["item"]["counts"][-1]["id"])
    assert r["item"]["counted"] == 87500 and r["item"]["done"] is False


def test_count_time_with_weighing_in_between(conn):
    """Zählzeitpunkt (5.4): Neuer Bestand = gezählt + Bewegungen seit der Zählung."""
    rid = tracked(conn, 1, "Weizenmehl 550", 100000, price=60)
    s = st.create(conn, {"name": "Inventur", "stichtag": "2026-12-31"})
    st.add_count(conn, {"raw_material_id": rid, "packs": 3})           # 75 kg gezählt, Buch 100 kg
    book(conn, rid, "consumption", -10000)                             # danach verwogen
    book(conn, rid, "receipt", 25000)                                  # und geliefert
    pv = st.detail(conn, s["id"])
    ln = pv["lines"][0]
    assert ln["counted"] == 75000 and ln["since_count"] == 15000 and ln["book_before"] == 115000
    assert ln["stock_after"] == 90000 and ln["diff"] == -25000
    assert ln["value_cents"] == 4500                                   # 75 kg × 0,60 €
    res = st.close(conn, s["id"], {"confirm": True})
    assert res["stocktake"]["status"] == "closed" and stock_of(conn, rid) == 90000
    m = conn.execute("SELECT kind, note, source, stocktake_id, delta_g FROM stock_movement ORDER BY id DESC").fetchone()
    assert tuple(m) == ("inventory", "Inventur 31.12.2026", "stocktake", s["id"], -25000)


def test_uncounted_unchanged_or_zero(conn):
    a = tracked(conn, 1, "Weizenmehl 550", 50000, price=100)
    b = tracked(conn, 2, "Roggenmehl", 30000, price=100)
    c = tracked(conn, 3, "Dinkelmehl", 20000, price=100)
    s = st.create(conn, {"name": "Inventur"})
    st.add_count(conn, {"raw_material_id": a, "amount_kg": "40"})
    pv = st.detail(conn, s["id"], [c])
    by = {ln["raw_material_id"]: ln for ln in pv["lines"]}
    assert by[b]["action"] == "unchanged" and by[c]["action"] == "zero"
    st.close(conn, s["id"], {"confirm": True, "zero_ids": [c]})
    assert (stock_of(conn, a), stock_of(conn, b), stock_of(conn, c)) == (40000, 30000, 0)
    lines = {ln["raw_material_id"]: ln for ln in st.detail(conn, s["id"])["lines"]}
    assert lines[b]["stock_movement_id"] is None and lines[c]["stock_movement_id"] is not None
    # Wert: gezählt 40 kg, ungezählt unverändert mit Buchbestand 30 kg, auf 0 → 0
    assert (lines[a]["value_cents"], lines[b]["value_cents"], lines[c]["value_cents"]) == (4000, 3000, 0)
    assert conn.execute("SELECT total_value_cents FROM stocktake").fetchone()[0] == 7000


def test_price_is_frozen_and_missing_price(conn):
    a = tracked(conn, 1, "Weizenmehl 550", 50000, price=60)
    b = tracked(conn, 2, "Mohn", 1000, price=None)
    s = st.create(conn, {"name": "Inventur"})
    st.add_count(conn, {"raw_material_id": a, "amount_kg": "50"})
    st.add_count(conn, {"raw_material_id": b, "amount_kg": "1"})
    res = st.close(conn, s["id"], {"confirm": True})
    assert res["totals"]["missing_price_count"] == 1 and res["totals"]["total_cents"] == 3000
    conn.execute("UPDATE raw_material SET price_cents_per_kg = 999 WHERE id = ?", (a,))
    again = st.detail(conn, s["id"])
    assert again["lines"][0]["price_cents"] == 60 and again["totals"]["total_cents"] == 3000
    # abgeschlossen: unveränderlich
    with pytest.raises(ConflictError):
        st.close(conn, s["id"], {"confirm": True})
    with pytest.raises(ConflictError):
        st.add_count(conn, {"raw_material_id": a, "amount_kg": "1"})


def test_aid_counted_in_units_with_own_subtotal(conn):
    a = tracked(conn, 1, "Weizenmehl 550", 25000, price=60)
    k = tracked(conn, 2, "Tortenkarton", 10000, price=150, unit=(1000, "Karton"), type_="aid")
    s = st.create(conn, {"name": "Inventur"})
    st.add_count(conn, {"raw_material_id": a, "packs": 1})
    st.add_count(conn, {"raw_material_id": k, "packs": 12})
    res = st.close(conn, s["id"], {"confirm": True})
    assert stock_of(conn, k) == 12000
    assert res["totals"]["aids_cents"] == 1800 and res["totals"]["materials_cents"] == 1500


def test_location_done_and_tracking_started_by_count(conn):
    l1 = location(conn, "Kühlhaus")
    a = tracked(conn, 1, "Butter", 5000, loc1=l1)
    b = tracked(conn, 2, "Sahne", 3000, loc1=l1)
    c = add_raw_material(conn, 3, "Quark")                     # ohne Führung, im Umfang „alle aktiven“
    conn.execute("UPDATE raw_material SET location1_id = ? WHERE id = ?", (l1, c))
    s = st.create(conn, {"name": "Inventur", "scope": "active"})
    st.add_count(conn, {"raw_material_id": a, "location_id": l1, "amount_kg": "4"})
    r = st.location_done(conn, {"location_id": l1, "raw_material_ids": [a, b]})
    assert r["zeroed"] == 1 and r["open"] == 1                 # a war schon gezählt, c bleibt offen
    st.add_count(conn, {"raw_material_id": c, "location_id": l1, "amount_kg": "2"})
    st.close(conn, s["id"], {"confirm": True})
    assert (stock_of(conn, a), stock_of(conn, b), stock_of(conn, c)) == (4000, 0, 2000)


def test_archived_not_countable_and_countlist(conn):
    l1 = location(conn, "Mehllager")
    a = tracked(conn, 1, "Weizenmehl 550", 5000, loc1=l1)
    b = tracked(conn, 2, "Zucker", 5000)
    conn.execute("UPDATE raw_material SET archived = 1 WHERE id = ?", (b,))
    s = st.create(conn, {"name": "Inventur"})
    with pytest.raises(ConflictError):
        st.add_count(conn, {"raw_material_id": b, "amount_kg": "1"})
    cl = st.countlist(conn, s["id"])
    assert [g["location"] for g in cl["groups"]] == ["Mehllager"]
    assert cl["groups"][0]["items"][0]["pack"] == "Sack = 25 kg" and "price" not in str(cl["groups"])
    assert a


def test_export_xlsx(conn):
    from openpyxl import load_workbook
    import io
    a = tracked(conn, 1, "Weizenmehl 550", 50000, price=60)
    b = tracked(conn, 2, "Mohn", 1000)
    k = tracked(conn, 3, "Tortenkarton", 10000, price=150, unit=(1000, "Karton"), type_="aid")
    s = st.create(conn, {"name": "Jahresinventur 2026", "stichtag": "2026-12-31"})
    with pytest.raises(ConflictError):
        st.export_xlsx(conn, s["id"])
    for rid, amount in ((a, "50"), (b, "1"), (k, "4")):
        st.add_count(conn, {"raw_material_id": rid, "amount_kg": amount})
    st.close(conn, s["id"], {"confirm": True})
    data, name = st.export_xlsx(conn, s["id"])
    assert name == "Inventur_2026-12-31_Jahresinventur_2026.xlsx"
    wb = load_workbook(io.BytesIO(data))
    assert wb.sheetnames == ["Inventur", "ohne Preis"]
    texts = [c for row in wb["Inventur"].iter_rows(values_only=True) for c in row if c is not None]
    assert "Zwischensumme Rohstoffe" in texts and "Zwischensumme Hilfs- und Betriebsstoffe" in texts
    assert 30.0 in texts and 6.0 in texts and 36.0 in texts
    assert any(isinstance(t, str) and t.startswith("Gesamtsumme (ohne 1 Position") for t in texts)
    missing = [row for row in wb["ohne Preis"].iter_rows(values_only=True)]
    assert missing[2][1] == "Mohn"
