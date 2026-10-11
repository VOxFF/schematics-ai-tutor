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
