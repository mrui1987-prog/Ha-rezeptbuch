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
    m = bk.months(conn)
    assert m["months"] == [{"month": "2026-11", "n": 1}, {"month": "2026-10", "n": 2}]


def test_articles_list_keeps_checked(conn, env):
    upload(conn, env, inv("RE4", [wpos(1, "1001", "100001", "Schokoriegel", 1000),
                                  wpos(2, "1250", "370066", "Stäbchen", 800, mwst=19)]),
           {"1": {"action": "other"}, "2": {"action": "other", "booking_group_id": bk.UNKOSTEN}})
    arts = {a["name"]: a for a in bk.articles(conn)}
    assert arts["Schokoriegel"]["checked"] is False and arts["Stäbchen"]["checked"] is True
    assert list(arts)[0] == "Schokoriegel"          # ungeprüfte zuerst
    a = arts["Schokoriegel"]
    bk.confirm(conn, [{"kind": a["kind"], "id": a["id"], "booking_group_id": a["booking_group_id"]}])
    assert all(x["checked"] for x in bk.articles(conn)) and len(bk.articles(conn)) == 2


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


def test_ab_substitute_pending_until_booked(conn, env):
    rm = mehl(conn)
    _, doc = load(conn, env, [position(1, "555001", "Speisequark Fremd", 5000)],
                  {"1": {"action": "substitute", "raw_material_id": rm}})
    pend = rec.pending_substitutes(conn)
    assert [(p["id"], p["article_no"]) for p in pend] == [(rm, "555001")] and rec.list_substitutes(conn) == []
    rec.book(conn, doc["id"], {"lines": [{"id": doc["lines"][0]["id"], "qty_milli": 5000}]})
    assert rec.pending_substitutes(conn) == [] and [s["id"] for s in rec.list_substitutes(conn)] == [rm]


def test_ab_substitute_prior_hint(conn, env):
    rm = mehl(conn)
    load(conn, env, [position(1, "555555", "Fremdmehl", 25000)],
         {"1": {"action": "substitute", "raw_material_id": rm}})
    env.append(ab([position(1, "555555", "Fremdmehl", 25000)], "AT1000002"))
    pre = rec.upload(conn, PDF + b"x2", "ab.pdf")
    assert pre["lines"][0]["prior_substitute"]["raw_material_id"] == rm
    assert pre["lines"][0]["prior_substitute"]["number"] == conn.execute(
        "SELECT number FROM raw_material WHERE id = ?", (rm,)).fetchone()[0]


def test_ab_permanent_switch_creates_new_raw_material(conn, env):
    """Befund 27.11.: „Dauerhaft umstellen“ beim Hochladen legt den neuen Rohstoff an (vorher Sprung ohne Anlegen)."""
    rm = mehl(conn, "Magerquark")
    load(conn, env, [position(1, "555777", "Speisequark mager Fremd", 5000)],
         {"1": {"action": "substitute", "raw_material_id": rm}})
    env.append(ab([position(1, "555777", "Speisequark mager Fremd", 5000)], "AT1000002"))
    pre = rec.upload(conn, PDF + b"x2", "ab.pdf")
    ps = pre["lines"][0]["prior_substitute"]
    doc = rec.commit(conn, {"token": pre["token"], "decisions": {"1": {
        "action": "new", "name": "Magerquark Fremd", "tolerance": "5", "tolerance_unit": "g",
        "switch_from": {"number": ps["number"], "name": ps["name"]}}}})
    line = doc["lines"][0]
    assert line["target"] == "raw_material" and line["raw_material_name"] == "Magerquark Fremd"
    assert line["raw_material_number"] and line["raw_material_id"] != rm


def _ipos(nr, art, bez, menge, order):
    p = wpos(nr, "201", art, bez, 2400, menge=menge, me="KG")
    p["auftrag"] = {"referenz": "CL1", "auftrag": order, "auftragsdatum": "2026-11-20"}
    return p


