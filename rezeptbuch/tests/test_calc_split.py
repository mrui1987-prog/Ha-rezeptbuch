"""Tests Modul 06 Teil C3 ohne Datenbank: Kombinieren, Faktor, Obergrenze, Teige, Unterrezept-Aufträge.

docs/berechnung.md Abschnitt 17 (R06-19 bis R06-58, P06-11 bis P06-18, H06-6 bis H06-10).
Erwartete Werte von Hand nachgerechnet (Rechenweg im Kommentar). Testdaten, keine Betriebsdaten.
"""

from fractions import Fraction

import pytest

from app.calculation.engine import (
    Basis,
    Line,
    Material,
    Order,
    PieceWeight,
    Recipe,
    calculate,
    calculate_order,
    min_doughs,
    plan_doughs,
)
from app.errors import ValidationError

MEHL = Material(1, 1, "Weizenmehl 550", "flour", "percent", 20)
ROGGEN = Material(2, 2, "Roggenmehl 1150", "flour", "percent", 20)
WASSER = Material(3, 3, "Wasser", "standard", "g", 50)
SALZ = Material(4, 4, "Speisesalz", "standard", "g", 2)
HEFE = Material(5, 5, "Hefe frisch", "standard", "g", 5)


def line(position, material, amount):
    return Line(position=position, amount_g=amount, material=material)


def recipe(lines, rid=100, name="Testrezept", **kw):
    return Recipe(id=rid, number=rid, name=name, lines=tuple(lines), **kw)


def targets(result):
    return [i["target_g"] for i in result["items"]]


def codes(result):
    return [w["code"] for w in result["warnings"]]


# Brötchenteig: G = 10 000 g (60 % Mehl), Stückgewicht 65 g
TEIG = recipe([line(1, MEHL, 6000), line(2, WASSER, 3800), line(3, SALZ, 120), line(4, HEFE, 80)],
              piece_weights=(PieceWeight(1, "Stück", 65),))

# Brot mit Vorteig: Vorteig 3 000 g (Obergrenze 5 000 g), Hauptteig G = 14 800 g
VORTEIG = recipe([line(1, ROGGEN, 1500), line(2, WASSER, 1500)], rid=2, name="Vorteig", limit_g=5000)
BROT = recipe([
    Line(position=1, amount_g=3000, sub=VORTEIG),
    line(2, MEHL, 7000), line(3, WASSER, 4500), line(4, SALZ, 200), line(5, HEFE, 100),
], rid=3, name="Mischbrot")


def total_order(target, **kw):
    return Order(basis=Basis("total", target), parts=({"kind": "total", "label": "Gesamtteig", "g": target},), **kw)


# -- plan_doughs (R06-34 bis R06-41) ---------------------------------------------------------------------

@pytest.mark.parametrize("demand, limit, count, mode, expected", [
    (32000, 20000, None, "fill", [20000, 12000]),          # Beispiel V06-2: voll auffüllen
    (32000, 20000, None, "even", [16000, 16000]),          # gleichmäßig
    (32000, 20000, 3, "even", [10667, 10667, 10667]),      # 32 000 ÷ 3 = 10 666,7 → aufgerundet
    (32000, 20000, 3, "fill", None),                       # 20 000 + 20 000 + (−8 000): nicht wählbar
    (40500, 20000, None, "fill", [20000, 20000, 500]),     # Beispiel 17.5
    (40500, 20000, None, "even", [13500, 13500, 13500]),
    (20000, 20000, None, "fill", [20000]),                 # R06-33: 1 × aktive Chargengröße = ein Teig
    (12000, 20000, None, "fill", [12000]),
    (12000, 20000, 2, "even", [6000, 6000]),               # mehr Teige als nötig (VC06-d)
    (12000, 20000, 2, "fill", None),                       # voll auffüllen ergäbe einen leeren Teig
    (5000, None, None, "fill", [5000]),                    # ohne Obergrenze keine Teilung
])
def test_plan_doughs(demand, limit, count, mode, expected):
    if expected is None:
        with pytest.raises(ValidationError) as exc:
            plan_doughs(demand, limit, count, mode)
        assert exc.value.code == "fill_empty_dough"
        assert "gleichmäßig" in exc.value.message
    else:
        assert plan_doughs(demand, limit, count, mode) == expected


