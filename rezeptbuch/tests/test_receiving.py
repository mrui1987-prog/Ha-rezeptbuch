"""Tests Wareneingang W1 (docs/wareneingang.md 10) mit Ersatz-Leser (feste JSON-Antworten, kein Add-on 3)."""

import pytest

from app.errors import ConflictError, ValidationError
from app.raw_materials import service as rms, stock
from app.readers import client
from app.receiving import service as rec

PDF = b"%PDF-1.4 test"


def position(nr, art, bez, menge, me="KG", gebinde=None, bestell=False, preis=6000, netto=2400):
    return {"nr": nr, "pos": nr, "artikelnummer": art, "bezeichnung": bez, "menge_tausendstel": menge,
            "mengeneinheit": me, "gebinde_text": gebinde, "bestellartikel": bestell,
            "preis_zehntausendstel_euro": preis, "preiseinheit": "EIN", "netto_cent": netto, "mwst_prozent": 7}


def ab(positions, no="AT1000001", art="auftragsbestaetigung"):
    return {"status": "ok", "addon_version": "0.1.0", "daten": {
        "belegart": art, "haendler": "BÄKO Saar-Pfalz eG", "belegnummer": no, "belegdatum": "2026-11-20",
        "lieferdatum_voraussichtlich": "2026-11-23", "ihre_referenz": "CL123", "summen": {"netto_cent": 10000},
        "positionen": positions}, "plausibilitaet": []}


@pytest.fixture
def env(conn, db_path, monkeypatch):
    monkeypatch.setenv("REZEPTBUCH_DB", str(db_path))
    answers = []
    monkeypatch.setattr(client, "read", lambda reader, pdf, name: answers.pop(0))
    return answers


def mehl(conn, name="Weizenmehl 550", **kw):
    data = {"name": name, "type": "standard", "tolerance_unit": "g", "tolerance": "5"}
    data.update(kw)
    return rms.create_raw_material(conn, data)["id"]


def load(conn, env, positions, decisions=None, no="AT1000001"):
    env.append(ab(positions, no))
    pre = rec.upload(conn, PDF + no.encode(), "ab.pdf")
    return pre, rec.commit(conn, {"token": pre["token"], "decisions": decisions or {}})


def test_first_ab_assign_then_automatic(conn, env):
    rm = mehl(conn)
    pre, doc = load(conn, env, [position(1, "202656", "Weizenmehl Type 550", 400000, gebinde="16 SCK à 25 KG")],
                    {"1": {"action": "assign", "raw_material_id": rm}})
    assert pre["lines"][0]["target"] == "unknown" and pre["lines"][0]["suggestions"][0]["id"] == rm
    line = doc["lines"][0]
    assert line["target"] == "raw_material" and line["pack"] == {"step_milli": 25000, "name": "Sack", "count": 16}
    # zweite AB: Artikel automatisch erkannt
    env.append(ab([position(1, "202656", "Weizenmehl Type 550", 50000)], "AT1000002"))
    pre2 = rec.upload(conn, PDF + b"2", "ab2.pdf")
    assert pre2["lines"][0]["target"] == "raw_material" and pre2["lines"][0]["raw_material_id"] == rm


def test_undecided_line_blocks_commit(conn, env):
    env.append(ab([position(1, "1", "Unbekannt", 1000)]))
    pre = rec.upload(conn, PDF, None)
    with pytest.raises(ValidationError) as e:
        rec.commit(conn, {"token": pre["token"], "decisions": {}})
    assert e.value.code == "decision_missing"
    assert conn.execute("SELECT count(*) FROM receiving_document").fetchone()[0] == 0


def test_duplicate_and_invoice_later(conn, env):
    load(conn, env, [position(1, "9", "Salz", 1000)], {"1": {"action": "other"}})
    env.append(ab([position(1, "9", "Salz", 1000)]))
    pre = rec.upload(conn, PDF, None)
    assert pre["duplicate"]
    with pytest.raises(ConflictError):
        rec.commit(conn, {"token": pre["token"]})
    env.append(ab([], "RE1", "rechnung"))           # seit W2a (0013): Rechnungen werden eingelesen
    assert rec.upload(conn, PDF, None)["billing"] is True


def test_reader_not_ok(conn, env):
    env.append({"status": "unlesbar", "meldung": "Summen stimmen nicht", "warnungen": ["x"]})
    with pytest.raises(ConflictError) as e:
        rec.upload(conn, PDF, None)
    assert e.value.code == "reader_unlesbar"


