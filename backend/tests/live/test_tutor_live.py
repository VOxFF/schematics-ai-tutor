"""Live tutor reply against the real Claude API. Costs money; run with ./test.sh live."""

import asyncio
import json
import os

import anthropic
import pytest

from app.config import REPO_ROOT
from app.tutor import answer, location_talk
from app.usage_log import UsageLog
from tests.conftest import example_level

pytestmark = pytest.mark.live


def test_tutor_answers_a_learner_question(config):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set (./test.sh live loads backend/keys/apikey.txt)")
    usage_log = UsageLog.from_config(config, REPO_ROOT, "live-test")
    level, spec = example_level()  # voltage divider task: VM1 currently blocks the loop
    question = "Why does the voltmeter show 12 volts? I thought it should be less."

    message, evaluation = asyncio.run(answer(
        anthropic.AsyncAnthropic(), config, usage_log, level=level, board=level["board"],
        reference=spec["complete_board"], history=[], learner_text=question, session_id="live",
    ))
    print(json.dumps({"status": evaluation["status"], "message": message}, indent=2))
    print(f"cost: ${usage_log.totals['cost_usd']:.4f}")
    assert message["chat"]["text"]
    assert location_talk(message["chat"]["text"]) == []


def test_tutor_reacts_to_an_edit(config):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set (./test.sh live loads backend/keys/apikey.txt)")
    usage_log = UsageLog.from_config(config, REPO_ROOT, "live-test")
    level, spec = example_level()
    message, evaluation = asyncio.run(answer(
        anthropic.AsyncAnthropic(), config, usage_log, level=level, board=level["board"],
        reference=spec["complete_board"], history=[], learner_text=None, session_id="live",
    ))
    print(json.dumps({"status": evaluation["status"], "message": message}, indent=2))
    print(f"cost: ${usage_log.totals['cost_usd']:.4f}")
    assert message["chat"]["text"]
    assert location_talk(message["chat"]["text"]) == []


def test_tutor_suggests_tidying_up_leftovers_when_solved(config):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set (./test.sh live loads backend/keys/apikey.txt)")
    usage_log = UsageLog.from_config(config, REPO_ROOT, "live-test")
    level, spec = example_level()
    board = {**spec["complete_board"], "inventory": [], "targets": level["board"]["targets"],
             "wires": spec["complete_board"]["wires"] + [{"id": "W90", "segments": [[[12, 8], [12, 7]]]}]}
    message, evaluation = asyncio.run(answer(
        anthropic.AsyncAnthropic(), config, usage_log, level=level, board=board,
        reference=spec["complete_board"], history=[], learner_text=None, session_id="live",
    ))
    print(json.dumps({"status": evaluation["status"], "message": message}, indent=2))
    print(f"cost: ${usage_log.totals['cost_usd']:.4f}")
    assert evaluation["status"] == "solved"
    assert {"target": {"wire": "W90"}, "style": "attention"} in message["meta"]["highlights"]


def test_tutor_gives_a_hint_at_each_level(config):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set (./test.sh live loads backend/keys/apikey.txt)")
    usage_log = UsageLog.from_config(config, REPO_ROOT, "live-test")
    level, spec = example_level()
    client = anthropic.AsyncAnthropic()
    for hint_level in (1, 2, 3):
        message, _ = asyncio.run(answer(
            client, config, usage_log, level=level, board=level["board"], reference=spec["complete_board"],
            history=[], session_id="live", hint_level=hint_level,
        ))
        print(hint_level, json.dumps(message["chat"]), json.dumps(message["meta"]["highlights"]))
        assert message["meta"]["hint_level"] == hint_level and message["chat"]["kind"] == "hint"
        assert location_talk(message["chat"]["text"]) == []
    print(f"cost: ${usage_log.totals['cost_usd']:.4f}")


def test_tutor_teaches_a_topic_it_has_not_explained(config):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set (./test.sh live loads backend/keys/apikey.txt)")
    from app.learner_profile import focus, join
    from app.reply_composer import compose

    usage_log = UsageLog.from_config(config, REPO_ROOT, "live-test")
    level, spec = example_level()  # VM1 sits in the loop: a voltmeter the learner hasn't been taught
    profile = {"topics": []}
    join(profile, level, level["board"], 1)
    message, _ = asyncio.run(answer(
        anthropic.AsyncAnthropic(), config, usage_log, level=level, board=level["board"],
        reference=spec["complete_board"], history=[], learner_text="What is this V thing?", session_id="live",
        profile={"skill_level": 1, "focus": focus(profile, 1)},
    ))
    chat, dropped = compose(message, profile, 1)
    print(json.dumps({"meta": message["meta"], "chat": chat, "dropped": dropped}, indent=2, ensure_ascii=False))
    print(f"cost: ${usage_log.totals['cost_usd']:.4f}")
    assert chat["kind"] == "knowledge" and chat["title"]
    assert next(t for t in profile["topics"] if t["id"] == "voltmeter")["explained"] == 1


