import asyncio
import copy
import json

import pytest

pytestmark = pytest.mark.usefixtures("any_level")

from app.task_generation import generate_task, learner_context
from tests.conftest import FakeClaude, as_claude_output, load_example, text_response, tool_response


def run(client, config, usage_log, **kwargs):
    kwargs.setdefault("skill_level", 2)
    kwargs.setdefault("history", [])
    return asyncio.run(generate_task(client, config, usage_log, **kwargs))


def log_events(usage_log):
    return [json.loads(line) for line in usage_log.path.read_text().splitlines()]


def test_valid_answer_becomes_a_level(config, usage_log):
    client = FakeClaude([text_response(as_claude_output(load_example()))])
    result = run(client, config, usage_log)
    assert result.errors == []
    assert result.attempts == 1
    assert result.level["board"]["targets"] == {"VM1": {"value": 4.0}}  # computed, not from Claude
    request = client.requests[0]
    assert request["model"] == config["claude"]["task_generation"]["model"]
    assert request["tools"][0]["name"] == "validate_grid"
    assert request["output_config"]["format"]["type"] == "json_schema"
    assert "Examples of valid TaskSpecs" in request["system"][0]["text"]


def test_tool_call_gets_validation_feedback(config, usage_log):
    bad_draft = as_claude_output(load_example())
    bad_draft["removed_ids"] = []
    client = FakeClaude([tool_response(bad_draft), text_response(as_claude_output(load_example()))])
    result = run(client, config, usage_log)
    assert result.level is not None
    tool_result = client.requests[1]["messages"][-1]["content"][0]
    feedback = json.loads(tool_result["content"])
    assert feedback["ok"] is False and any("at least one part" in e for e in feedback["errors"])


def test_retry_with_errors_then_success(config, usage_log):
    bad = as_claude_output(load_example())
    bad["target_meter_ids"] = ["R1"]
    client = FakeClaude([text_response(bad), text_response(as_claude_output(load_example()))])
    result = run(client, config, usage_log)
    assert result.attempts == 2 and result.level is not None
    retry_prompt = client.requests[1]["messages"][0]["content"]
    assert "previous proposal was rejected" in retry_prompt and "not a meter" in retry_prompt


def test_gives_up_after_max_attempts(config, usage_log):
    bad = as_claude_output(load_example())
    bad["difficulty"] = 0
    client = FakeClaude([text_response(bad), text_response(bad)])
    result = run(client, config, usage_log)
    assert result.level is None and result.attempts == 2
    assert any("difficulty" in e for e in result.errors)
    assert log_events(usage_log)[-1]["event"] == "task_generation_failed"


def test_refusal_and_bad_json_are_failures(config, usage_log):
    client = FakeClaude([text_response("{}", stop_reason="refusal"), text_response("not json")])
    result = run(client, config, usage_log)
    assert result.level is None
    assert "not valid TaskSpec JSON" in result.errors[0]


def test_every_call_is_logged_with_cost(config, usage_log):
    client = FakeClaude([text_response(as_claude_output(load_example()))])
    run(client, config, usage_log, session_id="s1")
    call = next(e for e in log_events(usage_log) if e["event"] == "claude_call")
    assert call["purpose"] == "task_generation" and call["session_id"] == "s1"
    assert call["cost_usd"] > 0


def test_learner_context_splits_recent_and_older():
    history = [{"concept": f"c{i}"} for i in range(12)]
    context = learner_context(4, copy.deepcopy(history), {"columns": 12, "rows": 8}, recent=10)
    assert len(context["recent_tasks"]) == 10
    assert context["older_tasks"] == {"count": 2, "concepts": ["c0", "c1"]}


def test_repeat_of_history_is_regenerated(config, usage_log):
    from app.task_spec import signature
    spec = load_example()
    other = load_example("parallel_paths")
    client = FakeClaude([text_response(as_claude_output(spec)), text_response(as_claude_output(other))])
    result = run(client, config, usage_log, history=[{"concept": "voltage divider", "signature": signature(spec)}])
    assert result.attempts == 2 and result.spec["title"] == "Parallel paths"
    assert result.level["signature"] == signature(other)


def test_identical_contexts_get_different_variations():
    import random
    from app.task_generation import variation
    rng = random.Random(1)
    variations = {tuple(variation(rng).items()) for _ in range(10)}
    assert len(variations) > 1


def test_some_tasks_get_a_battery_hint():
    import random
    from app.task_generation import BATTERY_HINTS, variation
    rng = random.Random(7)
    hints = [variation(rng).get("battery") for _ in range(200)]
    share = sum(h is not None for h in hints) / len(hints)
    assert 0.15 < share < 0.35 and {h for h in hints if h} == set(BATTERY_HINTS)


def test_prompt_carries_variation_and_level_has_shape(config, usage_log):
    client = FakeClaude([text_response(as_claude_output(load_example()))])
    result = run(client, config, usage_log)
    prompt = client.requests[0]["messages"][0]["content"]
    assert '"variation"' in prompt and '"layout"' in prompt
    assert result.level["shape"] == "V + 2R + VM" and result.level["difficulty"] == 3


def test_a_malformed_tool_draft_is_an_error_for_claude_not_a_crash():
    from app.task_generation import tool_result
    result = json.loads(tool_result({"complete_board": "V1, R1 and a gap"}, {}, {}))
    assert result["ok"] is False and "complete_board must be an object" in result["errors"][0]
