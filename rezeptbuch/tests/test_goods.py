"""Handelsware und Pfand, Teil H1 (docs/handelsware.md, K03-85 bis K03-93) – Dienst-Tests ohne Webserver."""

import pytest

from app.errors import ConflictError, ValidationError
import io

from openpyxl import Workbook

from app.raw_materials import goods, sales_import, service as rms, stock
from app.stocktake import service as stocktake
from app.readers import client as reader
from app.receiving import service as rec


@pytest.fixture(autouse=True)
def _db_env(db_path, monkeypatch):
    monkeypatch.setenv("REZEPTBUCH_DB", str(db_path))


def _answer(kind="auftragsbestaetigung", no="AB1", positions=None):
    return {"status": "ok", "addon_version": "0.1.0", "daten": {
        "belegart": kind, "haendler": "BÄKO Saar-Pfalz eG", "belegnummer": no, "belegdatum": "2026-11-20",
        "lieferdatum_voraussichtlich": "2026-11-23", "summen": {"netto_cent": 100},
        "positionen": positions or []}}


COLA = {"nr": 1, "artikelnummer": "500100", "bezeichnung": "Coca-Cola 0,33 l", "menge_tausendstel": 2000,
        "mengeneinheit": "KT", "gebinde_text": "24 ST à 0,33 L", "warengruppe": "1001", "bestellartikel": False,
        "preis_zehntausendstel_euro": 120000, "preiseinheit": "EIN", "netto_cent": 2400, "mwst_prozent": 19}
PFAND = {"nr": 2, "artikelnummer": "999001", "bezeichnung": "Pfand Kiste", "menge_tausendstel": 2000,
         "mengeneinheit": "ST", "gebinde_text": None, "warengruppe": "1405", "bestellartikel": False,
         "preis_zehntausendstel_euro": 15000, "preiseinheit": "EIN", "netto_cent": 300, "mwst_prozent": 19}


def _upload(conn, monkeypatch, answer):
    monkeypatch.setattr(reader, "read", lambda r, pdf, name: answer)
    return rec.upload(conn, b"%PDF-1", "a.pdf")


def _goods(conn, name="Cola", **extra):
    return rms.create_raw_material(conn, dict({"name": name, "type": "goods"}, **extra))


def test_goods_basics(conn):
    g = _goods(conn, is_deposit=False, register_no=1101)
    assert g["type"] == "goods" and g["unit_size_g"] == 1000 and g["unit_label"] == "Stück"
    assert g["stock_g"] == 0 and g["register_no"] == 1101 and g["register_hint"] is None
    p = _goods(conn, "Pfand Kiste", is_deposit=True)
    assert p["is_deposit"] and p["register_hint"] == "ohne Kassenartikel, nur Inventur"
    with pytest.raises(ConflictError):
        _goods(conn, "Fanta", register_no=1101)            # Kassennummer aktiv eindeutig
    m = rms.create_raw_material(conn, {"name": "Mehl", "type": "standard", "tolerance": "5", "is_deposit": True,
                                       "register_no": 5})
    assert not m["is_deposit"] and m["register_no"] is None    # nur bei Handelsware


def test_goods_never_in_recipe(conn):
    from app.recipes import service as recipes
    g = _goods(conn)
    with pytest.raises(ValidationError) as e:
        recipes.create_recipe(conn, {"name": "Test", "items": [{"item_type": "raw_material",
                                                                  "raw_material_id": g["id"], "amount_g": 100}]})
    assert "Handelsware" in str(e.value)


def test_same_name_as_raw_material_allowed(conn):
    rms.create_raw_material(conn, {"name": "H-Milch", "type": "standard", "tolerance": "5"})
    assert _goods(conn, "H-Milch")["type"] == "goods"
    with pytest.raises(ConflictError):
        _goods(conn, "H-Milch")