def test_feedback_conversation_asks_a_follow_up_without_tutoring(config, tmp_path):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set (./test.sh live loads backend/keys/apikey.txt)")
    from app.research import Research, ResearchLog

    usage_log = UsageLog.from_config(config, REPO_ROOT, "live-test")
    research = Research(ResearchLog(tmp_path), config, anthropic.AsyncAnthropic(), usage_log, "live")
    research.start({"consent": True, "learner_id": "0b7e3c1a-5f2d-4c8e-9a1b-2c3d4e5f6a7b"}, {}, {}, {})
    research.active_s = 600
    research.prompt_due(3, "open_circuit")
    reply = asyncio.run(research.reply("The hints are too vague, and why is my voltmeter reading 12 V?"))
    print(json.dumps(reply, indent=2, ensure_ascii=False))
    print(f"cost: ${usage_log.totals['cost_usd']:.4f}")
    assert reply["kind"] == "experience" and reply["text"]
    assert research.thread_open  # a follow-up question, not the end


@pytest.mark.parametrize("text, handoff", [
    ("The feedback is not sufficient for complex schematics like level 6", False),
    ("Its about my user experience", False),
    ("Why does the ammeter read zero?", True),
])
def test_feedback_conversation_hands_off_only_circuit_questions(config, tmp_path, text, handoff):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set (./test.sh live loads backend/keys/apikey.txt)")
    from app.research import Research, ResearchLog

    usage_log = UsageLog.from_config(config, REPO_ROOT, "live-test")
    research = Research(ResearchLog(tmp_path), config, anthropic.AsyncAnthropic(), usage_log, "live")
    research.start({"consent": True, "learner_id": "0b7e3c1a-5f2d-4c8e-9a1b-2c3d4e5f6a7b"}, {}, {}, {})
    research.active_s = 600
    research.prompt_due(3, "open_circuit")
    reply = asyncio.run(research.reply(text))
    print(text, "→", "handoff" if reply is None else reply["text"])
    assert (reply is None) == handoff


def _open_loop():
    """The closed_loop example with one wire piece taken out: open ends at [10, 5] and [10, 6]."""
    from app.task_spec import build_level, complete_grid, validate
    from tests.conftest import load_example

    spec = load_example("closed_loop")
    level = build_level(spec, 1, validate(spec)["board"])
    board = complete_grid(spec)
    board["wires"] = [w for w in board["wires"] if w["segments"] != [[[10, 5], [10, 6]]]]
    return level, board, spec


def test_tutor_highlights_the_open_ends_of_a_broken_loop(config):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set (./test.sh live loads backend/keys/apikey.txt)")
    usage_log = UsageLog.from_config(config, REPO_ROOT, "live-test")
    level, board, spec = _open_loop()
    message, evaluation = asyncio.run(answer(
        anthropic.AsyncAnthropic(), config, usage_log, level=level, board=board,
        reference=spec["complete_board"], history=[], learner_text=None, session_id="live",
    ))
    print(json.dumps({"issues": evaluation["issues"], "highlights": message["meta"]["highlights"],
                      "text": message["chat"]["text"]}, indent=1))
    points = [h["target"]["point"] for h in message["meta"]["highlights"] if "point" in h["target"]]
    assert sorted(points) == [[10, 5], [10, 6]]
    assert not [h for h in message["meta"]["highlights"] if h["target"].get("component") == "V1"]


def test_a_problem_the_learner_knows_gets_one_short_line(config):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set (./test.sh live loads backend/keys/apikey.txt)")
    from app.learner_profile import focus, join

    usage_log = UsageLog.from_config(config, REPO_ROOT, "live-test")
    level, board, spec = _open_loop()
    profile = {"topics": []}
    join(profile, {"curriculum": {"level": 3}}, board, 6)
    for t in profile["topics"]:
        if t["id"] in ("closed_loop", "open_circuit", "current"):
            t["understanding"], t["explained"] = 2, 2
    history = [{"role": "tutor", "text": "The ammeter reads zero because the loop still has a gap. Where does it stop?"}]
    message, _ = asyncio.run(answer(
        anthropic.AsyncAnthropic(), config, usage_log, level=level, board=board,
        reference=spec["complete_board"], history=history, learner_text=None, session_id="live",
        profile={"skill_level": 6, "focus": focus(profile, 6)},
    ))
    text = message["chat"]["text"]
    print(text)
    print(f"cost: ${usage_log.totals['cost_usd']:.4f}")
    assert len([s for s in text.replace("?", ".").split(".") if s.strip()]) <= 2
    assert not text.startswith("The ammeter reads zero")
