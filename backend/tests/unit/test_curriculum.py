import copy
import random

import pytest

from app.curriculum import check_centered, check_level, load_curriculum, pick_grid, position, prompt_rules, task_rules
from app.task_spec import validate
from tests.conftest import load_example


@pytest.mark.parametrize("skill, level, task", [
    (1, 1, 1), (2, 1, 2),            # level 1: 2 tasks
    (3, 2, 1), (4, 2, 2),            # level 2: 2 tasks
    (5, 3, 1), (7, 3, 3),            # level 3: 3 tasks
    (8, 4, 1), (13, 5, 3),           # levels 4–5: 3 tasks
    (14, 6, 1), (17, 6, 4),          # level 6: 4 tasks
    (22, 8, 1), (25, 8, 4),          # level 8: 4 tasks, the last
    (26, 8, 1), (29, 8, 4),          # past the end: stay at level 8, cycling its tasks
])
def test_skill_level_maps_to_level_and_task(skill, level, task):
    rules, n = position(skill)
    assert (rules["level"], n) == (level, task)


def test_task_counts_per_level():
    assert [l["tasks"] for l in load_curriculum()] == [2, 2, 3, 3, 3, 4, 4, 4]


def test_level_1_tasks_go_from_wires_to_several_elements():
    rules = load_curriculum()[0]
    first, second = task_rules(rules, 1), task_rules(rules, 2)
    assert first["removed"]["parts"] == [0, 0] and "wire" in first["variant"]
    assert second["removed"]["total"] == [2, 3]
    assert prompt_rules(rules, 2, {"columns": 8, "rows": 6})["this_task"].startswith("several elements")


def test_grid_is_picked_within_the_level_range():
    rules = load_curriculum()[0]
    rng = random.Random(3)
    for _ in range(20):
        grid = pick_grid(rules, rng)
        assert 8 <= grid["columns"] <= 10 and grid["rows"] == 6


def test_example_does_not_fit_level_1():
    rules = load_curriculum()[0]
    errors = check_level(load_example("voltage_divider"), rules, 1, {"columns": 8, "rows": 6})
    assert any("grid 8 x 6" in e for e in errors)
    assert any("remove 1–2 wire pieces" in e for e in errors)
    assert any("remove 0–0 parts" in e for e in errors)
    assert any("0–0 decoys" in e for e in errors)


@pytest.mark.parametrize("name", ["closed_loop", "voltage_divider", "parallel_paths"])
def test_examples_are_centered(name):
    assert check_centered(load_example(name)) == []


def test_off_center_circuit_is_reported():
    spec = copy.deepcopy(load_example("voltage_divider"))
    for c in spec["complete_board"]["components"]:
        c["pins"] = {k: [p[0] - 1, p[1]] for k, p in c["pins"].items()}
    for w in spec["complete_board"]["wires"]:
        w["segments"] = [[[p[0] - 1, p[1]] for p in s] for s in w["segments"]]
    assert any("center the circuit horizontally" in e for e in check_centered(spec))


def test_level_7_lets_the_learner_place_the_target_meter():
    spec = copy.deepcopy(load_example("voltage_divider"))
    meter = next(c for c in spec["complete_board"]["components"] if c["id"] == "VM1")
    meter["fixed"] = False
    spec["removed_ids"] = ["VM1"]
    spec["decoys"] = []
    level7 = {**load_curriculum()[6], "grid": {"columns": [12, 12], "rows": [8, 8]},
              "removed": {"wires": [0, 2], "parts": [1, 2], "meters": [1, 2]}}
    level = {"rules": level7, "task": 1, "grid": {"columns": 12, "rows": 8}}
    result = validate(spec, level=level)
    assert result["errors"] == []
    assert [i["id"] for i in result["board"]["inventory"]] == ["VM1"]
    assert result["targets"] == {"VM1": {"value": 4.0}}
    assert any("is removed" in e for e in validate(spec)["errors"])  # outside level 7 it's an error