def test_new_material_needs_tolerance_and_gpu(conn, env):
    env.append(ab([position(1, "77", "H-Milch 3,5%", 20000, me="L", gebinde="1 VE à 20 L")]))
    pre = rec.upload(conn, PDF, None)
    with pytest.raises(ValidationError):
        rec.commit(conn, {"token": pre["token"], "decisions": {"1": {"action": "new", "name": "Milch"}}})
    doc = rec.commit(conn, {"token": pre["token"], "decisions": {"1": {"action": "new", "name": "Milch",
                                                                      "tolerance": "5", "grams_per_unit": 1030}}})
    line = doc["lines"][0]
    assert line["grams_per_unit"] == 1030 and line["raw_material_name"] == "Milch"


def test_book_partial_backorder_and_rest(conn, env):
    rm = mehl(conn)
    stock.inventory(conn, rm, {"stock_kg": "0"})
    _, doc = load(conn, env, [position(1, "202656", "Weizenmehl", 400000, gebinde="16 SCK à 25 KG"),
                              position(2, "5", "Kirschwasser", 5000, me="L", bestell=True)],
                  {"1": {"action": "assign", "raw_material_id": rm}, "2": {"action": "other"}})
    l1, l2 = doc["lines"]
    res = rec.book(conn, doc["id"], {"lines": [{"id": l1["id"], "qty_milli": 375000, "rest": "backorder"},
                                               {"id": l2["id"], "qty_milli": 0, "rest": "backorder"}]})
    assert res["status"] == "partial" and res["lines"][0]["stock_g"] == 375000
    # Rückstand erscheint wieder (K03-44)
    open_doc = rec.list_deliveries(conn)[0]
    assert {l["id"]: l["remaining_milli"] for l in open_doc["lines"]} == {l1["id"]: 25000, l2["id"]: 5000}
    res = rec.book(conn, doc["id"], {"lines": [{"id": l1["id"], "qty_milli": 25000},
                                               {"id": l2["id"], "qty_milli": 0, "rest": "cancel"}]})
    assert res["status"] == "booked" and rec.list_deliveries(conn) == []
    moves = stock.movements(conn, rm)
    assert moves[0]["source"] == "receiving" and "AT1000001 Pos. 1" in moves[0]["note"]


def test_untracked_only_noted_unless_start(conn, env):
    rm = mehl(conn)
    _, doc = load(conn, env, [position(1, "202656", "Weizenmehl", 25000)],
                  {"1": {"action": "assign", "raw_material_id": rm}})
    lid = doc["lines"][0]["id"]
    res = rec.book(conn, doc["id"], {"lines": [{"id": lid, "qty_milli": 25000}]})
    assert res["lines"][0]["tracked"] is False and rms.get_raw_material(conn, rm)["stock_g"] is None


def test_unit_bt_uses_grams_per_unit(conn, env):
    rm = mehl(conn, "Apfelwürfel")
    stock.inventory(conn, rm, {"stock_kg": "0"})
    env.append(ab([position(1, "88", "Apfelwürfel", 3000, me="BT")]))
    pre = rec.upload(conn, PDF, None)
    doc = rec.commit(conn, {"token": pre["token"], "decisions": {"1": {"action": "assign", "raw_material_id": rm,
                                                                      "grams_per_unit": 5000}}})
    res = rec.book(conn, doc["id"], {"lines": [{"id": doc["lines"][0]["id"], "qty_milli": 3000}]})
    assert res["lines"][0]["grams"] == 15000
    # Faktor fehlt später an der Bezugsquelle → Buchen gesperrt
    _, doc2 = load(conn, env, [position(1, "88", "Apfelwürfel", 1000, me="BT")], no="AT9")
    conn.execute("UPDATE raw_material_source SET grams_per_unit = NULL")
    with pytest.raises(ConflictError) as e:
        rec.book(conn, doc2["id"], {"lines": [{"id": doc2["lines"][0]["id"], "qty_milli": 1000}]})
    assert e.value.code == "gpu_missing"


