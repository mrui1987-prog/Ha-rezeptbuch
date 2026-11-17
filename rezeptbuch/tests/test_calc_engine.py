"""Tests Modul 06: Rechenregeln ohne Datenbank (docs/berechnung.md Abschnitt 4, 5, 11).

Die Referenzrezepte sind Testdaten, keine Betriebsdaten. Die erwarteten Sollwerte sind von
Hand nachgerechnet (Rechenweg im Kommentar).
"""

from fractions import Fraction

import pytest

from app.calculation.engine import (
    Basis,
    Line,
    Material,
    PieceWeight,
    Recipe,
    calculate,
    decimal_text,
    flour_g,
    leading_materials,
    material_g,
    round_up_g,
    split_units,
    tolerance_g,
    walk_items,
)
from app.errors import ValidationError

# -- Testrohstoffe ------------------------------------------------------------------------

MEHL = Material(1, 1, "Weizenmehl 550", "flour", "percent", 20)
ROGGEN = Material(2, 2, "Roggenmehl 1150", "flour", "percent", 20)
WASSER = Material(3, 3, "Wasser", "standard", "g", 50)
SALZ = Material(4, 4, "Speisesalz", "standard", "g", 2, display_name="Salz")
HEFE = Material(5, 5, "Hefe frisch", "standard", "g", 5)
BACKMITTEL = Material(6, 6, "Backmittel", "standard", "g", 5)
QUARK = Material(7, 7, "Speisequark 20 %", "standard", "percent", 10, display_name="Quark")
ZUCKER = Material(8, 8, "Zucker", "standard", "g", 10)
EI = Material(9, 9, "Vollei", "standard", "g", 10, unit_size_g=55, unit_label="Ei")
STAERKE = Material(10, 10, "Speisestärke", "standard", "percent", 0)
VANILLE = Material(11, 11, "Vanille", "standard", "g", 0)
SACKMEHL = Material(12, 12, "Mehl Sack", "flour", "percent", 20, unit_size_g=25000, unit_label="Sack")


def line(position, material, amount, **kw):
    return Line(position=position, amount_g=amount, material=material, **kw)


def sub_line(position, recipe, amount, **kw):
    return Line(position=position, amount_g=amount, sub=recipe, **kw)


def recipe(lines, rid=100, name="Testrezept", **kw):
    return Recipe(id=rid, number=rid, name=name, lines=tuple(lines), **kw)


def targets(result):
    return [i["target_g"] for i in result["items"]]


# Brötchenteig: G = 16 700 g, Mehl 10 000 g
BROETCHEN = recipe([
    line(1, MEHL, 10000), line(2, WASSER, 5800), line(3, HEFE, 400), line(4, SALZ, 200), line(5, BACKMITTEL, 300),
], rid=1, name="Brötchenteig", piece_weights=(PieceWeight(1, "Stück", 65), PieceWeight(2, "Ballen", 1550)),
    knead_slow_min=5, knead_fast_min=6)

# Brot mit Vorteig: Vorteig 3 000 g (halb Mehl), Hauptteig G = 14 800 g, M = 7 000 + 1 500 = 8 500 g
VORTEIG = recipe([line(1, ROGGEN, 1500), line(2, WASSER, 1500)], rid=2, name="Vorteig", locked=True)
BROT = recipe([
    sub_line(1, VORTEIG, 3000, step_no=1, step_name="Vorteig"),
    line(2, MEHL, 7000, step_no=2, step_name="Hauptteig"),
    line(3, WASSER, 4500, step_no=2, step_name="Hauptteig"),
    line(4, SALZ, 200, step_no=2, step_name="Hauptteig"),
    line(5, HEFE, 100, step_no=2, step_name="Hauptteig"),
], rid=3, name="Mischbrot")

# Käsekuchen: G = 7 260 g, kein Mehl; 1 Kuchen = 2 400 g
KAESEKUCHEN = recipe([
    line(1, QUARK, 5000), line(2, ZUCKER, 800), line(3, EI, 1160), line(4, STAERKE, 300), line(5, VANILLE, 0),
], rid=4, name="Käsekuchen", piece_weights=(PieceWeight(3, "Käsekuchen", 2400),))


