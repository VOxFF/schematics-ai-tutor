"""Validation stages for generated tasks (docs/schematics.md §3)."""

import copy

import pytest

from app.task_spec import check_reconstruction, derive_task_board, validate
from tests.conftest import load_example


@pytest.mark.parametrize("name, targets", [
    ("closed_loop", {"VM1": {"value": 12.0}}),
    ("voltage_divider", {"VM1": {"value": 4.0}}),
    ("parallel_paths", {"AM1": {"value": 0.4}}),
])
def test_examples_pass_every_stage_with_computed_targets(name, targets):
    result = validate(load_example(name))
    assert result["errors"] == []
    assert result["targets"] == targets
    assert result["board"]["targets"] == targets


def changed(name, change):
    spec = copy.deepcopy(load_example(name))
    change(spec)
    return validate(spec)


def test_broken_complete_board_is_rejected():
    def open_loop(spec):  # remove a wire from the complete board itself
        board = spec["complete_board"]
        board["wires"] = [w for w in board["wires"] if w["segments"] != [[[9, 6], [9, 7]]]]
    result = changed("voltage_divider", open_loop)
    assert any("not a working circuit" in e and "open_circuit" in e for e in result["errors"])
    assert result["board"] is None


def test_target_reading_zero_is_rejected():
    def add_idle_meter(spec):  # a voltmeter across a plain wire reads 0 V
        spec["complete_board"]["components"].append({
            "id": "VM2", "type": "voltmeter", "fixed": True, "orientation": "W",
            "pins": {"positive": [3, 2], "negative": [5, 2]},
        })
        spec["complete_board"]["wires"] += [
            {"id": "W90", "segments": [[[3, 2], [3, 3]]]},
            {"id": "W91", "segments": [[[5, 2], [5, 3]]]},
        ]
        spec["target_meter_ids"] = ["VM2"]
    result = changed("voltage_divider", add_idle_meter)
    assert any("VM2 reads 0.0" in e for e in result["errors"])


def test_a_stub_wire_that_doesnt_matter_is_rejected():
    def remove_dead_end(spec):  # the closed loop with a stub wire that doesn't matter
        spec["complete_board"]["wires"].append({"id": "W90", "segments": [[[11, 2], [12, 2]]]})
        spec["removed_ids"] = ["W90"]
    result = changed("closed_loop", remove_dead_end)
    assert any("unused_wire (W90)" in e for e in result["errors"])  # the complete board has a leftover


def test_removing_something_irrelevant_is_already_solved():
    def remove_extra_meter(spec):  # a second voltmeter across R1 that no target depends on
        spec["complete_board"]["components"].append({
            "id": "VM2", "type": "voltmeter", "fixed": False, "orientation": "W",
            "pins": {"positive": [6, 5], "negative": [8, 5]},
        })
        spec["complete_board"]["wires"] += [
            {"id": "W90", "segments": [[[6, 3], [6, 4]]]}, {"id": "W91", "segments": [[[6, 4], [6, 5]]]},
            {"id": "W92", "segments": [[[8, 3], [8, 4]]]}, {"id": "W93", "segments": [[[8, 4], [8, 5]]]},
        ]
        spec["removed_ids"] = ["VM2"]
    result = changed("closed_loop", remove_extra_meter)
    assert any("already solved" in e for e in result["errors"])


def test_reconstruction_detects_a_tampered_task_board():
    spec = load_example("voltage_divider")
    board = derive_task_board(spec)
    board["components"][0] = {**board["components"][0], "value": 9}
    board["inventory"] = [i for i in board["inventory"] if i["id"] != "R2"]
    errors = check_reconstruction(spec, board)
    assert any("V1 differs" in e for e in errors)
    assert any("removed part R2" in e for e in errors)


def test_signature_ignores_layout_but_not_wiring():
    from app.task_spec import signature
    divider = load_example("voltage_divider")
    moved = copy.deepcopy(divider)
    for c in moved["complete_board"]["components"]:
        c["id"] = c["id"] + "x"  # IDs don't matter
    moved["target_meter_ids"] = [m + "x" for m in moved["target_meter_ids"]]
    assert signature(moved) == signature(divider)
    assert signature(load_example("parallel_paths")) != signature(divider)


def test_recent_repeat_is_rejected():
    from app.task_spec import signature
    spec = load_example("voltage_divider")
    result = validate(spec, recent_signatures=[signature(spec)])
    assert any("repeats a recent one" in e for e in result["errors"])
    assert validate(spec, recent_signatures=["something else"])["errors"] == []