def test_substitute_on_delivery_day(conn, env):
    a, b = mehl(conn, "Roggenmehl A"), mehl(conn, "Roggenmehl B")
    stock.inventory(conn, b, {"stock_kg": "0"})
    _, doc = load(conn, env, [position(1, "11", "Roggenmehl A", 25000)],
                  {"1": {"action": "assign", "raw_material_id": a}})
    rec.book(conn, doc["id"], {"lines": [{"id": doc["lines"][0]["id"], "qty_milli": 25000,
                                          "substitute": {"raw_material_id": b}}]})
    assert rms.get_raw_material(conn, b)["stock_g"] == 25000
    assert "Pass prüfen" in stock.movements(conn, b)[0]["note"]
    # Ersatz hängt keine Bezugsquelle an
    assert conn.execute("SELECT count(*) FROM raw_material_source WHERE raw_material_id = ?", (b,)).fetchone()[0] == 0


def test_substitute_scan_same_material_other_pack(conn, env):
    """Ersatz per Scan (H-D): gleicher Rohstoff, anderes Gebinde, kein Code gespeichert, Vermerk mit Gebinde."""
    a = mehl(conn, "Roggenmehl A")
    stock.inventory(conn, a, {"stock_kg": "0"})
    _, doc = load(conn, env, [position(1, "11", "Roggenmehl A", 50000)],
                  {"1": {"action": "assign", "raw_material_id": a}})
    rec.book(conn, doc["id"], {"lines": [{"id": doc["lines"][0]["id"], "qty_milli": 40000,
                                          "substitute": {"raw_material_id": a, "pack_g": 20000}}]})
    assert rms.get_raw_material(conn, a)["stock_g"] == 40000
    note = stock.movements(conn, a)[0]["note"]
    assert "Pass prüfen" in note and "Gebinde 20 kg" in note
    assert conn.execute("SELECT count(*) FROM raw_material_barcode").fetchone()[0] == 0


def test_unexpected_line_and_aid(conn, env):
    rm = mehl(conn)
    tuete = rms.create_raw_material(conn, {"name": "Brötchentüten", "type": "aid", "unit_label": "Karton"})["id"]
    stock.inventory(conn, tuete, {"packs": 0, "source": "scan", "device_id": "x"})
    _, doc = load(conn, env, [position(1, "3", "Tüten", 2000, me="KT")],
                  {"1": {"action": "aid_assign", "raw_material_id": tuete}})
    extra = rec.add_unexpected(conn, doc["id"], {"raw_material_id": rm})
    stock.inventory(conn, rm, {"stock_kg": "0"})
    res = rec.book(conn, doc["id"], {"lines": [{"id": doc["lines"][0]["id"], "qty_milli": 2000},
                                               {"id": extra["line_id"], "qty_milli": 25000}]})
    assert res["status"] == "booked"
    assert rms.get_raw_material(conn, tuete)["stock_g"] == 2000       # 2 Karton
    assert rms.get_raw_material(conn, rm)["stock_g"] == 25000


def test_delete_only_without_bookings(conn, env):
    rm = mehl(conn)
    stock.inventory(conn, rm, {"stock_kg": "0"})
    _, doc = load(conn, env, [position(1, "1", "Weizenmehl", 1000)], {"1": {"action": "assign", "raw_material_id": rm}})
    rec.book(conn, doc["id"], {"lines": [{"id": doc["lines"][0]["id"], "qty_milli": 1000}]})
    with pytest.raises(ConflictError):
        rec.delete_document(conn, doc["id"])
    _, doc2 = load(conn, env, [position(1, "1", "Weizenmehl", 1000)], no="AT2")
    rec.delete_document(conn, doc2["id"])
    assert len(rec.list_documents(conn)) == 1
    # M03-33: zurückbuchen und löschen
    assert rms.get_raw_material(conn, rm)["stock_g"] == 1000
    res = rec.delete_document(conn, doc["id"], reverse=True)
    assert res["reversed"] == 1
    assert rms.get_raw_material(conn, rm)["stock_g"] == 0
    assert rec.list_documents(conn) == []
    m = conn.execute("SELECT kind, delta_g, note, receiving_line_id FROM stock_movement ORDER BY id DESC LIMIT 1").fetchone()
    assert m["kind"] == "undo" and m["delta_g"] == -1000 and "gelöscht" in m["note"] and m["receiving_line_id"] is None


def test_other_article_to_raw_material(conn, env):
    _, doc = load(conn, env, [position(1, "500", "Faltenbeutel", 1000, me="KG")], {"1": {"action": "other"}})
    other = rec.list_other_articles(conn)[0]
    rm = mehl(conn, "Faltenbeutel")
    rec.update_other_article(conn, other["id"], {"raw_material_id": rm})
    assert rec.list_other_articles(conn) == []
    assert conn.execute("SELECT target FROM receiving_line").fetchone()[0] == "raw_material"