# -- Kleine Regeln --------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (Fraction(3121, 10), 313),   # 312,1 g → 313 g (R06-1)
    (Fraction(312), 312),        # genau 312 g bleibt
    (Fraction(1, 1000), 1),      # sehr klein → 1 g (R06-2)
    (Fraction(0), 0),            # 0 g bleibt 0 g
])
def test_round_up(value, expected):
    assert round_up_g(value) == expected


@pytest.mark.parametrize("target, unit, value, expected", [
    (312, "percent", 20, 6),     # 2 % von 312 g = 6,24 g → 6 g (R06-8)
    (30, "percent", 20, 1),      # 0,6 g → mindestens 1 g
    (312, "percent", 0, 1),      # 0 % wird mit ±1 g gewogen
    (312, "percent", 25, 7),     # 2,5 % = 7,8 g → 7 g
    (30000, "percent", 20, 600), # Sack: Prozent von der ganzen Sollmenge (K06-2)
    (500, "g", 20, 20),
    (500, "g", 0, 0),            # 0 g = Sollhandzugabe
    (0, "percent", 20, 0),       # Handzugabe nach Bedarf: keine Toleranz
])
def test_tolerance(target, unit, value, expected):
    assert tolerance_g(target, unit, value) == expected


@pytest.mark.parametrize("target, size, expected", [
    (580, 55, (10, 30)),
    (30000, 25000, (1, 5000)),
    (550, 55, (10, 0)),
    (40, 55, (0, 40)),
    (500, None, (0, 500)),
])
def test_split_units(target, size, expected):
    assert split_units(target, size) == expected


def test_decimal_text():
    assert decimal_text(Fraction(3121, 10)) == "312.1"
    assert decimal_text(Fraction(312)) == "312"
    assert decimal_text(Fraction(2, 3)) == "0.667"
    assert decimal_text(Fraction(1, 2), 0) == "1"


# -- Grundgrößen ------------------------------------------------------------------------

def test_flour_includes_sub_recipes():
    assert flour_g(BROT) == 8500                      # Beispiel aus Abschnitt 4.1
    assert material_g(BROT, WASSER.id) == 6000        # 4 500 + 3 000 × 1 500 / 3 000


def test_flour_over_two_levels():
    inner = recipe([line(1, ROGGEN, 100), line(2, WASSER, 100)], rid=20, name="Sauer")
    middle = recipe([sub_line(1, inner, 200), line(2, MEHL, 200)], rid=21, name="Vorteig")   # 300 Mehl von 400
    main = recipe([sub_line(1, middle, 800), line(2, MEHL, 1000), line(3, WASSER, 700)], rid=22)
    assert flour_g(main) == 1000 + Fraction(800 * 300, 400)   # 1 600 g


# -- Bezugsgrößen ---------------------------------------------------------------------

def test_total_rounds_every_line_up():
    r = recipe([line(1, MEHL, 3121), line(2, WASSER, 6879)])
    result = calculate(r, Basis("total", 1000))
    assert targets(result) == [313, 688]             # 312,1 → 313; 687,9 → 688
    assert result["totals"]["target_g"] == 1000
    assert result["totals"]["rounded_sum_g"] == 1001  # Summe darf darüber liegen (R06-3)
    assert result["items"][0]["exact_g"] == "312.1"


def test_no_floating_point_errors():
    r = recipe([line(1, MEHL, 300), line(2, WASSER, 300), line(3, ZUCKER, 300)])
    result = calculate(r, Basis("total", 300))         # Faktor 1/3
    assert targets(result) == [100, 100, 100]
    assert result["basis"]["factor"] == "1/3"


def test_pieces_reference_broetchen():
    # 2 Ballen × 1 550 g + 30 Stück × 65 g = 5 050 g; f = 5 050 / 16 700
    result = calculate(BROETCHEN, Basis("pieces", 5050), piece_hints=False)
    # Mehl 3 023,95 → 3 024; Wasser 1 753,89 → 1 754; Hefe 120,96 → 121; Salz 60,48 → 61; Backmittel 90,72 → 91
    assert targets(result) == [3024, 1754, 121, 61, 91]
    assert result["totals"]["rounded_sum_g"] == 5051
    assert result["piece_hints"] == []
    assert result["totals"]["knead"] == "5+6"


