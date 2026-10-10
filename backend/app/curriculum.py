"""Curriculum levels (backend/data/curriculum.yaml): skill level → level and task, rules, checks."""

import random
from functools import lru_cache
from pathlib import Path

import yaml

from .grid import METER_TYPES, component_points

CURRICULUM_PATH = Path(__file__).resolve().parents[1] / "data" / "curriculum.yaml"


@lru_cache(maxsize=1)
def load_curriculum(path: Path = CURRICULUM_PATH) -> list[dict]:
    return yaml.safe_load(path.read_text())["levels"]


def position(skill_level: int, levels: list[dict] | None = None) -> tuple[dict, int]:
    """The curriculum level and the 1-based task number within it for a skill level.

    Skill level 1 is the first task. Past the last level, tasks stay at the last level.
    """
    levels = levels or load_curriculum()
    remaining = max(skill_level, 1)
    for rules in levels:
        if remaining <= rules["tasks"]:
            return rules, remaining
        remaining -= rules["tasks"]
    last = levels[-1]
    return last, (remaining - 1) % last["tasks"] + 1


def task_rules(rules: dict, task: int) -> dict:
    """The level's rules with the task's variant (if any) applied."""
    merged = {k: v for k, v in rules.items() if k != "variants"}
    variants = rules.get("variants") or []
    if variants:
        variant = variants[(task - 1) % len(variants)]
        merged["removed"] = variant["removed"]
        merged["variant"] = variant["description"]
    return merged


def pick_grid(rules: dict, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    (cmin, cmax), (rmin, rmax) = rules["grid"]["columns"], rules["grid"]["rows"]
    return {"columns": rng.randint(cmin, cmax), "rows": rng.randint(rmin, rmax)}


def prompt_rules(rules: dict, task: int, grid: dict) -> dict:
    """What Claude must generate at this level, for the user turn."""
    applied = task_rules(rules, task)
    out = {
        "level": rules["level"],
        "task": f"{task} of {rules['tasks']}",
        "concept": rules["concept"],
        "goal": rules["goal"],
        "circuit": rules["circuit"],
        "grid": grid,
        "removed": applied["removed"],
        "decoys": rules["decoys"],
        "targets": rules["targets"],
    }
    if "variant" in applied:
        out["this_task"] = applied["variant"]
    if rules.get("removed_targets_allowed"):
        out["note"] = "the target meters are among the removed parts: the learner places them"
    return out


def _in(value: int, bounds) -> bool:
    return bounds[0] <= value <= bounds[1]


def check_level(spec: dict, rules: dict, task: int, grid: dict) -> list[str]:
    """The task fits its curriculum level: grid, removed elements, decoys, targets."""
    applied = task_rules(rules, task)
    errors = []
    board = spec["complete_board"]
    if board["grid"] != grid:
        errors.append(f"level {rules['level']}: use exactly the grid {grid['columns']} x {grid['rows']}")
    components = {c["id"]: c for c in board["components"]}
    removed = set(spec["removed_ids"])
    parts = [cid for cid in removed if cid in components]
    wires = [rid for rid in removed if rid not in components]
    meters = [cid for cid in parts if components[cid]["type"] in METER_TYPES]
    want = applied["removed"]
    if not _in(len(wires), want["wires"]):
        errors.append(f"level {rules['level']}: remove {want['wires'][0]}–{want['wires'][1]} wire pieces (now {len(wires)})")
    if not _in(len(parts), want["parts"]):
        errors.append(f"level {rules['level']}: remove {want['parts'][0]}–{want['parts'][1]} parts (now {len(parts)})")
    if "total" in want and not _in(len(parts) + len(wires), want["total"]):
        errors.append(f"level {rules['level']}: remove {want['total'][0]}–{want['total'][1]} elements in total")
    if "meters" in want and not _in(len(meters), want["meters"]):
        errors.append(f"level {rules['level']}: {want['meters'][0]}–{want['meters'][1]} of the removed parts must be meters")
    if not _in(len(spec["decoys"]), rules["decoys"]):
        errors.append(f"level {rules['level']}: use {rules['decoys'][0]}–{rules['decoys'][1]} decoys (now {len(spec['decoys'])})")
    if not _in(len(spec["target_meter_ids"]), rules["targets"]):
        errors.append(f"level {rules['level']}: use {rules['targets'][0]}–{rules['targets'][1]} target meters")
    return errors


def check_centered(spec: dict) -> list[str]:
    """The circuit is centered: margins on opposite sides differ by at most one grid step."""
    board = spec["complete_board"]
    points = [p for c in board["components"] for p in component_points(c)]
    points += [tuple(p) for w in board["wires"] for s in w["segments"] for p in s]
    if not points:
        return []
    cols = [p[0] for p in points]
    rows = [p[1] for p in points]
    left, right = min(cols) - 1, board["grid"]["columns"] - max(cols)
    top, bottom = min(rows) - 1, board["grid"]["rows"] - max(rows)
    errors = []
    if abs(left - right) > 1:
        errors.append(f"center the circuit horizontally: free columns left {left}, right {right}")
    if abs(top - bottom) > 1:
        errors.append(f"center the circuit vertically: free rows top {top}, bottom {bottom}")
    return errors