def test_plan_doughs_errors():
    with pytest.raises(ValidationError, match="Mindestens 2 Teige nötig") as exc:
        plan_doughs(32000, 20000, 1)                        # P06-14: nur erhöhbar
    assert exc.value.field == "dough_count"
    with pytest.raises(ValidationError, match="Höchstens 50 Teige"):
        plan_doughs(1_000_000, 10000)                       # P06-16: 100 Teige nötig
    with pytest.raises(ValidationError, match="Höchstens 50 Teige"):
        plan_doughs(32000, 20000, 51, "even")
    with pytest.raises(ValidationError, match="nur mit einer Obergrenze"):
        plan_doughs(5000, None, 2)
    with pytest.raises(ValidationError, match="voll auffüllen"):
        plan_doughs(5000, 2000, None, "half")


def test_min_doughs():
    assert min_doughs(32000, 20000) == 2
    assert min_doughs(40001, 20000) == 3
    assert min_doughs(20000, 20000) == 1
    assert min_doughs(99999, None) == 1


def test_even_never_above_limit():
    """R06-41: bei n ≥ Mindestanzahl ist der gleichmäßige Teig nie größer als die Obergrenze."""
    for demand in range(39990, 60011, 7):
        n_min = min_doughs(demand, 20000)
        for count in range(n_min, n_min + 4):
            doughs = plan_doughs(demand, 20000, count, "even")
            assert max(doughs) <= 20000 and 0 <= sum(doughs) - demand < count


# -- Faktor (R06-24 bis R06-26) ----------------------------------------------------------------------

def test_factor_alone_scales_lines():
    """Faktor 1,5: 6 000 → 9 000, 3 800 → 5 700, 120 → 180, 80 → 120; Bedarf 15 000 g."""
    result = calculate_order(TEIG, Order(basis=Basis("factor", 1, factor=Fraction(3, 2))))
    assert targets(result) == [9000, 5700, 180, 120]
    assert result["demand"]["target_g"] == 15000
    assert result["basis"]["type"] == "factor" and result["basis"]["factor_hundredths"] == 150
    assert result["demand"]["parts"][0]["kind"] == "factor"
    assert [h["count_tenths"] for h in result["piece_hints"]] == [2307]   # 15 000 ÷ 65 = 230,76 → 230,7


def test_factor_with_fraction_rounds_demand_up():
    """G = 333 g, Faktor 1,5 → 499,5 g, Bedarf aufgerundet 500 g (K06-8); Zeilen mit genau 1,5 (R06-25)."""
    small = recipe([line(1, MEHL, 200), line(2, WASSER, 133)])
    result = calculate_order(small, Order(basis=Basis("factor", 1, factor=Fraction(3, 2))))
    assert result["demand"] == {"exact": "499.5", "target_g": 500, "parts": result["demand"]["parts"]}
    assert targets(result) == [300, 200]                     # 199,5 → 200
    # mit Obergrenze 250 g: Bedarf 500 → 2 Teige als Gesamtteig 250 g
    split = calculate_order(small, Order(basis=Basis("factor", 1, factor=Fraction(3, 2)), limit_g=250,
                                         limit_source="order"))
    assert [d["target_g"] for d in split["doughs"]] == [250, 250]
    assert targets(split["doughs"][1]["result"]) == [151, 100]   # 250 × 200/333 = 150,15; 250 × 133/333 = 99,85


# -- Kombinieren (R06-19 bis R06-23) -----------------------------------------------------------------

