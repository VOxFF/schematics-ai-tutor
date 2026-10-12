"""Fallback pack: pre-generated tasks for the whole learning path, served when a generated task
isn't available (docs/design.md §6, Fallback when Claude is unavailable).

One file per skill level of the curriculum, `data/fallback/skill-<n>.json`, each a list of
`task_generation.fallback_variants` TaskSpecs. They are made by scripts/generate_fallback.py and
checked by the tests against the current validator and curriculum. A spec is built into a Level
when it's served, like a generated one.
"""

import json
import random
from functools import lru_cache
from pathlib import Path

from .curriculum import load_curriculum, position
from .learner_profile import first_skill_level
from .task_generation import GenerationResult
from .task_spec import build_level, signature, validate

FALLBACK_DIR = Path(__file__).resolve().parents[1] / "data" / "fallback"


def skill_levels(levels: list[dict] | None = None) -> int:
    """How many skill levels the learning path has: the curriculum's tasks, all levels together."""
    return sum(rules["tasks"] for rules in levels or load_curriculum())


def pack_skill(skill_level: int, levels: list[dict] | None = None) -> int:
    """The pack file for a skill level. Past the end of the path, tasks stay at the last curriculum
    level and cycle through its tasks, so they come from that level's files."""
    rules, task = position(skill_level, levels)
    return first_skill_level(rules["level"], levels) + task - 1


def path(skill: int) -> Path:
    return FALLBACK_DIR / f"skill-{skill}.json"


@lru_cache(maxsize=None)
def load(skill: int) -> tuple[dict, ...]:
    """The specs for one skill level; empty when the file is missing."""
    file = path(skill)
    return tuple(json.loads(file.read_text())) if file.exists() else ()


def curriculum_check(skill: int, levels: list[dict] | None = None) -> dict:
    """The `level` argument of `validate` for a stored spec: its skill level's rules and task, and
    the spec's own grid, which must be within the level's range (see `grid_errors`)."""
    rules, task = position(skill, levels)
    return {"rules": rules, "task": task}


def grid_errors(spec: dict, rules: dict) -> list[str]:
    grid = spec["complete_board"]["grid"]
    (cmin, cmax), (rmin, rmax) = rules["grid"]["columns"], rules["grid"]["rows"]
    if cmin <= grid["columns"] <= cmax and rmin <= grid["rows"] <= rmax:
        return []
    return [f"grid {grid['columns']} x {grid['rows']} is outside level {rules['level']}'s range"]


def check(spec: dict, skill: int, config: dict, levels: list[dict] | None = None) -> dict:
    """`validate` for a stored spec at its skill level: the result has `errors` and `board`."""
    level = curriculum_check(skill, levels)
    level["grid"] = spec["complete_board"]["grid"]
    result = validate(spec, config.get("rate_limits", {}).get("grid", {}), config.get("evaluator", {}), (), level)
    result["errors"] = grid_errors(spec, level["rules"]) + result["errors"]
    return result


def pick(skill_level: int, history: list[dict], config: dict, usage_log=None,
         rng: random.Random | None = None) -> GenerationResult | None:
    """A task from the pack for this skill level: one the learner hasn't had, else the one they had
    longest ago (by signature, as the repeat check). None when the pack has nothing valid."""
    rng = rng or random.Random()
    skill = pack_skill(skill_level)
    seen = [t.get("signature") for t in history]

    def last_seen(spec: dict) -> int:
        mine = signature(spec)
        return max((i for i, s in enumerate(seen) if s == mine), default=-1)

    specs = sorted(load(skill), key=lambda spec: (last_seen(spec), rng.random()))
    for spec in specs:
        result = check(spec, skill, config)
        if result["errors"]:
            if usage_log is not None:
                usage_log.event("fallback_invalid", skill=skill, title=spec.get("title"), errors=result["errors"][:5])
            continue
        rules, task = position(skill_level)
        curriculum = {"level": rules["level"], "task": task, "tasks": rules["tasks"], "concept": rules["concept"]}
        level = build_level(spec, skill_level, result["board"], curriculum)
        return GenerationResult(spec=spec, level=level, attempts=0)
    return None