def test_receiving_goods_new_and_book(conn, monkeypatch):
    pre = _upload(conn, monkeypatch, _answer(positions=[COLA, PFAND]))
    cola, pfand = pre["lines"]
    assert cola["target"] == "unknown" and cola["suggest_goods"] and not cola["deposit_hint"]
    assert cola["pieces_hint"] == 24
    assert pfand["deposit_hint"] and pfand["pieces_hint"] == 1
    doc = rec.commit(conn, {"token": pre["token"], "decisions": {
        "1": {"action": "goods_new", "name": "Cola 0,33", "pieces_per_unit": 24},
        "2": {"action": "goods_new", "name": "Pfand Kiste"}}})
    rows = {r["name"]: r for r in rms.list_raw_materials(conn, type_="goods")}
    assert rows["Pfand Kiste"]["is_deposit"] and not rows["Cola 0,33"]["is_deposit"]
    lines = rec.get_delivery(conn, doc["id"])["lines"]
    res = rec.book(conn, doc["id"], {"lines": [{"id": l["id"], "qty_milli": l["qty_milli"]} for l in lines]})
    assert res["status"] == "booked"
    rows = {r["name"]: r for r in rms.list_raw_materials(conn, type_="goods")}
    assert rows["Cola 0,33"]["stock_g"] == 48000             # 2 Karton × 24 Stück
    assert rows["Pfand Kiste"]["stock_g"] == 2000


def test_receiving_wrong_kind_rejected(conn, monkeypatch):
    aid = rms.create_raw_material(conn, {"name": "Tüten", "type": "aid", "unit_label": "VE"})
    pre = _upload(conn, monkeypatch, _answer(positions=[COLA]))
    with pytest.raises(ValidationError):
        rec.commit(conn, {"token": pre["token"], "decisions": {
            "1": {"action": "goods_assign", "raw_material_id": aid["id"], "pieces_per_unit": 24}}})


def test_credit_note_books_deposit_back(conn, monkeypatch):
    p = _goods(conn, "Pfand Kiste", is_deposit=True)
    stock.receipt(conn, p["id"], {"amount_kg": "5"})
    pre = _upload(conn, monkeypatch, _answer("gutschrift", "GS1", [dict(PFAND, netto_cent=-300)]))
    rec.commit(conn, {"token": pre["token"], "decisions": {"2": {"action": "goods_assign", "raw_material_id": p["id"]}}})
    assert rms.get_raw_material(conn, p["id"])["stock_g"] == 3000
    moves = stock.movements(conn, p["id"])
    assert moves[0]["kind"] == "loss" and moves[0]["reason"] == "deposit_return"
    assert moves[0]["reason_text"] == "Pfand zurück"


def test_invoice_sets_piece_price(conn, monkeypatch):
    pre = _upload(conn, monkeypatch, _answer(positions=[COLA]))
    rec.commit(conn, {"token": pre["token"], "decisions": {"1": {"action": "goods_new", "name": "Cola",
                                                                  "pieces_per_unit": 24}}})
    g = rms.list_raw_materials(conn, type_="goods")[0]
    pre = _upload(conn, monkeypatch, _answer("rechnung", "RE1", [COLA]))
    rec.commit(conn, {"token": pre["token"], "decisions": {}})
    assert rms.get_raw_material(conn, g["id"])["price_cents_per_kg"] == 50   # 24,00 € ÷ 48 Stück


def test_deposit_return_only_for_deposit(conn):
    g = _goods(conn)
    stock.receipt(conn, g["id"], {"amount_kg": "10"})
    with pytest.raises(ValidationError):
        stock.loss(conn, g["id"], {"amount_kg": "1", "reason": "deposit_return"})
    stock.loss(conn, g["id"], {"amount_kg": "1", "reason": "own_use"})
    assert rms.get_raw_material(conn, g["id"])["stock_g"] == 9000


# -- Verschieben / Kopieren (K03-89, K03-93) ---------------------------------------------------

def test_move_aid_to_goods_keeps_stock_with_factor(conn):
    a = rms.create_raw_material(conn, {"name": "Cola Karton", "type": "aid", "unit_label": "Karton"})
    stock.receipt(conn, a["id"], {"amount_kg": "3"})                  # 3 VE
    res = goods.move(conn, a["id"], {"to": "goods", "factor": 24})
    g = res["raw_material"]
    assert g["type"] == "goods" and g["unit_label"] == "Stück" and g["stock_g"] == 72000