def combined(*parts, factor=None, **kw):
    target = sum(p["g"] for p in parts)
    return Order(basis=Basis("combined", max(target, 1)), parts=tuple(parts), factor=factor, **kw)


def part(kind, g, label="x", count=1):
    return {"kind": kind, "label": label, "count": count, "g": g}


def test_combined_example_without_limit():
    """17.2: 5 kg + 100 × 65 g + 2 × 12 kg + Faktor 0,5 × 10 000 → B = 5 000 + 6 500 + 24 000 + 5 000 = 40 500 g."""
    result = calculate_order(TEIG, combined(part("total", 5000), part("pieces", 6500, "Stück", 100),
                                            part("batch_size", 24000, "Großer Teig", 2), factor=Fraction(1, 2)))
    assert result["demand"]["target_g"] == 40500
    assert [p["kind"] for p in result["demand"]["parts"]] == ["total", "pieces", "batch_size", "factor"]
    assert result["demand"]["parts"][-1]["exact_g"] == "5000"
    # 40 500 / 10 000 = 4,05: 24 300 · 15 390 · 486 · 324
    assert targets(result) == [24300, 15390, 486, 324]
    assert result["basis"]["type"] == "combined" and result["basis"]["target_g"] == 40500
    assert len(result["doughs"]) == 1 and result["split"]["count"] == 1
    # R06-23: Stückhinweis, weil nicht nur Stückzahlen
    assert result["piece_hints"][0]["count_tenths"] == 6230       # 40 500 ÷ 65 = 623,07


def test_single_entry_equals_previous_result():
    """R06-22: eine einzelne Angabe ergibt genau dasselbe Ergebnis wie bisher."""
    before = calculate(TEIG, Basis("total", 7500))
    now = calculate_order(TEIG, combined(part("total", 7500)))
    assert targets(now) == targets(before)
    assert now["totals"] == before["totals"]
    plain = calculate_order(TEIG, total_order(7500))
    assert {k: plain[k] for k in before} | {"basis": before["basis"]} == before | {"warnings": plain["warnings"]}


def test_pieces_only_has_no_piece_hints():
    result = calculate_order(TEIG, combined(part("pieces", 6500, "Stück", 100), pieces_only=True))
    assert result["piece_hints"] == [] and result["order_totals"]["piece_hints"] == []


# -- Teilen (R06-34 bis R06-43) --------------------------------------------------------------------

def test_combined_split_fill_with_small_last_dough():
    """B = 40 500 g, L = 20 000 g, voll auffüllen: 20 000 + 20 000 + 500 g, Hinweis H06-7 (500 < 20 % von 20 000)."""
    result = calculate_order(TEIG, combined(part("total", 5000), part("pieces", 6500), part("batch_size", 24000),
                                            factor=Fraction(1, 2), limit_g=20000, limit_source="recipe"))
    assert [d["target_g"] for d in result["doughs"]] == [20000, 20000, 500]
    assert targets(result["doughs"][0]["result"]) == [12000, 7600, 240, 160]
    assert targets(result["doughs"][2]["result"]) == [300, 190, 6, 4]
    assert targets(result) == [12000, 7600, 240, 160]                 # oberste Ebene = Teig 1
    assert result["split"] == {"limit_g": 20000, "limit_source": "recipe", "limit_label": None, "min_count": 3,
                               "count": 3, "mode": "fill", "needs_question": False, "split": True,
                               "sub_question": False}
    assert "last_dough_small" in codes(result)
    assert "Letzter Teig nur 500 g" in result["warnings"][0]["text"]
    totals = result["order_totals"]
    assert totals["target_g"] == 40500 and totals["rounded_sum_g"] == 40500
    assert totals["flour_g"] == 24300
    summary = {r["raw_material"]["name"]: r["target_g"] for r in result["order_summary"]}
    assert summary == {"Weizenmehl 550": 24300, "Wasser": 15390, "Speisesalz": 486, "Hefe frisch": 324}


