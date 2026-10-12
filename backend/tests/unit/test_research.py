"""Learner experience research: records on disk, consent, active time, the 🔔 prompt and the
feedback conversation (docs/design.md §5)."""

import asyncio
import json

from app.research import MAX_GAP_S, PROMPTS, Research, ResearchLog
from app.usage_log import UsageLog
from tests.conftest import FakeClaude, text_response

LEARNER = "0b7e3c1a-5f2d-4c8e-9a1b-2c3d4e5f6a7b"
SETTINGS = {"research": {"enabled": True, "prompt_from_level": 3, "prompt_every_active_min": 10, "max_followups": 2},
            "claude": {"experience": {"model": "claude-opus-5-5", "effort": "low"}}}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def records(tmp_path):
    return [json.loads(line) for f in sorted((tmp_path / LEARNER).glob("*.jsonl")) for line in f.read_text().splitlines()]


def research(tmp_path, claude=None, consent=True, learner_id=LEARNER, clock=None):
    r = Research(ResearchLog(tmp_path), SETTINGS, claude or FakeClaude([]), UsageLog(None), "s1", clock or Clock())
    r.start({"consent": consent, "learner_id": learner_id, "name": "  Curious Otter 42 "}, {"id": "gen-1"},
            {"topics": []}, {"skill_level": 5, "history": []})
    return r


def test_without_consent_or_with_a_bad_id_nothing_is_recorded(tmp_path):
    for kwargs in ({"consent": False}, {"learner_id": "../../etc"}, {"learner_id": None}):
        r = research(tmp_path, **kwargs)
        r.board(1, {}, {}, {"status": "open_circuit"})
        assert not r.active
    assert not any(tmp_path.iterdir())


def test_records_are_timestamped_json_lines_per_learner(tmp_path):
    r = research(tmp_path)
    r.board(1, {"grid": {}}, {"nets": []}, {"status": "open_circuit"})
    r.chat("learner", {"text": "Why zero?"})
    kinds = [(x["type"], x["session_id"]) for x in records(tmp_path)]
    assert kinds == [("session", "s1"), ("board", "s1"), ("chat", "s1")]
    first = records(tmp_path)[0]
    assert first["name"] == "Curious Otter 42" and first["ts"].endswith("+00:00")


def test_the_log_stops_at_the_cap_per_learner(tmp_path):
    log = ResearchLog(tmp_path, max_mb_per_learner=0.001)  # about 1 KB
    written = [log.append(LEARNER, {"pad": "x" * 200}) for _ in range(10)]
    assert written[:3] == [True] * 3 and written[-1] is False
    assert (tmp_path / LEARNER).stat()  # the folder exists
    assert not log.append("not-a-uuid", {})


def test_the_prompt_comes_after_ten_active_minutes_from_level_three(tmp_path):
    clock = Clock()
    r = research(tmp_path, clock=clock)
    for _ in range(9):  # gaps of 2 min count as 1 min each
        r.activity()
        clock.now += 120
    r.activity()
    assert r.active_s == 9 * MAX_GAP_S
    assert r.prompt_due(3, "open_circuit") is None  # 9 active minutes
    clock.now += 60
    r.activity()  # 10 active minutes
    assert r.prompt_due(2, "open_circuit") is None  # level 2
    assert r.prompt_due(3, "short_circuit") is None  # never during a short
    prompt = r.prompt_due(3, "open_circuit")
    assert prompt == {"kind": "experience", "icon": "🔔", "title": None, "text": PROMPTS[0], "terms": []}
    assert r.thread_open and r.active_s == 0 and r.prompt_due(3, "open_circuit") is None


def test_the_conversation_asks_at_most_two_follow_ups(tmp_path):
    def answer(text, done=False):
        return text_response({"handoff": False, "text": text, "done": done})

    fake = FakeClaude([answer("What felt vague?"), answer("Which hint was it?"), answer("Thanks, that helps!", done=False)])
    r = research(tmp_path, claude=fake)
    r.active_s = 600
    r.prompt_due(3, "open_circuit")
    for text in ("Hints are vague", "The second one", "The one about R2"):
        reply = asyncio.run(r.reply(text))
    assert reply["text"] == "Thanks, that helps!" and not r.thread_open  # closed after two follow-ups
    assert "<followups_left>0</followups_left>" in fake.requests[2]["messages"][0]["content"]
    turns = [x for x in records(tmp_path) if x["type"] == "experience"]
    assert all(t["experience"] for t in turns) and len(turns) == 7  # prompt + 3 learner + 3 Claude
    assert turns[-1]["done"] is True


