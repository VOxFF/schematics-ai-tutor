import json

from app.jsonfmt import dumps
from tests.conftest import load_example


def test_round_trip_and_trailing_newline():
    data = load_example()
    text = dumps(data)
    assert json.loads(text) == data and text.endswith("\n")


def test_short_values_stay_on_one_line():
    assert dumps({"pins": {"a": [5, 3], "b": [7, 3]}}) == '{"pins": {"a": [5, 3], "b": [7, 3]}}\n'


def test_long_arrays_wrap_six_per_line():
    lines = dumps(list(range(14))).splitlines()
    assert lines == ["[", "  0, 1, 2, 3, 4, 5,", "  6, 7, 8, 9, 10, 11,", "  12, 13", "]"]


def test_nothing_is_squashed_into_one_long_line():
    assert max(len(line) for line in dumps(load_example()).splitlines()) <= 110
