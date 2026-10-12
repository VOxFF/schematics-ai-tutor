"""Math check for formulas in tutor replies: the LaTeX subset, board numbers, arithmetic, rungs, answer."""

import pytest

from app.formula import answer_in_text, answer_values, board_quantities, check, parse_line, tokenize
from app.learner_profile import load_catalog
from tests.conftest import example_level

# The voltage divider example: V1 12 V, R1 40 Ω and VM1 (target 4 V) placed; R2 = 20 Ω to find.
BOARD = [(12.0, "volt"), (40.0, "ohm"), (4.0, "volt")]
ANSWERS = [(20.0, "ohm")]

SYMBOLIC = r"V_{R2} = V \cdot \frac{R_2}{R_1 + R_2}"
PARTIAL = r"4\,\mathrm{V} = 12\,\mathrm{V} \cdot \frac{R_2}{40\,\Omega + R_2}"
FULL = [r"\frac{R_2}{40\,\Omega + R_2} = \frac{4}{12}", r"2 R_2 = 40\,\Omega", r"R_2 = \frac{40\,\Omega}{2} = 20\,\Omega"]


def problems(lines, rung=0):
    return check(lines, allowed=BOARD, answers=ANSWERS, rung=rung)


def test_units_and_symbols_are_tokenized():
    assert tokenize(r"V_{R2} = 300\,\mathrm{mA} \cdot 2\,\mathrm{k\Omega}") == [
        ("sym", "V_R2"), ("=",), ("num", 0.3, "amp"), ("*",), ("num", 2000.0, "ohm")]
    assert tokenize(r"R_{\text{total}}")[0] == ("sym", r"R_\text{total}")
    assert tokenize("12 V")[0] == ("num", 12.0, "volt")
    assert tokenize("4 V_1")[1] == ("sym", "V_1")  # V with a subscript is a symbol, not a unit


def test_sides_are_computed_when_they_have_no_symbols():
    sides, approx = parse_line(r"I = \frac{12\,\mathrm{V}}{40\,\Omega} \approx 0.3\,\mathrm{A}")
    assert [s["value"] for s in sides] == [None, 0.3, 0.3] and approx


@pytest.mark.parametrize("lines,rung", [
    ([SYMBOLIC], 0), ([SYMBOLIC], 2), ([PARTIAL], 3), (FULL, 4),
    ([r"I = \frac{12\,\mathrm{V}}{40\,\Omega} = 0.3\,\mathrm{A}"], 0),
    ([r"I \approx \frac{12\,\mathrm{V}}{40\,\Omega} \approx 0.31\,\mathrm{A}"], 0),
    ([r"P = I^2 R"], 0),
    ([r"R_{\text{eq}} = \frac{1}{\frac{1}{R_1} + \frac{1}{R_2}}"], 0),
])
def test_good_formulas_pass(lines, rung):
    assert problems(lines, rung) == []


def test_catalog_formulas_parse():
    formulas = [t["formula"] for t in load_catalog().values() if "formula" in t]
    assert len(formulas) >= 5
    assert all(check([f], allowed=[], answers=[], rung=2) == [] for f in formulas)


@pytest.mark.parametrize("lines,rung,problem", [
    ([r"\sqrt{x}"], 0, "outside the subset"),
    ([r"I = \frac{12\,\mathrm{V}}{40\,\Omega} = 0.4\,\mathrm{A}"], 0, "arithmetic"),
    ([r"I = \frac{12\,\mathrm{V}}{30\,\Omega}"], 0, "30 is not a value"),
    ([r"I = \frac{12\,\Omega}{40\,\Omega}"], 0, "12 is not a value"),  # 12 V on the board, not 12 Ω
    ([PARTIAL], 2, "without the board's numbers"),
    ([r"R_2 = 20\,\Omega"], 3, "gives the answer"),
    (FULL, 3, "gives the answer"),
    ([r"R_2 = \frac{40\,\Omega}{2}"], 0, "gives the answer"),  # computed, not written
    (["x"] * 9, 4, "at most 8"),
])
def test_bad_formulas_are_named(lines, rung, problem):
    assert any(problem in p for p in problems(lines, rung))


def test_the_answer_in_the_text():
    found = answer_in_text("So R2 is 20 Ω, or 20 ohms, not 20 V; 0.02 kΩ too.", ANSWERS)
    assert found == ["20 Ω", "20 ohms", "0.02 kΩ"]
    assert answer_in_text("Two resistors share 12 V.", ANSWERS) == []


def test_board_quantities_and_answers_from_the_example():
    level, spec = example_level()
    evaluation = {"readings": {"VM1": None}}
    placed, inventory = board_quantities(level["board"], evaluation)
    assert set(placed) == {(12.0, "volt"), (40.0, "ohm"), (4.0, "volt")}
    assert set(inventory) == {(20.0, "ohm"), (40.0, "ohm"), (60.0, "ohm")}
    assert answer_values(spec["complete_board"], placed) == [(20.0, "ohm")]
    assert answer_values(None, placed) == []
    # Once a 20 Ω resistor is placed, its value is on the board and no longer the answer.
    assert answer_values(spec["complete_board"], placed + [(20.0, "ohm")]) == []
