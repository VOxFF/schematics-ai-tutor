"""Learner profile: sanitizing what the browser sends, topics joining per task, focus topics."""

from app.learner_profile import FOCUS_TOPICS, MAX_TOPICS, first_skill_level, focus, join, load_catalog, sanitize


def entry(topic_id, introduced=1, understanding=0, explained=0, **extra):
    return {"id": topic_id, "name": topic_id.title(), "type": "term", "definition": "A test topic.",
            "introduced": introduced, "understanding": understanding, "explained": explained,
            "source": "catalog"} | extra


def test_catalog_topics_are_well_formed():
    catalog = load_catalog()
    assert {"closed_loop", "ohms_law", "ammeter", "voltmeter"} <= set(catalog)
    for topic in catalog.values():
        assert topic["type"] in ("principle", "term") and topic["definition"]
        assert ("level" in topic) != ("component" in topic)


def test_sanitize_drops_bad_entries_and_clamps_scores():
    raw = {"topics": [
        entry("current", understanding=7, explained=-2),
        entry("current"),  # duplicate
        {"id": "Bad Id", "name": "x", "type": "term", "definition": "x"},
        entry("watt", type="opinion"),
        "nonsense",
        entry("volt", introduced=0, source="hacker", name="  " + "V" * 100),
    ]}
    topics = sanitize(raw)["topics"]
    assert [t["id"] for t in topics] == ["current", "volt"]
    assert (topics[0]["understanding"], topics[0]["explained"]) == (3, 0)
    assert topics[1]["introduced"] == 1 and topics[1]["source"] == "claude" and len(topics[1]["name"]) == 40
    assert sanitize(None) == {"topics": []} and sanitize({"topics": "x"}) == {"topics": []}
    assert len(sanitize({"topics": [entry(f"t{i:03d}") for i in range(200)]})["topics"]) == MAX_TOPICS


def test_a_task_brings_its_level_topics_and_its_meters():
    profile = {"topics": []}
    level = {"curriculum": {"level": 2}}
    board = {"components": [{"type": "voltage_source"}, {"type": "ammeter"}], "inventory": []}
    joined = join(profile, level, board, skill_level=3)
    assert {"closed_loop", "ohms_law", "resistance", "ammeter"} <= set(joined)
    assert "voltmeter" not in joined and "series" not in joined
    by_id = {t["id"]: t for t in profile["topics"]}
    assert by_id["closed_loop"]["introduced"] == 1
    assert by_id["ohms_law"]["introduced"] == first_skill_level(2) == 3
    assert by_id["ammeter"]["introduced"] == 3
    # Known topics keep their scores.
    by_id["current"]["understanding"] = 2
    assert join(profile, level, board, skill_level=4) == []
    assert by_id["current"]["understanding"] == 2


def test_focus_is_recent_topics_then_older_weak_ones():
    topics = [entry(f"old_{i}", introduced=1, understanding=3) for i in range(6)]
    topics += [entry("old_weak", introduced=1, understanding=1)]
    topics += [entry(f"new_{i}", introduced=5) for i in range(5)]
    picked = focus({"topics": topics}, skill_level=6)
    assert len(picked) == FOCUS_TOPICS
    assert [t["id"] for t in picked[:6]] == [f"new_{i}" for i in range(5)] + ["old_weak"]
    assert picked[0]["tasks_ago"] == 1 and "source" not in picked[0]
