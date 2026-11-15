"""Tests: Sperre B2 (Namen wie Excel-Formeln) – Modul 05, M05-14."""

import pytest

from app.errors import ValidationError
from app.text_rules import check_no_formula_start, starts_like_formula


@pytest.mark.parametrize("text", ["=SUMME(A1)", "+49", "-Mohn", "@x", "  =x", "\t+1"])
def test_formula_start_detected(text):
    assert starts_like_formula(text)
    with pytest.raises(ValidationError) as exc:
        check_no_formula_start(text, field="name")
    assert exc.value.code == "formula_start"
    assert exc.value.field == "name"
    assert "=, +, - oder @" in exc.value.message


@pytest.mark.parametrize("text", [None, "", "   ", "Weizenmehl 550", "Mehl =gut", "Ei-Gelb", "1+1"])
def test_normal_text_allowed(text):
    assert not starts_like_formula(text)
    check_no_formula_start(text, field="name")


def test_label_in_message():
    with pytest.raises(ValidationError, match="Kurzname darf nicht"):
        check_no_formula_start("=x", field="display_name", label="Kurzname")
