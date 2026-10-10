import copy

import pytest

from app.grid import validate_grid, wire_shape
from tests.conftest import load_example


def example_grid(name="voltage_divider"):
    board = copy.deepcopy(load_example(name)["complete_board"])
    return {**board, "inventory": [], "targets": {}}


@pytest.mark.parametrize("name", ["closed_loop", "voltage_divider", "parallel_paths"])
def test_examples_are_valid(name):
    assert validate_grid(example_grid(name)) == []


@pytest.mark.parametrize(
    "segments, shape",
    [
        ([[[1, 1], [1, 2]]], "straight"),
        ([[[1, 1], [1, 2]], [[1, 2], [2, 2]]], "corner"),
        ([[[1, 1], [1, 2]], [[1, 2], [1, 3]]], None),  # collinear: not a corner
        ([[[2, 1], [2, 2]], [[2, 2], [3, 2]], [[1, 2], [2, 2]]], "T"),
        ([[[2, 1], [2, 2]], [[2, 2], [3, 2]], [[1, 2], [2, 2]], [[2, 3], [2, 2]]], "plus"),
        ([[[1, 1], [1, 2]], [[3, 3], [3, 4]]], None),  # disconnected
    ],
)
def test_wire_shapes(segments, shape):
    assert wire_shape(segments) == shape


def errors_after(change):
    grid = example_grid()
    change(grid)
    return validate_grid(grid)


def test_pins_must_match_orientation():
    def flip(grid):
        grid["components"][1]["orientation"] = "E"  # R1: pins say W
    assert any("pointing E" in e for e in errors_after(flip))


def test_components_must_not_overlap():
    def overlap(grid):
        r2 = next(c for c in grid["components"] if c["id"] == "R2")
        r2["pins"] = {"a": [6, 2], "b": [6, 4]}  # body on R1's body [6, 3]
        r2["orientation"] = "N"
    assert any("overlaps" in e for e in errors_after(overlap))


def test_segment_must_join_neighbors():
    def stretch(grid):
        grid["wires"][0]["segments"] = [[[2, 4], [2, 2]]]
    assert any("orthogonal neighbors" in e for e in errors_after(stretch))


def test_wire_must_not_cross_a_body():
    def cross(grid):
        grid["wires"].append({"id": "W99", "segments": [[[6, 2], [6, 3]]]})  # into R1's body
    assert any("passes through the body" in e for e in errors_after(cross))


def test_ids_must_be_unique():
    def duplicate(grid):
        grid["wires"][0]["id"] = "R1"
    assert any("duplicate id R1" in e for e in errors_after(duplicate))


def test_point_must_be_inside_grid():
    def outside(grid):
        grid["wires"].append({"id": "W99", "segments": [[[12, 8], [13, 8]]]})
    assert any("outside the grid" in e for e in errors_after(outside))


def test_target_must_name_a_meter():
    def target(grid):
        grid["targets"] = {"R1": {"value": 1.0}}
    assert any("not a meter" in e for e in errors_after(target))
