import asyncio
import json

import pytest

from app.tutor import TUTOR_MESSAGE_SCHEMA, answer, build_context, clean_highlights, location_talk
from tests.conftest import FakeClaude, example_level, tutor_reply


@pytest.mark.parametrize("text, found", [
    ("Connect R1.b to AM1.positive.", ["AM1.positive", "R1.b"]),
    ("Put it at [3, 4].", ["[3, 4]"]),
    ("Check row 3.", ["row"]),
    ("Current needs a complete path back to the source.", []),
])
def test_location_talk(text, found):
    assert location_talk(text) == found


def test_schema_puts_meta_before_chat():
    assert list(TUTOR_MESSAGE_SCHEMA["properties"]) == ["meta", "chat"]
    assert list(TUTOR_MESSAGE_SCHEMA["properties"]["meta"]["properties"])[0] == "principle"


def test_context_has_every_section_and_no_raw_reference_grid():
    level, spec = example_level()
    request = {"action": "message", "learner_text": "Why 4 volts?"}
    context, evaluation = build_context(level, level["board"], spec["complete_board"], [], request, 6)
    for tag in ("level", "reference", "summary", "snapshots", "profile", "history", "request"):
        assert f"<{tag}>" in context
    assert "status: meter_misuse" in context  # the task board alone: VM1 blocks the loop
    assert evaluation["status"] == "meter_misuse"
    reference = context.split("<reference>")[1].split("</reference>")[0]
    assert '"edges"' in reference and '"segments"' not in reference  # graph only, no layout


def test_reaction_context_lists_earlier_snapshots_then_the_current_board():
    level, spec = example_level()
    earlier = [{"seq": 1, "t_ms": 900, "graph": {"components": []}, "evaluation": {"status": "open_circuit"}}]
    context, _ = build_context(level, level["board"], spec["complete_board"], [], {"trigger": "reaction"}, 6,
                               snapshots=earlier)
    timeline = json.loads(context.split("<snapshots>")[1].split("</snapshots>")[0])
    assert [s.get("seq") for s in timeline] == [1, None]
    assert timeline[-1]["current"] is True and "grid" in timeline[-1]  # only the current board has the layout
    assert "reaction" in context.split("<request>")[1]


def test_clean_highlights_keeps_only_real_targets():
    level, _ = example_level()
    kept = clean_highlights([
        {"component": "R1", "wire": None, "point": None, "style": "attention"},
        {"component": "R9", "wire": None, "point": None, "style": "error"},
        {"component": None, "wire": "W1", "point": None, "style": "success"},
        {"component": None, "wire": None, "point": [40, 40], "style": "error"},
    ], level["board"])
    assert kept == [
        {"target": {"component": "R1"}, "style": "attention"},
        {"target": {"wire": "W1"}, "style": "success"},
    ]


def ask(client, config, usage_log, text="Why does VM1 show 12 V?"):
    level, spec = example_level()
    return asyncio.run(answer(client, config, usage_log, level=level, board=level["board"],
                              reference=spec["complete_board"], history=[], learner_text=text, session_id="s1"))


def test_answer_returns_a_clean_message(config, usage_log):
    client = FakeClaude([tutor_reply(highlights=[{"component": "VM1", "wire": None, "point": None, "style": "attention"}])])
    message, evaluation = ask(client, config, usage_log)
    assert message["chat"]["text"].startswith("Follow the path")
    assert message["meta"]["hint_level"] == 0  # no hint ladder yet
    assert message["meta"]["highlights"] == [{"target": {"component": "VM1"}, "style": "attention"}]
    request = client.requests[0]
    assert request["model"] == config["claude"]["tutor_request"]["model"]
    assert request["output_config"]["effort"] == config["claude"]["tutor_request"]["effort"]
    assert "Why does VM1 show 12 V?" in request["messages"][0]["content"]


def test_answer_logs_returned_and_kept_highlights(config, usage_log):
    returned = [{"component": "VM1", "wire": None, "point": None, "style": "attention"},
                {"component": "R9", "wire": None, "point": None, "style": "error"}]
    ask(FakeClaude([tutor_reply(highlights=returned)]), config, usage_log)
    records = [json.loads(line) for line in usage_log.path.read_text().splitlines()]
    logged = next(r for r in records if r["event"] == "tutor_highlights")
    assert logged["returned"] == returned
    assert logged["kept"] == [{"target": {"component": "VM1"}, "style": "attention"}]


def test_location_talk_regenerates_then_falls_back(config, usage_log):
    client = FakeClaude([tutor_reply("Connect R1.b to VM1."), tutor_reply("Look at row 3.")])
    message, evaluation = ask(client, config, usage_log)
    assert "previously" not in message["chat"]["text"]
    assert location_talk(message["chat"]["text"]) == []
    assert "described locations" in client.requests[1]["messages"][0]["content"]
    events = [json.loads(line)["event"] for line in usage_log.path.read_text().splitlines()]
    assert events.count("tutor_backstop") == 2 and events.count("claude_call") == 2


def test_a_hint_that_keeps_describing_locations_falls_back_as_a_hint(config, usage_log):
    client = FakeClaude([tutor_reply("Look at row 3."), tutor_reply("Check R1.a again.")])
    level, spec = example_level()
    message, _ = asyncio.run(answer(client, config, usage_log, level=level, board=level["board"],
                                    reference=spec["complete_board"], history=[], hint_level=2))
    assert message["meta"]["hint_level"] == 2 and message["chat"]["kind"] == "hint"


def test_location_talk_then_clean_reply(config, usage_log):
    client = FakeClaude([tutor_reply("Connect R1.b to VM1."), tutor_reply("What does a voltmeter need around it?")])
    message, _ = ask(client, config, usage_log)
    assert message["chat"]["text"] == "What does a voltmeter need around it?"
