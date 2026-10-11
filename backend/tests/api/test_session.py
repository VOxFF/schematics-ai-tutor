"""WebSocket session: session.start → evaluation; tutor.request → tutor.started → tutor.message;
board.update → evaluation, then a reaction after an editing pause."""

import time

from fastapi.testclient import TestClient

from app.main import References, app, get_claude, get_config, get_limits, get_references, get_task_cache, get_usage_log
from app.rate_limits import RateLimiter
from app.task_cache import progress_key, solved
from app.usage_log import UsageLog
from tests.conftest import FakeClaude, example_level, tutor_reply


def connect(config, claude, cache=None, limits=None):
    level, spec = example_level()
    references = References()
    references[level["id"]] = spec["complete_board"]
    app.dependency_overrides = {
        get_claude: lambda: claude,
        get_config: lambda: config,
        get_usage_log: lambda: UsageLog(None),
        get_references: lambda: references,
        get_task_cache: lambda: cache,
        get_limits: lambda: limits or RateLimiter(config["rate_limits"]),
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
        assert reply["seq"] == 0  # about the session.start board
        assert reply["message"]["chat"]["text"] == "What does the voltmeter need to measure across?"
        assert reply["evaluation"]["readings"] == {"VM1": 12.0}
    context = fake.requests[0]["messages"][0]["content"]
    assert "<reference>" in context and "none" not in context.split("<reference>")[1][:10]


def test_the_profile_joins_task_topics_and_learns_from_replies(config):
    fake = FakeClaude([tutor_reply("A voltmeter has a huge resistance, so it goes across a part.", kind="knowledge",
                                   topic_updates=[{"topic": "voltmeter", "understanding": 0, "explained": 1},
                                                  {"topic": "current", "understanding": 1, "explained": 0}])])
    client, level = connect(config, fake)
    saved = {"topics": [{"id": "current", "name": "Current", "type": "term", "definition": "Flow of charge.",
                         "introduced": 1, "understanding": 1, "explained": 2, "source": "catalog"}]}
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level, "profile": saved,
                      "progress": {"skill_level": 2, "history": []}})
        first = ws.receive_json()
        topics = {t["id"]: t for t in first["profile"]["topics"]}
        assert topics["current"]["explained"] == 2  # the saved scores are kept
        assert {"closed_loop", "voltmeter"} <= set(topics)  # the task's level and its meter joined

        ws.send_json({"type": "tutor.request", "request_id": "r1", "action": "message", "learner_text": "What's VM1?"})
        ws.receive_json()
        reply = ws.receive_json()
        assert reply["message"]["chat"] == {"kind": "knowledge", "icon": "📘", "title": "Voltmeter",
                                            "text": "A voltmeter has a huge resistance, so it goes across a part."}
        topics = {t["id"]: t for t in reply["profile"]["topics"]}
        assert topics["voltmeter"]["explained"] == 1 and topics["current"]["understanding"] == 2
    context = fake.requests[0]["messages"][0]["content"]
    assert '"voltmeter"' in context.split("<profile>")[1].split("</profile>")[0]

def test_a_resumed_task_gets_its_next_task_pregenerated(config):
    class Cache:
        def __init__(self):
            self.pregenerated = []

        def pregenerate(self, progress, count=1):
            self.pregenerated.append(progress)

    cache = Cache()
    client, level = connect(config, None, cache)
    progress = {"skill_level": 4, "history": []}
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level, "progress": progress})
        assert ws.receive_json()["type"] == "evaluation"
    assert [progress_key(p) for p in cache.pregenerated] == [progress_key(solved(progress, level))]


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
        assert reply["seq"] == 2  # about the latest board
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
    limits = RateLimiter({**config["rate_limits"], "tutor": {"calls_per_session_per_min": 0}})
    fake = FakeClaude([])
    client, level = connect(fast_reactions(config), fake, limits=limits)
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        ws.receive_json()
        ws.send_json({"type": "board.update", "seq": 1, "board": level["board"]})
        ws.receive_json()
        time.sleep(0.2)
    assert fake.requests == []


def ask_hint(ws, request_id):
    ws.send_json({"type": "tutor.request", "request_id": request_id, "action": "hint"})
    assert ws.receive_json()["type"] == "tutor.started"
    return ws.receive_json()


