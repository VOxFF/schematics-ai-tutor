import copy

import pytest

from app.task_spec import build_level, check_format, derive_task_board, normalize
from tests.conftest import as_claude_output, load_example


@pytest.mark.parametrize("name", ["closed_loop", "voltage_divider", "parallel_paths"])
def test_examples_pass_format_checks(name):
    assert check_format(load_example(name)) == []


def test_claude_output_normalizes_to_the_grid_format():
    spec = normalize(as_claude_output(load_example()))
    assert spec == load_example()


def test_derive_task_board_moves_removed_parts_to_inventory():
    board = derive_task_board(load_example("voltage_divider"))
    assert "R2" not in {c["id"] for c in board["components"]}
    assert [item["id"] for item in board["inventory"]] == ["R2", "R3", "R4"]
    assert board["inventory"][0] == {"id": "R2", "type": "resistor", "value": 20}
    assert board["targets"] == {"VM1": {"value": None}}


def test_removed_wire_disappears():
    spec = load_example("closed_loop")
    board = derive_task_board(spec)
    removed = spec["removed_ids"][0]
    assert removed not in {w["id"] for w in board["wires"]}
    assert board["inventory"] == []


def test_build_level_shape():
    level = build_level(load_example(), skill_level=3)
    assert level["id"].startswith("gen-")
    assert level["order"] == 3
    assert {"title", "concept", "intro", "board"} <= set(level)


def broken(change):
    spec = copy.deepcopy(load_example("voltage_divider"))
    change(spec)
    return check_format(spec)


def test_fixed_part_cannot_be_removed():
    assert any("is fixed" in e for e in broken(lambda s: s.update(removed_ids=["R1"])))


def test_something_must_be_removed():
    assert any("at least one part" in e for e in broken(lambda s: s.update(removed_ids=[])))


def test_target_must_be_a_placed_meter():
    assert any("not a meter" in e for e in broken(lambda s: s.update(target_meter_ids=["R1"])))


def test_target_meter_cannot_be_removed():
    def remove_meter(spec):
        meter = next(c for c in spec["complete_board"]["components"] if c["id"] == "VM1")
        meter["fixed"] = False
        spec["removed_ids"] = ["VM1"]
    assert any("is removed" in e for e in broken(remove_meter))


def test_difficulty_range():
    assert any("difficulty" in e for e in broken(lambda s: s.update(difficulty=9)))


def test_grid_limits():
    errors = check_format(load_example(), {"max_points": 10})
    assert any("larger than 10" in e for e in errors)


def test_a_welcome_that_describes_locations_is_rejected():
    from app.task_spec import check_format, normalize
    spec = normalize(load_example())
    assert not [e for e in check_format(spec) if e.startswith("welcome")]
    spec["welcome"] = "Put a wire at [3, 4] and see what happens."
    assert [e for e in check_format(spec) if e.startswith("welcome")] == [
        "welcome: describes locations ([3, 4]); talk about the idea instead"]


def test_wire_shapes_are_straight_plus_the_removed_pieces_shapes():
    from app.task_spec import wire_shapes
    spec = {"removed_ids": ["W1", "W2", "R2"], "complete_board": {"wires": [
        {"id": "W1", "segments": [[[2, 2], [3, 2]], [[2, 2], [2, 3]]]},                    # corner
        {"id": "W2", "segments": [[[5, 5], [6, 5]], [[5, 5], [4, 5]], [[5, 5], [5, 6]]]},  # T
        {"id": "W3", "segments": [[[8, 1], [8, 2]], [[8, 1], [9, 1]], [[8, 1], [7, 1]], [[8, 1], [8, 0]]]},  # kept +
    ]}}
    assert wire_shapes(spec) == ["straight", "corner", "T"]
    assert wire_shapes({**spec, "removed_ids": ["R2"]}) == ["straight"]