def test_move_locked_when_in_recipe(conn):
    from tests.conftest import add_item, add_recipe
    m = rms.create_raw_material(conn, {"name": "H-Milch", "type": "standard", "tolerance": "5"})
    _, v = add_recipe(conn, 1)
    add_item(conn, v, 1, m["id"])
    with pytest.raises(ConflictError) as e:
        goods.move(conn, m["id"], {"to": "goods", "piece_g": 1000})
    assert e.value.code == "move_locked"
    res = goods.copy(conn, m["id"], {"to": "goods", "piece_g": 1030, "register_no": 1200})
    g = res["raw_material"]
    assert res["reference"] and g["name"] == "H-Milch" and g["stock_ref"]["id"] == m["id"]
    assert g["stock_g"] is None and g["piece_g"] == 1030


def test_move_grams_to_goods_converts(conn):
    m = rms.create_raw_material(conn, {"name": "Saft", "type": "standard", "tolerance": "5", "price_per_kg": "2,00"})
    stock.receipt(conn, m["id"], {"amount_kg": "10"})                 # 10 kg
    g = goods.move(conn, m["id"], {"to": "goods", "piece_g": 500})["raw_material"]
    assert g["stock_g"] == 20000 and g["price_cents_per_kg"] == 100  # 20 Stück à 1,00 €


def test_copy_goods_to_raw_material_takes_over(conn, monkeypatch):
    pre = _upload(conn, monkeypatch, _answer(positions=[dict(COLA, bezeichnung="H-Milch 1 l", artikelnummer="777",
                                                             gebinde_text="12 ST à 1 L")]))
    doc = rec.commit(conn, {"token": pre["token"], "decisions": {"1": {"action": "goods_new", "name": "H-Milch"}}})
    line = rec.get_delivery(conn, doc["id"])["lines"][0]
    rec.book(conn, doc["id"], {"lines": [{"id": line["id"], "qty_milli": 2000}]})
    g = rms.list_raw_materials(conn, type_="goods")[0]
    assert g["stock_g"] == 24000
    res = goods.copy(conn, g["id"], {"to": "standard", "piece_g": 1030, "tolerance": 5})
    r = res["raw_material"]
    assert r["type"] == "standard" and r["stock_g"] == 24720 and r["active_source"]["article_no"] == "777"
    assert res["goods"]["stock_ref"]["id"] == r["id"] and res["goods"]["stock_g"] is None
    # nächste Lieferung trifft den Rohstoff (Gewicht je Karton = 12 × 1030 g)
    pre = _upload(conn, monkeypatch, _answer(no="AB2", positions=[dict(COLA, bezeichnung="H-Milch 1 l",
                                                                        artikelnummer="777")]))
    assert pre["lines"][0]["raw_material_id"] == r["id"] and not pre["lines"][0]["needs_gpu"]
    with pytest.raises(ConflictError):
        stock.receipt(conn, g["id"], {"amount_kg": "1"})             # Verweis führt keinen Bestand


def test_move_to_other_and_back(conn, monkeypatch):
    pre = _upload(conn, monkeypatch, _answer(positions=[COLA]))
    rec.commit(conn, {"token": pre["token"], "decisions": {"1": {"action": "goods_new", "name": "Cola",
                                                                  "pieces_per_unit": 24}}})
    g = rms.list_raw_materials(conn, type_="goods")[0]
    res = goods.move(conn, g["id"], {"to": "other"})
    other_id = res["other_article_id"]
    assert rms.get_raw_material(conn, g["id"])["archived"]
    assert rec.list_other_articles(conn)[0]["lines"] == 1
    back = goods.other_to(conn, other_id, {"to": "goods", "pieces_per_unit": 24}, keep=False)
    assert back["raw_material"]["type"] == "goods" and back["moved"]
    assert rec.list_other_articles(conn) == []


# -- Kassenimport (K03-86) und Pfand-Übersicht (K03-87) -------------------------------------