def test_an_unanswered_thread_closes_after_three_active_minutes(tmp_path):
    clock = Clock()
    r = research(tmp_path, clock=clock)
    r.active_s = 600
    r.prompt_due(3, "open_circuit")
    for _ in range(3):  # the learner keeps building: the thread stays open meanwhile
        r.activity()
        assert r.thread_open
        clock.now += 60
    r.activity()
    assert not r.thread_open
    assert records(tmp_path)[-1] == {**records(tmp_path)[-1], "type": "experience", "closed": "timeout"}


def test_a_message_for_the_tutor_is_handed_off(tmp_path):
    fake = FakeClaude([text_response({"handoff": True, "text": "", "done": False})])
    r = research(tmp_path, claude=fake)
    r.active_s = 600
    r.prompt_due(3, "open_circuit")
    assert asyncio.run(r.reply("Why does the ammeter read zero?")) is None
    assert not r.thread_open
    learner, closed = records(tmp_path)[-2:]
    assert learner["role"] == "learner" and learner["handoff"] is True and closed["closed"] == "handoff"


def test_active_time_continues_from_the_browser_across_connections(tmp_path):
    clock = Clock()
    r = Research(ResearchLog(tmp_path), SETTINGS, FakeClaude([]), UsageLog(None), "s2", clock)
    clock.now = 1000.0
    # The previous task's last activity was 20 s ago: that gap (reading the new task) counts too.
    r.start({"consent": True, "learner_id": LEARNER, "active_s": 570, "last_ts": 980.0}, {}, {}, {})
    assert r.state() == {"active_s": 570, "last_ts": 980.0, "thread": None}
    r.activity()
    clock.now += 10
    r.activity()
    assert r.prompt_due(3, "open_circuit") is not None  # 570 s from earlier tasks + 20 s between + 10 s now
    assert r.state()["active_s"] == 0 and r.state()["last_ts"] == 1010.0
    r.start({"consent": True, "learner_id": LEARNER, "active_s": 0, "last_ts": 0.0}, {}, {}, {})
    r.activity()
    assert r.active_s == MAX_GAP_S  # a stale last_ts adds one capped gap at most
    r.start({"consent": True, "learner_id": LEARNER, "last_ts": 10 ** 12}, {}, {}, {})
    assert r.last_activity != 10 ** 12  # a future time is ignored
    for saved in (-5, 10 ** 9, "600", True):  # clamped or ignored
        r.start({"consent": True, "learner_id": LEARNER, "active_s": saved}, {}, {}, {})
        assert 0 <= r.state()["active_s"] <= 600
    r.start({"consent": False}, {}, {}, {})
    assert r.state() is None


def test_an_open_thread_survives_a_reconnect_and_waits_for_the_answer(tmp_path):
    fake = FakeClaude([text_response({"handoff": False, "text": "Which hint was it?", "done": False})])
    r = research(tmp_path)
    r.active_s = 600
    r.prompt_due(3, "open_circuit")
    assert r.awaiting  # the question waits: the session holds reactions
    saved = r.state()["thread"]
    assert saved["turns"][0]["role"] == "tutor" and saved["followups"] == 0

    # A reload: a new session restores the thread from the browser and takes the answer.
    again = Research(ResearchLog(tmp_path), SETTINGS, fake, UsageLog(None), "s3", Clock())
    again.start({"consent": True, "learner_id": LEARNER, "thread": saved}, {}, {}, {})
    assert again.thread_open and again.awaiting
    reply = asyncio.run(again.reply("The hints are vague"))
    assert reply["text"] == "Which hint was it?" and again.awaiting  # a follow-up waits again
    assert "Quick check-in" in fake.requests[0]["messages"][0]["content"]  # the restored prompt is in the thread

    for bad in ("x", {"turns": "x"}, {"turns": [{"role": "admin", "text": "hi"}]}):
        again.start({"consent": True, "learner_id": LEARNER, "thread": bad}, {}, {}, {})
        assert not again.thread_open