def test_pack_step():
    assert rec.pack_step("3 VE à 5 KG", "KG")["step_milli"] == 5000
    assert rec.pack_step("1 VE à 3 BT", "BT") == {"step_milli": 3000, "name": "VE", "count": 1}
    assert rec.pack_step(None, "L")["step_milli"] == 1000
    assert rec.pack_step("1 PG à 1.000 ST", "ST")["step_milli"] == 1_000_000      # Tausenderpunkt
    assert rec.pack_step("1 VE à 2,5 KG", "KG")["step_milli"] == 2500
    assert rec.pack_step("1 KT à 5 KG", "KG") == {"step_milli": 5000, "name": "Karton", "count": 1}  # Sahne AT1003549
    other = rec.pack_step("2 VE à 5 L", "KG")            # Menge in KG, Gebinde in L → nur Vorschlag
    assert other["step_milli"] == 1000 and other["count"] is None
    assert other["hint"] == {"name": "VE", "size_milli": 5000, "unit": "L"}


def test_same_article_twice_in_one_ab(conn, env):
    """Gleicher Artikel zweimal im Beleg (z. B. Pfand): kein Fehler 500 (Meldung Michael 23.11.2026, 10:23)."""
    _, doc = load(conn, env, [position(1, "1405", "Pfand Kiste", 2000, me="ST"),
                              position(2, "1405", "Pfand Kiste", 1000, me="ST")],
                  {"1": {"action": "other"}, "2": {"action": "other"}})
    assert {l["target"] for l in doc["lines"]} == {"other"}
    assert conn.execute("SELECT count(*) FROM other_article").fetchone()[0] == 1
    _, doc2 = load(conn, env, [position(1, "66", "Becher", 2000, me="KT"), position(2, "66", "Becher", 1000, me="KT")],
                   {"1": {"action": "aid_new", "name": "Becher", "unit_label": "Karton"},
                    "2": {"action": "aid_new", "name": "Becher", "unit_label": "Karton"}}, no="AT2")
    assert doc2["lines"][0]["raw_material_id"] == doc2["lines"][1]["raw_material_id"]


def test_missing_gpu_on_known_line_says_so(conn, env):
    """Bekannter Rohstoff ohne „g je ME“: klare Meldung statt „Ungültige Zahl“."""
    rm = mehl(conn, "Apfelwürfel")
    env.append(ab([position(1, "88", "Apfelwürfel", 3000, me="BT")]))
    pre = rec.upload(conn, PDF, None)
    rec.commit(conn, {"token": pre["token"], "decisions": {"1": {"action": "assign", "raw_material_id": rm,
                                                                  "grams_per_unit": 5000}}})
    conn.execute("UPDATE raw_material_source SET grams_per_unit = NULL")
    env.append(ab([position(1, "88", "Apfelwürfel", 3000, me="BT")], "AT5"))
    pre = rec.upload(conn, PDF + b"5", None)
    assert pre["lines"][0]["needs_gpu"]
    with pytest.raises(ValidationError) as e:
        rec.commit(conn, {"token": pre["token"], "decisions": {}})
    assert e.value.code == "gpu_missing" and "Pos. 1" in str(e.value) and "Gewicht je Beutel" in str(e.value)


def test_line_knows_delivery_pack_and_code(conn, env):
    """Befund Michael 27.11.2026: Abhaken braucht Liefergebinde und „hat schon Code“ an der Zeile."""
    from app.raw_materials import scanner
    rm = mehl(conn, "Sahne 30 %", unit_size_g=1000, unit_label="Packung")
    _, doc = load(conn, env, [position(1, "500", "Sahne 30%", 10000, me="L", gebinde="2 VE à 5 L")],
                  {"1": {"action": "assign", "raw_material_id": rm, "grams_per_unit": 1000}})
    line = doc["lines"][0]
    assert line["pack"] == {"step_milli": 5000, "name": "VE", "count": 2}      # Beleg-Gebinde: 1 Scan = 5 L
    assert line["rm_pack_g"] == 1000 and line["rm_delivery_pack_g"] is None and line["rm_has_code"] is False
    scanner.assign(conn, {"code": "4006381333931", "raw_material_id": rm})
    assert rec.get_delivery(conn, doc["id"])["lines"][0]["rm_has_code"] is True