def _xlsx(rows, head=("Nummer", "Name", "Anzahl", "Wert")):
    wb = Workbook()
    ws = wb.active
    ws.append(["Artikelabverkauf vom 16.11.2026 bis 22.11.2026"])
    ws.append([])
    ws.append(list(head))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sales_import(conn):
    cola = _goods(conn, "Cola", register_no=1101)
    pfand = _goods(conn, "Pfand Einweg", is_deposit=True, register_no=1003)
    milk = rms.create_raw_material(conn, {"name": "H-Milch", "type": "standard", "tolerance": "5"})
    stock.receipt(conn, milk["id"], {"amount_kg": "20"})
    goods.copy(conn, milk["id"], {"to": "goods", "piece_g": 1000, "register_no": 1200})
    stock.receipt(conn, cola["id"], {"amount_kg": "48"})
    data = _xlsx([(1101, "Cola 0,33", 10, "25,00"), (1101, "Cola 0,33", 2, 5), (1003, "Pfand Einweg", 12, 3.0),
                  (1200, "H-Milch", 3, 4.5), (500, "Offene Handelswaren", 4, 10), (4711, "Brötchen", 100, 40),
                  (None, "Summe", 131, 87.5)])
    rep = sales_import.import_sales(conn, data, mode="check")
    assert (rep["date_from"], rep["date_to"]) == ("2026-11-16", "2026-11-22")
    by = {l["register_no"]: l for l in rep["lines"]}
    assert by[1101]["qty_milli"] == 12000 and by[1101]["status"] == "booked"
    assert by[500]["status"] == "collective" and by[4711]["status"] == "unassigned"
    assert by[1200]["raw_material_id"] == milk["id"] and by[1200]["booked_qty"] == 3000
    assert rep["deposit_cents"] == 300
    run = sales_import.import_sales(conn, data, mode="run")
    assert run["imported"] and run["booked"] == 3
    assert rms.get_raw_material(conn, cola["id"])["stock_g"] == 36000
    assert rms.get_raw_material(conn, milk["id"])["stock_g"] == 17000
    assert rms.get_raw_material(conn, pfand["id"])["stock_g"] == -12000
    with pytest.raises(ConflictError) as e:                       # Zeitraum nur einmal
        sales_import.import_sales(conn, data, mode="run")
    assert e.value.code == "period_imported"
    with pytest.raises(ConflictError):                            # auch überlappend
        sales_import.import_sales(conn, data, mode="run", date_from="2026-11-20", date_to="2026-11-28")
    ov = goods.deposit_overview(conn)
    assert ov["customers_cents"] == 300 and ov["total_cents"] == -300
    sales_import.delete_import(conn, run["id"])
    assert rms.get_raw_material(conn, cola["id"])["stock_g"] == 48000
    assert sales_import.import_sales(conn, data, mode="run")["imported"]


def test_deposit_overview_baeko(conn, monkeypatch):
    pre = _upload(conn, monkeypatch, _answer("rechnung", "RE1", [PFAND]))
    rec.commit(conn, {"token": pre["token"], "decisions": {"2": {"action": "goods_new", "name": "Pfand Kiste"}}})
    pre = _upload(conn, monkeypatch, _answer("gutschrift", "GS1", [dict(PFAND, netto_cent=-150, menge_tausendstel=1000)]))
    rec.commit(conn, {"token": pre["token"], "decisions": {}})
    ov = goods.deposit_overview(conn)
    assert ov["baeko_cents"] == 150 and ov["total_cents"] == 150
    g = rms.list_raw_materials(conn, type_="goods")[0]
    assert g["is_deposit"] and g["stock_g"] == -1000           # Gutschrift: 1 Kiste zurück


def test_stocktake_subtotals(conn):
    cola = _goods(conn, "Cola")
    pfand = _goods(conn, "Pfand Kiste", is_deposit=True)
    conn.execute("UPDATE raw_material SET price_cents_per_kg = 50 WHERE id = ?", (cola["id"],))
    conn.execute("UPDATE raw_material SET price_cents_per_kg = 150 WHERE id = ?", (pfand["id"],))
    stock.receipt(conn, cola["id"], {"amount_kg": "24"})
    st = stocktake.create(conn, {"name": "Test", "stichtag": "2026-11-27"})
    stocktake.add_count(conn, {"raw_material_id": cola["id"], "packs": 20})
    stocktake.add_count(conn, {"raw_material_id": pfand["id"], "amount_kg": "4"})
    res = stocktake.close(conn, st["id"], {"confirm": True})
    assert res["totals"]["goods_cents"] == 1000 and res["totals"]["deposit_cents"] == 600
    assert [ln["name"] for ln in res["lines"]] == ["Cola", "Pfand Kiste"]
    moves = stock.movements(conn, cola["id"])
    assert "Schwund laut Inventur" in moves[0]["note"]
    data, _ = stocktake.export_xlsx(conn, st["id"])
    assert data[:2] == b"PK"
