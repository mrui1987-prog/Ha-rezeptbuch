import pytest

from app.units import grams_to_kg_text, kg_to_grams


@pytest.mark.parametrize(
    "value, expected",
    [
        ("9,500", 9500),
        ("9.5", 9500),
        ("0,0005", 1),  # kaufmännisch gerundet
        (" 25 ", 25000),
        (2, 2000),
        ("0,095", 95),
    ],
)
def test_kg_to_grams(value, expected):
    assert kg_to_grams(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "1,2,3"])
def test_kg_to_grams_invalid(value):
    with pytest.raises(ValueError):
        kg_to_grams(value)


@pytest.mark.parametrize(
    "grams, expected",
    [(9500, "9,500"), (95, "0,095"), (0, "0,000"), (-200, "-0,200")],
)
def test_grams_to_kg_text(grams, expected):
    assert grams_to_kg_text(grams) == expected