def test_split_even_rounding_hint():
    """32 000 g gleichmäßig in 3 Teige: 3 × 10 667 = 32 001 g, Hinweis H06-10."""
    result = calculate_order(TEIG, total_order(32000, limit_g=20000, limit_source="recipe", dough_count=3,
                                               split_mode="even"))
    assert [d["target_g"] for d in result["doughs"]] == [10667] * 3
    assert result["order_totals"]["target_g"] == 32001
    hint = next(w for w in result["warnings"] if w["code"] == "even_rounded")
    assert hint["text"] == "Summe der Teige 32 001 g statt 32 000 g (Aufrunden)."
    assert result["split"]["mode"] == "even" and result["split"]["min_count"] == 2


def test_no_split_below_limit_and_no_limit():
    result = calculate_order(TEIG, total_order(12000, limit_g=20000, limit_source="recipe"))
    assert len(result["doughs"]) == 1 and result["split"]["mode"] is None and result["split"]["split"] is False
    free = calculate_order(TEIG, total_order(50000))
    assert len(free["doughs"]) == 1 and free["split"]["limit_g"] is None


def test_overrides_apply_to_all_doughs():
    """R06-43: Mengenänderung (Salz 240 statt 120 → G = 10 120) gilt für jeden Teig."""
    result = calculate_order(TEIG, total_order(40480, limit_g=20240, limit_source="order"), overrides={3: 240})
    assert [d["target_g"] for d in result["doughs"]] == [20240, 20240]
    for dough in result["doughs"]:
        assert targets(dough["result"]) == [12000, 7600, 480, 160]


# -- Mehl gesamt / Leitrohstoff mit Obergrenze (R06-50 bis R06-52) --------------------------------------

def flour_order(target, **kw):
    return Order(basis=Basis("flour_total", target), limit_g=15000, limit_source="recipe", **kw)


def test_flour_total_over_limit_asks():
    """Mehl 12 000 g → Teig 20 000 g > 15 000 g: Rückfrage; ohne Antwort und bei „Nein“ ein Teig mit H06-8."""
    for answer in (None, False):
        result = calculate_order(TEIG, flour_order(12000, split=answer))
        assert result["split"]["needs_question"] is True and result["split"]["split"] is False
        assert len(result["doughs"]) == 1 and targets(result) == [12000, 7600, 240, 160]
        assert "over_limit" in codes(result)
        assert result["split"]["min_count"] == 2


def test_flour_total_split_yes():
    """„Ja“: B = 20 000 g, mindestens 2 Teige, voll auffüllen 15 000 + 5 000 g, jeder als Gesamtteig."""
    result = calculate_order(TEIG, flour_order(12000, split=True))
    assert [d["target_g"] for d in result["doughs"]] == [15000, 5000]
    assert targets(result["doughs"][0]["result"]) == [9000, 5700, 180, 120]
    assert result["doughs"][0]["result"]["basis"]["type"] == "total"
    assert result["basis"]["type"] == "flour_total" and result["basis"]["target_g"] == 12000
    assert "over_limit" not in codes(result)


def test_flour_total_below_limit_no_question():
    result = calculate_order(TEIG, flour_order(6000))
    assert result["split"]["needs_question"] is False and len(result["doughs"]) == 1
    with pytest.raises(ValidationError, match="teilen: Ja"):
        calculate_order(TEIG, flour_order(6000, dough_count=2))


def test_leading_material_split_sum_hint():
    """Salz 301 g → Teig 25 083,3 g → B = 25 084 g; gleichmäßig 2 × 12 542 g: Salz je 150,5 → 151 g, zusammen
    302 g statt 301 g → Hinweis H06-6 für den ganzen Auftrag (R06-52)."""
    order = Order(basis=Basis("raw_material", 301, SALZ.id), limit_g=20000, limit_source="recipe", split=True,
                  split_mode="even")
    result = calculate_order(TEIG, order)
    assert result["demand"]["target_g"] == 25084
    assert [d["target_g"] for d in result["doughs"]] == [12542, 12542]
    assert [targets(d["result"])[2] for d in result["doughs"]] == [151, 151]
    hint = next(w for w in result["warnings"] if w["code"] == "basis_rounded")
    assert "302 g statt 301 g" in hint["text"]


