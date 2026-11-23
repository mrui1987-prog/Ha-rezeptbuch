"""Tests W2a (Rechnung/Gutschrift einlesen) und B1 (Buchungsgruppen, Export) – docs/buchfuehrung-export.md."""

import io

import pytest
from openpyxl import load_workbook

from app.booking import service as bk
from app.errors import ValidationError
from app.raw_materials import service as rms
from app.receiving import service as rec
from tests.test_receiving import PDF, ab, env, load, mehl, position  # noqa: F401  (Fixture env)


def inv(no, positions, art="rechnung", date="2026-10-05", saetze=None):
    r = ab(positions, no, art)
    r["daten"]["belegdatum"] = date
    r["daten"]["summen"] = {"netto_cent": sum(p["netto_cent"] for p in positions), "mwst_saetze": saetze or []}
    return r


def wpos(nr, wg, art, bez, netto, mwst=7, menge=1000, me="ST"):
    p = position(nr, art, bez, menge, me=me, netto=netto)
    p.update(warengruppe=wg, mwst_prozent=mwst, pos=None)
    return p


def upload(conn, env, doc, decisions=None):
    env.append(doc)
    pre = rec.upload(conn, PDF + doc["daten"]["belegnummer"].encode(), "re.pdf")
    return pre, rec.commit(conn, {"token": pre["token"], "decisions": decisions or {}})


def test_groups_seeded_and_maintainable(conn):
    names = [g["short_name"] for g in bk.list_groups(conn)]
    assert names == ["Leergut", "Wurst", "Spirit.", "Feinkost", "HW", "Kaffee", "Zeit.", "Rohst.", "Unk."]
    g = bk.save_group(conn, {"name": "Getränke", "short_name": "Getr."})
    bk.move_group(conn, g["id"], -1)
    assert [x["short_name"] for x in bk.list_groups(conn)][-2:] == ["Getr.", "Unk."]
    with pytest.raises(Exception):
        bk.save_group(conn, {"name": "leergut"})


def test_invoice_groups_learned_and_unchecked(conn, env):
    rm = mehl(conn)
    load(conn, env, [position(1, "109037", "Weizenmehl 550", 25000)],
                   {"1": {"action": "assign", "raw_material_id": rm}})  # Artikelnummer am Rohstoff
    doc = inv("RE1", [wpos(1, "201", "109037", "Weizenmehl 550", 1500, menge=25000, me="KG"),
                      wpos(2, "1405", "990164", "Leergut Pfand", 300, mwst=19),
                      wpos(3, "1250", "370066", "Stäbchen", 800, mwst=19)])
    # neue Warengruppe 1250 ohne Artikelgruppe → muss gefragt werden
    env.append(doc)
    pre = rec.upload(conn, PDF + b"RE1", "re.pdf")
    assert pre["billing"] and pre["lines"][0]["booking"]["id"] == bk.ROHSTOFFE
    with pytest.raises(ValidationError) as e:
        rec.commit(conn, {"token": pre["token"], "decisions": {"2": {"action": "other"}, "3": {"action": "other"}}})
    assert e.value.code == "group_missing"
    saved = rec.commit(conn, {"token": pre["token"], "decisions": {
        "2": {"action": "other"}, "3": {"action": "other", "booking_group_id": bk.UNKOSTEN}}})
    assert saved["status"] == "open" and all(d["kind"] == "order_confirmation" for d in rec.list_deliveries(conn))
    groups = {l["line_no"]: l["booking_group_id"] for l in saved["lines"]}
    assert groups == {1: bk.ROHSTOFFE, 2: bk.LEERGUT, 3: bk.UNKOSTEN}
    # automatisch gesetzt = ungeprüft, gewählt = geprüft; Warengruppe 1250 gelernt
    names = {u["name"] for u in bk.unchecked(conn)}
    assert "Weizenmehl 550" in names and "Leergut Pfand" in names and "Stäbchen" not in names
    assert bk.learned(conn, saved_dealer(conn), "1250") == bk.UNKOSTEN
    assert conn.execute("SELECT count(*) FROM stock_movement").fetchone()[0] == 0   # Rechnung bucht keinen Bestand
    n = bk.confirm(conn, [{"kind": u["kind"], "id": u["id"], "booking_group_id": u["booking_group_id"]}
                          for u in bk.unchecked(conn)])
    assert n == 2 and bk.unchecked(conn) == []