def test_flour_total_with_vorteig():
    result = calculate(BROT, Basis("flour_total", 4250))          # f = 4 250 / 8 500 = 1/2
    assert targets(result) == [1500, 3500, 2250, 100, 50]
    sub = result["items"][0]
    assert sub["kind"] == "sub_recipe"
    assert [i["target_g"] for i in sub["sub"]["items"]] == [750, 750]
    assert sub["sub"]["totals"]["target_g"] == 1500
    assert result["totals"]["flour_g"] == 4250


def test_baker_percent_of_all_flour_lines_add_up_to_100():
    result = calculate(BROT, Basis("total", 14800))
    flour_lines = [i for i in walk_items(result["items"])
                   if i["raw_material"] and i["raw_material"]["type"] == "flour"]
    assert [i["baker_tenths"] for i in flour_lines] == [176, 824]   # Roggen im Vorteig 17,6 %, Weizen 82,4 %
    assert sum(i["baker_tenths"] for i in flour_lines) == 1000
    assert result["items"][2]["baker_tenths"] == 529                 # Wasser 4 500 / 8 500 = 52,94 %
    assert result["items"][2]["share_tenths"] == 304                 # 4 500 / 14 800 = 30,41 %


def test_percentages_do_not_change_with_scaling():
    small = calculate(BROT, Basis("total", 1000))
    big = calculate(BROT, Basis("total", 50000))
    assert [i["baker_tenths"] for i in small["items"]] == [i["baker_tenths"] for i in big["items"]]


def test_no_baker_percent_without_flour():
    result = calculate(KAESEKUCHEN, Basis("total", 7260))
    assert all(i["baker_tenths"] is None for i in result["items"])
    assert result["totals"]["has_flour"] is False


def test_flour_total_without_flour_is_refused():
    with pytest.raises(ValidationError, match="kein Mehl") as exc:
        calculate(KAESEKUCHEN, Basis("flour_total", 1000))
    assert exc.value.field == "basis_type"


# -- Leitrohstoff (K06-1) ------------------------------------------------------------------

def test_leading_material_total_over_sub_recipe():
    result = calculate(BROT, Basis("raw_material", 3000, raw_material_id=WASSER.id))   # 6 000 → 3 000, f = 1/2
    assert targets(result) == [1500, 3500, 2250, 100, 50]
    assert result["warnings"] == []     # gesperrtes Unterrezept ist kein Hinweis (M05-5)


def test_leading_material_single_line_gives_exact_amount():
    # Wasser im Hauptteig 4 500 → 3 000, f = 2/3
    result = calculate(BROT, Basis("raw_material", 3000, raw_material_id=WASSER.id, item_position=3))
    assert targets(result) == [2000, 4667, 3000, 134, 67]
    assert [i["target_g"] for i in result["items"][0]["sub"]["items"]] == [1000, 1000]


def test_leading_material_quark_with_piece_hint():
    result = calculate(KAESEKUCHEN, Basis("raw_material", 7500, raw_material_id=QUARK.id))   # f = 1,5
    assert targets(result) == [7500, 1200, 1740, 450, 0]
    eggs = result["items"][2]
    assert eggs["units"] == {"size_g": 55, "label": "Ei", "count": 31, "rest_g": 35}
    assert eggs["tolerance"]["tolerance_g"] == 10                     # ganze Toleranz für den Rest (M02-2d)
    # 10 890 g / 2 400 g = 4,54 → 4,5 Käsekuchen (abgerundet, R06-17)
    assert result["piece_hints"] == [{"id": 3, "label": "Käsekuchen", "weight_g": 2400, "count_tenths": 45}]