# -- Vorteig bei geteilten Teigen (R06-44 bis R06-49) ---------------------------------------------------

def brot_order(target, **kw):
    return total_order(target, limit_g=14801, limit_source="recipe", split_mode="even", **kw)


def test_sub_orders_per_dough_and_for_all():
    """B = 29 601 g, L = 14 801, gleichmäßig 2 × 14 801 g. Vorteig-Zeile je Teig: 3 000 × 14 801/14 800 =
    3 000,2 → 3 001 g. Je Teig: 2 Aufträge à 3 001 g; für alle: ein Auftrag 6 002 g (über 5 000 g → H06-9)."""
    per = calculate_order(BROT, brot_order(29601))
    assert [d["target_g"] for d in per["doughs"]] == [14801, 14801]
    assert per["split"]["sub_question"] is True
    assert [(s["mode"], s["dough_index"], s["target_g"]) for s in per["sub_orders"]] == [
        ("per_dough", 1, 3001), ("per_dough", 2, 3001)]
    assert per["sub_orders"][0]["sub_recipe"]["name"] == "Vorteig"

    for_all = calculate_order(BROT, brot_order(29601, sub_modes={1: "all"}))
    assert [(s["mode"], s["dough_index"], s["target_g"]) for s in for_all["sub_orders"]] == [("all", None, 6002)]
    hint = next(w for w in for_all["warnings"] if w["code"] == "sub_over_limit")
    assert "6 002 g" in hint["text"] and "5 000 g" in hint["text"]

    # Zusammenfassung des ganzen Auftrags (R06-58): je Teig wird der Vorteig zweimal mit 3 001 g gerechnet
    # (Roggen 1 500,5 → 1 501 g je Teig = 3 002 g), für alle einmal mit 6 002 g (Roggen genau 3 001 g)
    def summary(result):
        return {r["raw_material"]["name"]: r["target_g"] for r in result["order_summary"]}
    assert summary(per)["Roggenmehl 1150"] == 3002
    assert summary(for_all)["Roggenmehl 1150"] == 3001
    # Wasser: Hauptteig 4 500 × 14 801/14 800 = 4 500,3 → 4 501 g je Teig; dazu Vorteig
    assert summary(per)["Wasser"] == 2 * 4501 + 2 * 1501
    assert summary(for_all)["Wasser"] == 2 * 4501 + 3001
    assert summary(per)["Weizenmehl 550"] == 2 * 7001


def test_one_dough_has_one_sub_order_without_question():
    result = calculate_order(BROT, total_order(14800))
    assert result["split"]["sub_question"] is False
    assert [(s["mode"], s["dough_index"], s["target_g"]) for s in result["sub_orders"]] == [("all", None, 3000)]
    assert result["order_summary"] == result["summary"]


def test_sub_mode_must_name_sub_line():
    with pytest.raises(ValidationError, match="kein Unterrezept"):
        calculate_order(BROT, brot_order(29601, sub_modes={2: "all"}))
    with pytest.raises(ValidationError, match="je Teig"):
        calculate_order(BROT, brot_order(29601, sub_modes={1: "half"}))


def test_warnings_are_merged_without_duplicates():
    """Hinweise der Teige erscheinen auf oberster Ebene nur einmal (z. B. starkes Aufrunden in jedem Teig)."""
    result = calculate_order(TEIG, total_order(300, limit_g=100, limit_source="order", split_mode="even"))
    assert [d["target_g"] for d in result["doughs"]] == [100, 100, 100]
    texts = [w["text"] for w in result["warnings"]]
    assert len(texts) == len(set(texts))
