"""WebSocket session: session.start → evaluation; tutor.request → tutor.started → tutor.message."""

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


def test_request_before_start_and_bad_messages(config):
    client, level = connect(config, FakeClaude([]))
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "tutor.request", "action": "message", "learner_text": "hi"})
        assert ws.receive_json()["code"] == "bad_message"
        ws.send_json({"type": "nonsense"})
        assert ws.receive_json()["code"] == "bad_message"
        ws.send_json({"type": "session.start", "level": {**level, "board": {"grid": {}}}})
        assert ws.receive_json()["code"] == "bad_message"


def test_no_claude_means_tutor_unavailable(config):
    client, level = connect(config, None)
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        ws.receive_json()
        ws.send_json({"type": "tutor.request", "request_id": "r1", "action": "message", "learner_text": "hi"})
        error = ws.receive_json()
        assert error["code"] == "tutor_unavailable" and error["request_id"] == "r1"