def test_leading_material_total_rounding_above_input_gives_hint():
    r = recipe([line(1, QUARK, 333), line(2, QUARK, 667), line(3, ZUCKER, 100)])
    result = calculate(r, Basis("raw_material", 7500, raw_material_id=QUARK.id))   # f = 7,5
    assert targets(result) == [2498, 5003, 750]                     # 2 497,5 → 2 498; 5 002,5 → 5 003
    texts = [w["text"] for w in result["warnings"] if w["code"] == "basis_rounded"]
    assert texts == ["Quark: 7501 g statt 7500 g (Aufrunden mehrerer Zeilen)."]


def test_leading_material_not_in_recipe():
    with pytest.raises(ValidationError, match="nicht vor") as exc:
        calculate(KAESEKUCHEN, Basis("raw_material", 1000, raw_material_id=MEHL.id))
    assert exc.value.field == "raw_material_id"


@pytest.mark.parametrize("position", [1, 2, 99])
def test_leading_material_line_must_belong_to_material(position):
    # Zeile 1 ist ein Unterrezept, Zeile 2 Mehl, 99 gibt es nicht
    with pytest.raises(ValidationError) as exc:
        calculate(BROT, Basis("raw_material", 1000, raw_material_id=WASSER.id, item_position=position))
    assert exc.value.field == "item_position"


def test_leading_material_hand_line_is_refused():
    with pytest.raises(ValidationError):
        calculate(KAESEKUCHEN, Basis("raw_material", 10, raw_material_id=VANILLE.id, item_position=5))
    with pytest.raises(ValidationError, match="nicht vor"):
        calculate(KAESEKUCHEN, Basis("raw_material", 10, raw_material_id=VANILLE.id))


def test_leading_materials_offer_total_and_lines():
    options = leading_materials(BROT)
    assert [o["name"] for o in options] == ["Roggenmehl 1150", "Wasser", "Weizenmehl 550", "Speisesalz",
                                             "Hefe frisch"]
    water = options[1]
    assert water["amount_g"] == 6000
    assert water["lines"] == [{"position": 3, "step_name": "Hauptteig", "amount_g": 4500}]
    assert options[0]["lines"] == []          # nur im Vorteig: nur „gesamt“
    assert options[2]["lines"] == []          # nur eine Zeile: nur „gesamt“
    assert all(o["raw_material_id"] != VANILLE.id for o in leading_materials(KAESEKUCHEN))   # 0 g nicht wählbar


# -- Zeilen: Handzugabe, Toleranz, Gebinde ---------------------------------------------

def test_hand_addition_and_hand_ack():
    result = calculate(KAESEKUCHEN, Basis("total", 7260))
    vanille = result["items"][4]
    assert vanille["kind"] == "hand" and vanille["target_g"] == 0 and vanille["tolerance"] is None
    r = recipe([line(1, MEHL, 1000), line(2, Material(30, 30, "Gewürz", "standard", "g", 0), 10)])
    spice = calculate(r, Basis("total", 1010))["items"][1]
    assert spice["tolerance"]["is_hand_ack"] is True and spice["tolerance"]["tolerance_g"] == 0


def test_line_tolerance_overrides_material():
    r = recipe([line(1, MEHL, 1000, tolerance_unit="g", tolerance_value=3)])
    item = calculate(r, Basis("total", 1000))["items"][0]
    assert item["tolerance"] == {"unit": "g", "value": 3, "tolerance_g": 3, "is_hand_ack": False}


def test_zero_percent_is_weighed_with_one_gram_and_warned():
    result = calculate(KAESEKUCHEN, Basis("total", 7260))
    starch = result["items"][3]
    assert starch["tolerance"]["tolerance_g"] == 1
    assert any(w["code"] == "tolerance_zero_percent" for w in result["warnings"])


def test_sack_plus_rest_with_percent_tolerance():
    r = recipe([line(1, SACKMEHL, 30000), line(2, WASSER, 18000)])
    item = calculate(r, Basis("total", 48000))["items"][0]
    assert item["units"] == {"size_g": 25000, "label": "Sack", "count": 1, "rest_g": 5000}
    assert item["tolerance"]["tolerance_g"] == 600