def test_invoice_reconcile_and_rebook(conn, env):
    """M03-41: Rechnungsposition nicht geliefert/gebucht → offen, „Nachbuchen“ bucht auf die AB-Position."""
    rm = mehl(conn)
    kw = mehl(conn, "Kirschwasser")
    _, doc = load(conn, env, [position(1, "109037", "Weizenmehl 550", 25000), position(2, "777001", "Kirschwasser", 2000)],
                  {"1": {"action": "assign", "raw_material_id": rm}, "2": {"action": "assign", "raw_material_id": kw}})
    l1, l2 = doc["lines"]
    rec.book(conn, doc["id"], {"lines": [{"id": l1["id"], "qty_milli": 25000, "start_tracking": True},
                                         {"id": l2["id"], "qty_milli": 0, "rest": "cancel"}]})
    _, invd = upload(conn, env, inv("RE7", [_ipos(1, "109037", "Weizenmehl 550", 25000, "AT1000001"),
                                            _ipos(2, "777001", "Kirschwasser", 2000, "AT1000001"),
                                            _ipos(3, "109037", "Weizenmehl 550", 5000, None)], date="2026-11-21"))
    assert conn.execute("SELECT order_no FROM receiving_line WHERE document_id = ? AND line_no = 1",
                        (invd["id"],)).fetchone()[0] == "AT1000001"
    r = {x["line_no"]: x for x in rec.reconcile(conn, invd["id"])}
    assert r[1]["status"] == "ok" and r[2]["status"] == "open" and r[2]["missing_milli"] == 2000
    assert r[3]["status"] == "no_ab"
    res = rec.rebook(conn, invd["id"], r[2]["line_id"])
    assert res["status"] == "booked" and res["ab_doc_no"] == "AT1000001"
    assert stock_g(conn, kw) == 2000
    res = rec.rebook(conn, invd["id"], r[3]["line_id"])
    assert stock_g(conn, rm) == 30000
    assert {x["status"] for x in rec.reconcile(conn, invd["id"])} == {"ok"}
    with pytest.raises(Exception):
        rec.rebook(conn, invd["id"], r[2]["line_id"])


def stock_g(conn, rm_id):
    return conn.execute("SELECT stock_g FROM raw_material WHERE id = ?", (rm_id,)).fetchone()[0]


def test_reconcile_ignore(conn, env):
    rm = mehl(conn)
    load(conn, env, [position(1, "109037", "Weizenmehl 550", 25000)], {"1": {"action": "assign", "raw_material_id": rm}})
    _, invd = upload(conn, env, inv("RE8", [_ipos(1, "109037", "Weizenmehl 550", 25000, "AT1000001")], date="2026-11-21"))
    line = rec.reconcile(conn, invd["id"])[0]
    assert line["status"] == "open"
    rec.rebook(conn, invd["id"], line["line_id"], {"ignore": True})
    assert rec.reconcile(conn, invd["id"])[0]["status"] == "ignored"


def test_change_assignment_after_save(conn, env):
    """M03-42: Zuordnung nachträglich ändern, gebuchte Positionen nur die Gruppe."""
    rm = mehl(conn)
    rm2 = mehl(conn, "Weizenmehl 812")
    _, doc = load(conn, env, [position(1, "109037", "Weizenmehl 550", 25000), position(2, "990164", "Pfand", 1000, me="ST")],
                  {"1": {"action": "assign", "raw_material_id": rm}, "2": {"action": "other"}})
    a = rec.assignment(conn, doc["id"])
    l1 = a["lines"][0]
    assert l1["raw_material_name"] == "Weizenmehl 550" and not l1["locked"]
    a = rec.change_line(conn, l1["id"], {"raw_material_id": rm2})
    assert a["lines"][0]["raw_material_name"] == "Weizenmehl 812"
    # Artikelnummer wandert mit: nächste AB findet den neuen Rohstoff
    assert rec._source_hit(conn, a["lines"] and saved_dealer(conn), "109037")["raw_material_id"] == rm2
    rec.book(conn, doc["id"], {"lines": [{"id": l1["id"], "qty_milli": 25000, "start_tracking": True}]})
    assert rec.assignment(conn, doc["id"])["lines"][0]["locked"]
    with pytest.raises(Exception):
        rec.change_line(conn, l1["id"], {"raw_material_id": rm})
    # Rechnung: Gruppe je Position änderbar
    _, invd = upload(conn, env, inv("RE9", [wpos(1, "1405", "990164", "Pfand", 300, mwst=19)]),
                     {"1": {"action": "other"}})
    il = rec.assignment(conn, invd["id"])["lines"][0]
    a = rec.change_line(conn, il["id"], {"booking_group_id": bk.UNKOSTEN})
    assert a["lines"][0]["booking_group_id"] == bk.UNKOSTEN
