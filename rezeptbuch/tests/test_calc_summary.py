"""Tests Modul 06, Teil C2: Ansicht „Zusammenfassung“ und Mehlmischung (docs/berechnung.md 17.8).

Regeln R06-53 bis R06-57 (VC06-f, K06-10). Testdaten wie in ``test_calc_engine.py``, Sollwerte
von Hand nachgerechnet.
"""

from app.calculation.engine import Basis, calculate

from test_calc_engine import BROETCHEN, BROT, KAESEKUCHEN, ROGGEN, MEHL, WASSER, line, recipe


def _by_id(result):
    return {row["raw_material"]["id"]: row for row in result["summary"]}


def test_each_raw_material_once_in_order_of_first_occurrence():
    result = calculate(BROT, Basis("total", 14800))
    # Vorteig steht an Position 1: Roggen und Wasser kommen dort zuerst vor (R06-57)
    assert [row["raw_material"]["name"] for row in result["summary"]] == [
        "Roggenmehl 1150", "Wasser", "Weizenmehl 550", "Speisesalz", "Hefe frisch"]
    # keine Unterrezept-Zeile in der Zusammenfassung (R06-53)
    assert all(row["raw_material"] for row in result["summary"])


def test_sum_over_all_levels():
    rows = _by_id(calculate(BROT, Basis("total", 14800)))
    assert rows[WASSER.id]["target_g"] == 6000            # 1 500 im Vorteig + 4 500 im Hauptteig
    assert rows[ROGGEN.id]["target_g"] == 1500
    assert rows[MEHL.id]["target_g"] == 7000


def test_sum_uses_rounded_amounts_that_are_weighed():
    # f = 1 000 / 14 800 = 5/74; Vorteig 202,7 → 203 g, darin Wasser 101,5 → 102 g;
    # Wasser im Hauptteig 304,05 → 305 g; gewogen 407 g (R06-54, K06-10)
    rows = _by_id(calculate(BROT, Basis("total", 1000)))
    assert rows[WASSER.id]["target_g"] == 102 + 305
    assert rows[WASSER.id]["exact_g"] == "405.554"


def test_share_and_baker_percent_from_base_recipe():
    rows = _by_id(calculate(BROT, Basis("total", 14800)))
    assert rows[WASSER.id]["share_tenths"] == 405          # 6 000 / 14 800 = 40,54 %
    assert rows[WASSER.id]["baker_tenths"] == 706          # 6 000 / 8 500 = 70,59 %
    assert rows[ROGGEN.id]["baker_tenths"] + rows[MEHL.id]["baker_tenths"] == 1000   # R06-55
    small = _by_id(calculate(BROT, Basis("total", 1000)))
    assert small[WASSER.id]["baker_tenths"] == 706         # unabhängig von der Skalierung


def test_flour_mix():
    result = calculate(BROT, Basis("total", 14800))
    assert [(m["name"], m["flour_tenths"]) for m in result["flour_mix"]] == [
        ("Roggenmehl 1150", 176), ("Weizenmehl 550", 824)]      # R06-56


def test_flour_mix_single_flour_is_100_percent():
    result = calculate(BROETCHEN, Basis("total", 16700))
    assert [m["flour_tenths"] for m in result["flour_mix"]] == [1000]


def test_no_flour_no_mix_and_no_baker_percent():
    result = calculate(KAESEKUCHEN, Basis("total", 7260))
    assert result["flour_mix"] == []
    assert all(row["baker_tenths"] is None for row in result["summary"])


def test_hand_addition_is_shown_as_needed():
    rows = {row["raw_material"]["name"]: row for row in calculate(KAESEKUCHEN, Basis("total", 7260))["summary"]}
    vanille = rows["Vanille"]
    assert vanille["hand_only"] is True and vanille["target_g"] == 0      # „nach Bedarf“ (R06-57)
    assert rows["Zucker"]["hand_only"] is False


def test_hand_and_weighed_line_of_same_material():
    r = recipe([line(1, MEHL, 1000), line(2, WASSER, 600), line(3, WASSER, 0)])
    row = _by_id(calculate(r, Basis("total", 1600)))[WASSER.id]
    assert row["target_g"] == 600 and row["hand_only"] is False and row["has_hand"] is True