def test_large_rounding_is_hinted():
    r = recipe([line(1, MEHL, 987), line(2, SALZ, 13)])
    result = calculate(r, Basis("total", 100))          # Salz 1,3 g → 2 g
    assert result["items"][1]["target_g"] == 2
    texts = [w["text"] for w in result["warnings"] if w["code"] == "rounding_large"]
    assert texts == ["Salz: Aufrunden auf 2 g statt 1,3 g (+54 %)"]


# -- Mengenänderungen, Hinweise, Fehler ------------------------------------------------

def test_override_replaces_amount_before_calculation():
    result = calculate(BROETCHEN, Basis("total", 16750), overrides={4: 250})   # Salz 200 → 250, G = 16 750
    assert targets(result) == [10000, 5800, 400, 250, 300]
    assert result["items"][3]["overridden"] is True
    assert result["items"][3]["base_g"] == 250


def test_override_unknown_position():
    with pytest.raises(ValidationError, match="Zeile 9") as exc:
        calculate(BROETCHEN, Basis("total", 1000), overrides={9: 10})
    assert exc.value.field == "overrides"


def test_override_sub_recipe_needs_amount():
    with pytest.raises(ValidationError):
        calculate(BROT, Basis("total", 1000), overrides={1: 0})


def test_piece_hint_is_rounded_down():
    # 811 g / 65 g = 12,48 → 12,4 (nicht 12,5)
    result = calculate(BROETCHEN, Basis("total", 811))
    hint = next(h for h in result["piece_hints"] if h["label"] == "Stück")
    assert hint["count_tenths"] == 124


def test_review_archived_and_locked_hints():
    archived_rm = Material(40, 40, "Alte Margarine", "standard", "g", 5, archived=True)
    archived_sub = recipe([line(1, MEHL, 100)], rid=41, name="Altes Unterrezept", archived=True)
    r = recipe([line(1, archived_rm, 100, needs_review=True), sub_line(2, archived_sub, 100)],
               locked=True, archived=True)
    codes = [w["code"] for w in calculate(r, Basis("total", 200))["warnings"]]
    assert codes.count("needs_review") == 1
    assert codes.count("archived") == 2
    assert "recipe_locked" in codes and "recipe_archived" in codes


@pytest.mark.parametrize("r, basis, field", [
    (recipe([]), Basis("total", 100), "recipe_id"),                                   # P06-3
    (recipe([line(1, VANILLE, 0)]), Basis("total", 100), "recipe_id"),                # nur Handzugabe
    (BROETCHEN, Basis("total", 0), "value"),                                          # P06-1
    (BROETCHEN, Basis("total", 1_000_001), "value"),                                  # P06-2
    (BROETCHEN, Basis("raw_material", 100_000, raw_material_id=SALZ.id), "value"),    # Teig 8 350 kg
    (BROETCHEN, Basis("unbekannt", 100), "basis_type"),
    (BROETCHEN, Basis("raw_material", 100), "raw_material_id"),
])
def test_errors(r, basis, field):
    with pytest.raises(ValidationError) as exc:
        calculate(r, basis)
    assert exc.value.field == field


def test_empty_sub_recipe_is_refused():
    empty = recipe([line(1, VANILLE, 0)], rid=50, name="Leer")
    with pytest.raises(ValidationError, match="Leer"):
        calculate(recipe([sub_line(1, empty, 100), line(2, MEHL, 100)]), Basis("total", 200))


def test_cycle_in_tree_is_refused():
    inner = recipe([line(1, MEHL, 100)], rid=60, name="A")
    outer = recipe([sub_line(1, inner, 100)], rid=60, name="A")      # gleiche ID wie das Unterrezept
    with pytest.raises(ValidationError, match="Kreis"):
        calculate(outer, Basis("total", 100))


def test_too_deep_is_refused():
    r = recipe([line(1, MEHL, 100)], rid=200)
    for level in range(11):
        r = recipe([sub_line(1, r, 100)], rid=201 + level, name=f"Ebene {level}")
    with pytest.raises(ValidationError, match="10 Ebenen"):
        calculate(r, Basis("total", 100))
