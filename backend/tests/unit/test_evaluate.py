"""Evaluator statuses and readings on the example circuits and broken variants."""

import copy

import pytest

from app.evaluate import evaluate
from app.grid import validate_grid
from app.task_spec import complete_grid
from tests.conftest import load_example


def grid(name="voltage_divider"):
    return copy.deepcopy(complete_grid(load_example(name)))


def comp(g, cid):
    return next(c for c in g["components"] if c["id"] == cid)


def drop_wire(g, segment):
    g["wires"] = [w for w in g["wires"] if w["segments"] != [segment]]


@pytest.mark.parametrize("name, meter, value", [
    ("closed_loop", "VM1", 12.0),       # full source voltage across R1
    ("voltage_divider", "VM1", 4.0),    # 12 V * 20 / (40 + 20)
    ("parallel_paths", "AM1", 0.4),     # 12/60 + 12/60
])
def test_examples_work_and_read_the_intended_values(name, meter, value):
    result = evaluate(grid(name))
    assert result["issues"] == []
    assert result["status"] == "solved"  # no targets: a working circuit is solved
    assert result["readings"][meter] == value


def test_open_loop_is_open_circuit():
    g = grid("closed_loop")
    drop_wire(g, [[10, 5], [10, 6]])
    result = evaluate(g)
    assert result["status"] == "open_circuit"
    assert result["readings"]["VM1"] == 0.0


def test_wire_across_the_source_is_short_circuit():
    g = grid("closed_loop")
    g["wires"].append({"id": "W99", "segments": [[[3, 4], [2, 4]]]})
    g["wires"].append({"id": "W98", "segments": [[[2, 4], [2, 5]]]})
    g["wires"].append({"id": "W96", "segments": [[[2, 5], [2, 6]]]})
    g["wires"].append({"id": "W97", "segments": [[[2, 6], [3, 6]]]})
    assert validate_grid(g) == []
    result = evaluate(g)
    assert result["status"] == "short_circuit"
    assert all(v is None for v in result["readings"].values())


def test_no_source():
    g = grid()
    g["components"] = [c for c in g["components"] if c["type"] != "voltage_source"]
    result = evaluate(g)
    assert result["status"] == "no_source"
    assert result["readings"] == {"VM1": 0.0}


def test_voltmeter_in_place_of_a_resistor_is_meter_misuse():
    g = grid()  # the divider without R2: VM1 bridges the gap, so it sits in the loop
    g["components"] = [c for c in g["components"] if c["id"] != "R2"]
    result = evaluate(g)
    assert result["status"] == "meter_misuse"
    assert [i["code"] for i in result["issues"]] == ["voltmeter_series"]
    assert result["readings"]["VM1"] == 12.0


def test_unconnected_parts_dont_make_a_short():
    """Regression: parts connected to nothing used to fail the solve and read as short_circuit."""
    g = grid()
    g["components"] = [c for c in g["components"] if c["id"] != "R2"]  # VM1 in series, as above
    g["components"].append({"id": "R9", "type": "resistor", "value": 300, "fixed": False,
                            "orientation": "E", "pins": {"a": [12, 8], "b": [10, 8]}})
    assert validate_grid(g) == []
    result = evaluate(g)
    assert result["status"] == "meter_misuse"
    assert result["readings"]["VM1"] == 12.0
    assert sorted(i["code"] for i in result["issues"]) == ["floating_part", "voltmeter_series"]


def test_contradictory_sources_are_a_short():
    from app.solver import solve
    components = [{"id": "V1", "type": "voltage_source", "value": 9, "pins": ["positive", "negative"]},
                  {"id": "V2", "type": "voltage_source", "value": 5, "pins": ["positive", "negative"]},
                  {"id": "R1", "type": "resistor", "value": 100, "pins": ["a", "b"]}]
    nets = {"V1.positive": 1, "V1.negative": 0, "V2.positive": 1, "V2.negative": 0, "R1.a": 1, "R1.b": 0}
    assert solve(components, nets, 0) is None


def test_floating_part():
    g = grid("parallel_paths")
    drop_wire(g, [[5, 5], [6, 5]])  # R2.a loses its only wire
    result = evaluate(g)
    assert result["status"] == "floating_part"
    assert result["issues"][0]["component_ids"] == ["R2"]
    assert result["issues"][0]["points"] == [[6, 5]]


def test_overcurrent():
    g = grid()
    comp(g, "R1")["value"] = 2
    comp(g, "R2")["value"] = 1  # 12 V over 3 ohm: 4 A, R1 dissipates 32 W
    assert evaluate(g)["status"] == "overcurrent"


def test_targets_solved_near_and_misplaced():
    g = grid()
    g["targets"] = {"VM1": {"value": 4.0}}
    assert evaluate(g)["status"] == "solved"
    g["targets"] = {"VM1": {"value": 4.3}}   # off by 0.3 V: within 10%, outside 2%
    assert evaluate(g)["status"] == "near_target"
    g["targets"] = {"VM1": {"value": 6.0}}
    assert evaluate(g)["status"] == "misplaced"


def test_reversed_meter_reads_negative():
    g = grid()
    vm = comp(g, "VM1")
    vm["pins"] = {"positive": vm["pins"]["negative"], "negative": vm["pins"]["positive"]}
    vm["orientation"] = "S"
    assert evaluate(g)["readings"]["VM1"] == -4.0
