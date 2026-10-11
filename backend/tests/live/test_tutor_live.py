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