def test_hints_climb_the_ladder_one_level_at_a_time_up_to_three(config):
    highlight = [{"component": "VM1", "wire": None, "point": None, "style": "attention"}]
    fake = FakeClaude([tutor_reply(f"Hint {n}", highlights=highlight) for n in range(4)])
    client, level = connect(config, fake)
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        ws.receive_json()
        replies = [ask_hint(ws, f"h{n}")["message"] for n in range(4)]
    assert [r["meta"]["hint_level"] for r in replies] == [1, 2, 3, 3]  # Claude said 2 every time
    assert {r["chat"]["kind"] for r in replies} == {"hint"}
    assert replies[0]["meta"]["highlights"] == []  # level 1 names the concept only
    assert replies[1]["meta"]["highlights"] == [{"target": {"component": "VM1"}, "style": "attention"}]
    requests = [r["messages"][0]["content"].split("<request>")[1] for r in fake.requests]
    assert ['"hint_level": 1' in requests[0], '"hint_level": 3' in requests[3]] == [True, True]


def test_a_resumed_session_continues_the_ladder(config):
    fake = FakeClaude([tutor_reply("Method")])
    client, level = connect(config, fake)
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level, "hint_level": 2})
        ws.receive_json()
        assert ask_hint(ws, "h1")["message"]["meta"]["hint_level"] == 3


def test_reactions_without_progress_offer_a_hint(config):
    config = fast_reactions(config)
    config = {**config, "tutor": {**config["tutor"], "offer_hint_after_reactions": 2}}
    fake = FakeClaude([tutor_reply(f"Reaction {n}") for n in range(3)])
    client, level = connect(config, fake)
    offered = []
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        ws.receive_json()
        for seq in (1, 2, 3):  # the same board each time: the status never improves
            ws.send_json({"type": "board.update", "seq": seq, "board": level["board"]})
            assert ws.receive_json()["type"] == "evaluation"
            assert ws.receive_json()["type"] == "tutor.started"
            offered.append(ws.receive_json()["hint_offered"])
    assert offered == [False, False, True]  # the first sets the best status; then two without progress
    assert '"offer_hint": true' in fake.requests[2]["messages"][0]["content"]


def test_over_the_claude_budget_the_tutor_rests_but_evaluation_works(config):
    limits = RateLimiter(config["rate_limits"])
    limits.budget.spend(limits.budget.usd_per_day)
    fake = FakeClaude([])
    client, level = connect(fast_reactions(config), fake, limits=limits)
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        assert ws.receive_json()["type"] == "evaluation"
        ws.send_json({"type": "tutor.request", "request_id": "r1", "action": "hint"})
        error = ws.receive_json()
        assert error["code"] == "tutor_unavailable" and error["request_id"] == "r1"
        ws.send_json({"type": "board.update", "seq": 1, "board": level["board"]})
        assert ws.receive_json()["type"] == "evaluation"
        time.sleep(0.2)  # past the idle threshold: the reaction is skipped
    assert fake.requests == []


def test_oversized_learner_board_is_rejected(config):
    client, level = connect(config, FakeClaude([]))
    big = {**level["board"], "grid": {"columns": 31, "rows": 8}}
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        ws.receive_json()
        ws.send_json({"type": "board.update", "seq": 1, "board": big})
        error = ws.receive_json()
    assert error["code"] == "bad_message" and "30 x 30" in error["message"]


def test_board_updates_over_the_limit_are_coalesced_to_the_latest(config):
    limits = RateLimiter({**config["rate_limits"], "board_updates": {"per_session_per_sec": 1}})
    client, level = connect(config, None, limits=limits)
    with client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "session.start", "level": level})
        ws.receive_json()
        for seq in (1, 2, 3):
            ws.send_json({"type": "board.update", "seq": seq, "board": level["board"]})
        seqs = [ws.receive_json()["seq"], ws.receive_json()["seq"]]
    assert seqs == [1, 3]  # 2 was over the limit and replaced by 3, evaluated a second later


def test_sessions_per_ip_are_limited(config):
    limits = RateLimiter({**config["rate_limits"], "sessions": {"per_ip_per_hour": 30, "open_per_ip": 1}})
    client, level = connect(config, None, limits=limits)
    with client.websocket_connect("/ws/session") as first:
        with client.websocket_connect("/ws/session") as second:
            assert second.receive_json()["code"] == "rate_limited"
        first.send_json({"type": "session.start", "level": level})
        assert first.receive_json()["type"] == "evaluation"
    with client.websocket_connect("/ws/session") as third:  # the first one closed
        third.send_json({"type": "session.start", "level": level})
        assert third.receive_json()["type"] == "evaluation"