def saved_dealer(conn):
    return conn.execute("SELECT id FROM dealer ORDER BY id LIMIT 1").fetchone()["id"]


def test_month_export_rates_groups_credit_note(conn, env):
    upload(conn, env, inv("RE2", [wpos(1, "1001", "100001", "Schokoriegel", 1000, mwst=7),
                                  wpos(2, "1405", "990164", "Pfand", 300, mwst=19)],
                          saetze=[{"satz": 7, "netto_cent": 1000, "mwst_cent": 70, "brutto_cent": 1070},
                                  {"satz": 19, "netto_cent": 300, "mwst_cent": 57, "brutto_cent": 357}]),
           {"1": {"action": "other"}, "2": {"action": "other"}})
    upload(conn, env, inv("GS1", [wpos(1, "1405", "990164", "Pfand", -300, mwst=19, menge=-1000)],
                          art="gutschrift", date="2026-10-20"))
    upload(conn, env, inv("RE3", [wpos(1, "1001", "100001", "Schokoriegel", 999)], date="2026-11-02"))
    data = bk.month_rows(conn, "2026-10")
    assert [d["doc_no"] for d in data["documents"]] == ["RE2", "GS1"]
    re2, gs1 = data["documents"]
    assert (re2["net"], re2["vat"], re2["gross"]) == (1300, 127, 1427)
    assert (re2["net_7"], re2["vat_7"], re2["net_19"], re2["vat_19"]) == (1000, 70, 300, 57)
    assert re2["groups"] == {bk.HANDELSWARE: 1000, bk.LEERGUT: 300}
    assert gs1["net"] == -300 and gs1["vat"] == -57 and gs1["groups"] == {bk.LEERGUT: -300}
    wb = load_workbook(io.BytesIO(bk.export_xlsx(conn, "2026-10")))
    ws = wb.active
    head = [c.value for c in ws[1]]
    assert head[:7] == ["Nr.", "Tag", "Händler", "Beleg", "Brutto", "MwSt.", "Netto"]
    assert ws.cell(row=2, column=1).value is None and ws.cell(row=2, column=5).value == 14.27
    assert ws.cell(row=3, column=4).value == "Gutschrift GS1" and ws.cell(row=2, column=len(head)).value == "ok"
    with pytest.raises(ValidationError):
        bk.month_rows(conn, "2026-13")


def test_substitute_mark_and_repeat(conn, env):
    rm = mehl(conn)
    _, doc = load(conn, env, [position(1, "109037", "Weizenmehl 550", 25000)],
                  {"1": {"action": "assign", "raw_material_id": rm}})
    line = doc["lines"][0]["id"]
    r = rec.book(conn, doc["id"], {"lines": [{"id": line, "qty_milli": 25000,
                                              "substitute": {"raw_material_id": rm, "code": "4001234"}}]})
    assert r["lines"][0]["repeat_substitute"] is False
    assert [s["id"] for s in rec.list_substitutes(conn)] == [rm]
    _, doc2 = load(conn, env, [position(1, "109037", "Weizenmehl 550", 25000)], no="AT1000002")
    r2 = rec.book(conn, doc2["id"], {"lines": [{"id": doc2["lines"][0]["id"], "qty_milli": 25000,
                                                "substitute": {"raw_material_id": rm, "code": "4001234"}}]})
    assert r2["lines"][0]["repeat_substitute"] is True
    rec.clear_substitute(conn, rm)
    assert rec.list_substitutes(conn) == []


def test_ab_substitute_prior_hint(conn, env):
    rm = mehl(conn)
    load(conn, env, [position(1, "555555", "Fremdmehl", 25000)],
         {"1": {"action": "substitute", "raw_material_id": rm}})
    env.append(ab([position(1, "555555", "Fremdmehl", 25000)], "AT1000002"))
    pre = rec.upload(conn, PDF + b"x2", "ab.pdf")
    assert pre["lines"][0]["prior_substitute"]["raw_material_id"] == rm