def test_pack_from_bracket_line():
    """Befund Michael 27.11.2026 (AT1003549): H-Milch „10,000 L“, nur „(1 BIB)“ → 1 BIB à 10 L."""
    p = {"gebinde_text": None, "gebinde_klammer": "(1 BIB)", "menge_tausendstel": 10000, "mengeneinheit": "L"}
    assert rec.pack_text_of(p) == "1 BIB à 10 L"
    assert rec.pack_step(rec.pack_text_of(p), "L") == {"step_milli": 10000, "name": "BIB", "count": 1}
    assert rec.pack_text_of({**p, "gebinde_klammer": "(4 SCK)", "menge_tausendstel": 100000, "mengeneinheit": "KG"}) \
        == "4 SCK à 25 KG"
    assert rec.pack_text_of({**p, "gebinde_klammer": "(3 KT)", "menge_tausendstel": 2500}) == "3 KT à 0,833 L"
    assert rec.pack_text_of({**p, "gebinde_klammer": None}) is None
    assert rec.pack_text_of({**p, "gebinde_klammer": "(10 L)"}) is None          # gleiche Einheit: kein Gebinde
    assert rec.pack_text_of({**p, "gebinde_text": "1 VE à 5 L"}) == "1 VE à 5 L"


def test_bib_line_gets_pack_on_upload_and_for_old_documents(conn, env):
    rm = mehl(conn, "H-Milch 3,5 %")
    pos = position(1, "506020", "H-Milch 3,5% Milch-Wolke - 10l BIB", 10000, me="L")
    pos["gebinde_klammer"] = "(1 BIB)"
    _, doc = load(conn, env, [pos], {"1": {"action": "assign", "raw_material_id": rm, "grams_per_unit": 1030}})
    assert doc["lines"][0]["pack"]["step_milli"] == 10000
    # schon früher eingelesener Beleg ohne gespeicherten Gebindetext: aus dem Leserergebnis abgeleitet
    conn.execute("UPDATE receiving_line SET pack_text = NULL")
    conn.commit()
    line = rec.get_delivery(conn, doc["id"])["lines"][0]
    assert line["pack_text"] == "1 BIB à 10 L" and line["pack"]["name"] == "BIB"


def test_preview_with_areas_and_page_images(conn, env, monkeypatch):
    """Vorschaubild der Zuordnung (Wunsch Michael 27.11.2026): Bereiche, Klartext, Seitenbild mit Ablage."""
    rm = mehl(conn, "H-Schlagsahne 30 %")
    pos = position(1, "505062", "H-Schlagsahne 30% frischli", 5000, gebinde="1 KT à 5 KG")
    pos["bereich"] = {"seite": 1, "oben": 477.7, "unten": 512.2}
    answer = ab([pos])
    answer["daten"]["seitenmasse"] = [{"breite": 595.3, "hoehe": 841.9}]
    answer["daten"]["positionen"][0]["menge_text"] = "5,000"
    env.append(answer)
    pre = rec.upload(conn, PDF + b"vorschau", "ab.pdf")
    assert pre["pages"] == [{"page": 1, "width": 595.3, "height": 841.9}]
    line = pre["lines"][0]
    assert line["area"] == {"page": 1, "top": 477.7, "bottom": 512.2}
    assert line["read"]["qty_text"] == "5,000 KG" and line["read"]["pack"]["step_milli"] == 5000
    calls = []
    monkeypatch.setattr(client, "page_image", lambda pdf, page: calls.append(page) or b"\x89PNG-seite")
    assert rec.page_png(conn, pre["token"], 1) == b"\x89PNG-seite"
    assert rec.page_png(conn, pre["token"], 1) == b"\x89PNG-seite" and calls == [1]        # zweites Mal aus der Ablage
    with pytest.raises(Exception):
        rec.page_png(conn, "../../etc", 1)
    doc = rec.commit(conn, {"token": pre["token"], "decisions": {"1": {"action": "assign", "raw_material_id": rm}}})
    a = rec.assignment(conn, doc["id"])
    assert a["file_key"] == pre["token"] and a["pages"][0]["page"] == 1
    assert a["lines"][0]["area"]["top"] == 477.7 and a["lines"][0]["read"]["pack"]["name"] == "Karton"
    # nach dem Speichern liegt das PDF nicht mehr im Probelauf: Bild kommt über den gespeicherten Beleg
    for f in (rec.documents_dir() / "vorschau").glob("*.png"):
        f.unlink()
    assert rec.page_png(conn, pre["token"], 1) == b"\x89PNG-seite" and calls == [1, 1]
