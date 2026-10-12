"""Fallback pack: the real pack fits the current curriculum and validator; picking a task."""

import random

from app import fallback
from app.curriculum import load_curriculum
from app.jsonfmt import dumps
from app.task_spec import signature
from tests.conftest import load_example


def test_the_pack_covers_every_skill_level_of_the_curriculum(config):
    # Sizes come from curriculum.yaml: a level with 4 tasks has 4 skill levels in the pack.
    count = fallback.skill_levels()
    assert count == sum(rules["tasks"] for rules in load_curriculum())
    expected = {fallback.path(n).name for n in range(1, count + 1)}
    present = {p.name for p in fallback.FALLBACK_DIR.glob("*.json")}
    assert present == expected, "missing or left-over pack files: run scripts/generate_fallback.py"
    variants = config["task_generation"]["fallback_variants"]
    for skill in range(1, count + 1):
        assert len(fallback.load(skill)) == variants, f"skill-{skill}.json"


def test_every_task_in_the_pack_validates(config):
    for skill in range(1, fallback.skill_levels() + 1):
        signatures = set()
        for spec in fallback.load(skill):
            result = fallback.check(spec, skill, config)
            assert result["errors"] == [], f"skill-{skill}.json, {spec['title']}: {result['errors']}"
            signatures.add(signature(spec))
        assert len(signatures) == len(fallback.load(skill)), f"skill-{skill}.json repeats a circuit"


def test_past_the_end_tasks_cycle_through_the_last_levels_files():
    levels = [{"level": 1, "tasks": 2}, {"level": 2, "tasks": 3}]
    assert [fallback.pack_skill(n, levels) for n in range(1, 10)] == [1, 2, 3, 4, 5, 3, 4, 5, 3]


def test_pick_prefers_unseen_then_seen_longest_ago(config, pack):
    first = load_example()
    # The same task with doubled resistors: another circuit, so another signature.
    second = {**load_example(), "title": "Second"}
    second["complete_board"] = {**first["complete_board"],
                                "components": [dict(c, value=c["value"] * 2) if c.get("type") == "resistor" else c
                                               for c in first["complete_board"]["components"]]}
    (pack / "skill-1.json").write_text(dumps([first, second]))
    fallback.load.cache_clear()
    seen = lambda *specs: [{"signature": signature(s)} for s in specs]
    assert fallback.pick(1, seen(first), config).spec["title"] == "Second"
    assert fallback.pick(1, seen(second), config).spec["title"] == first["title"]
    assert fallback.pick(1, seen(second, first), config).spec["title"] == "Second"  # seen longest ago
    level = fallback.pick(5, [], config, rng=random.Random(1)).level
    assert level["order"] == 5 and level["board"]["targets"]


def test_an_invalid_entry_is_skipped(config, pack):
    bad = {**load_example(), "removed_ids": []}
    (pack / "skill-1.json").write_text(dumps([bad]))
    fallback.load.cache_clear()
    assert fallback.pick(1, [], config) is None
