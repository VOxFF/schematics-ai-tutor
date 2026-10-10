import json

from app.config import load_config
from app.usage_log import UsageLog

PRICING = {"claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.2, "cache_write": 5.0}}


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_root_config_loads_with_logs_section():
    config = load_config()
    assert isinstance(config["logs"]["enabled"], bool)
    assert "claude-opus-5-5" in config["pricing"]


def test_disabled_log_writes_nothing(tmp_path):
    log = UsageLog.from_config({"logs": {"enabled": False, "dir": "logs"}}, tmp_path, "r1")
    log.event("server_started")
    log.claude_call(purpose="tutor_reaction", model="claude-opus-5-5", usage={"input_tokens": 10})
    assert not log.enabled
    assert not (tmp_path / "logs").exists()


def test_claude_call_cost_and_summary(tmp_path):
    log = UsageLog.from_config({"logs": {"enabled": True, "dir": "logs"}, "pricing": PRICING}, tmp_path, "r1")
    usage = {
        "input_tokens": 1_000,
        "output_tokens": 500,
        "cache_read_input_tokens": 2_000,
        "cache_creation_input_tokens": 100,
    }
    log.claude_call(purpose="tutor_reaction", model="claude-opus-5-5", usage=usage, session_id="s1")
    log.claude_call(purpose="task_generation", model="unknown-model", usage={"input_tokens": 5})
    log.summary()

    events = read_events(tmp_path / "logs" / "run-r1.jsonl")
    call, unpriced, summary = events
    expected = (1_000 * 4.0 + 500 * 20.0 + 2_000 * 0.2 + 100 * 5.0) / 1e6
    assert call["event"] == "claude_call" and call["session_id"] == "s1"
    assert call["cost_usd"] == round(expected, 6)
    assert unpriced["cost_usd"] is None
    assert summary["event"] == "run_summary"
    assert summary["claude_calls"] == 2
    assert summary["input_tokens"] == 1_005
    assert summary["cost_usd"] == round(expected, 6)
