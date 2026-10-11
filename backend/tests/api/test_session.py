"""WebSocket session: session.start → evaluation; tutor.request → tutor.started → tutor.message;
board.update → evaluation, then a reaction after an editing pause."""

import time

from fastapi.testclient import TestClient

from app.main import References, app, get_claude, get_config, get_references, get_usage_log
from app.usage_log import UsageLog
from tests.conftest import FakeClaude, example_level, tutor_reply


def connect(config, claude):
    level, spec = example_level()
    references = References()
    references[level["id"]] = spec["complete_board"]
    app.dependency_overrides = {
        get_claude: lambda: claude,
        get_config: lambda: config,
        get_usage_log: lambda: UsageLog(None),
        get_references: lambda: references,
    }
    return TestClient(app), level


def teardown_function():
    app.dependency_overrides = {}


def test_chat_round_trip(config):
    fake = FakeClaude([tutor_reply("What does the voltmeter need to measure across?")])
    client, level = connect(config, fake)
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        first = ws.receive_json()
        assert first["type"] == "evaluation" and first["evaluation"]["status"] == "meter_misuse"

        ws.send_json({"type": "tutor.request", "request_id": "r1", "action": "message", "learner_text": "Help?"})
        assert ws.receive_json() == {"type": "tutor.started", "request_id": "r1", "trigger": "request"}
        reply = ws.receive_json()
        assert reply["type"] == "tutor.message" and reply["request_id"] == "r1"
        assert reply["message"]["chat"]["text"] == "What does the voltmeter need to measure across?"
        assert reply["evaluation"]["readings"] == {"VM1": 12.0}
    context = fake.requests[0]["messages"][0]["content"]
    assert "<reference>" in context and "none" not in context.split("<reference>")[1][:10]


def test_request_before_start_is_no_session(config):
    client, level = connect(config, FakeClaude([]))
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "tutor.request", "request_id": "r1", "action": "message", "learner_text": "hi"})
        error = ws.receive_json()
        assert error["code"] == "no_session" and error["request_id"] == "r1"
        ws.send_json({"type": "nonsense"})
        assert ws.receive_json()["code"] == "bad_message"


def test_unresumable_board_is_session_rejected(config):
    client, level = connect(config, FakeClaude([]))
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": {**level, "board": {"grid": {}}}})
        assert ws.receive_json()["code"] == "session_rejected"


def test_saved_board_with_null_targets_resumes(config):
    """Boards saved before targets were computed still start a session (regression)."""
    client, level = connect(config, FakeClaude([]))
    old = {**level, "board": {**level["board"], "targets": {"VM1": {"value": None}}}}
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": old})
        reply = ws.receive_json()
        assert reply["type"] == "evaluation"
        assert reply["evaluation"]["status"] == "meter_misuse"


def test_no_claude_means_tutor_unavailable(config):
    client, level = connect(config, None)
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        ws.receive_json()
        ws.send_json({"type": "tutor.request", "request_id": "r1", "action": "message", "learner_text": "hi"})
        error = ws.receive_json()
        assert error["code"] == "tutor_unavailable" and error["request_id"] == "r1"


def fast_reactions(config, ms=50):
    return {**config, "tutor": {**config["tutor"], "idle_threshold_ms": ms}}


def test_editing_pause_gets_a_reaction(config):
    fake = FakeClaude([tutor_reply("What path does the current take now?")])
    client, level = connect(fast_reactions(config), fake)
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        ws.receive_json()
        for seq in (1, 2):  # a quick burst: one reaction
            ws.send_json({"type": "board.update", "seq": seq, "board": level["board"]})
            assert ws.receive_json()["seq"] == seq
        started = ws.receive_json()
        assert started["type"] == "tutor.started" and started["trigger"] == "reaction"
        reply = ws.receive_json()
        assert reply["type"] == "tutor.message" and reply["request_id"] == started["request_id"]
        assert reply["message"]["chat"]["text"] == "What path does the current take now?"
    assert len(fake.requests) == 1
    context = fake.requests[0]["messages"][0]["content"]
    assert '"trigger": "reaction"' in context and '"seq": 1' in context  # the earlier edit is in the timeline


def test_learner_message_cancels_the_pending_reaction(config):
    fake = FakeClaude([tutor_reply("Which part sets the current?")])
    client, level = connect(fast_reactions(config, 300), fake)
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        ws.receive_json()
        ws.send_json({"type": "board.update", "seq": 1, "board": level["board"]})
        ws.receive_json()
        ws.send_json({"type": "tutor.request", "request_id": "r1", "action": "message", "learner_text": "Help?"})
        assert ws.receive_json()["trigger"] == "request"
        assert ws.receive_json()["request_id"] == "r1"
        time.sleep(0.5)  # past the idle threshold: no reaction follows
    assert len(fake.requests) == 1


def test_reaction_is_skipped_over_the_rate_limit(config):
    limited = fast_reactions(config)
    limited["rate_limits"] = {**config["rate_limits"], "tutor_calls_per_session_per_min": 0}
    fake = FakeClaude([])
    client, level = connect(limited, fake)
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        ws.receive_json()
        ws.send_json({"type": "board.update", "seq": 1, "board": level["board"]})
        ws.receive_json()
        time.sleep(0.2)
    assert fake.requests == []
