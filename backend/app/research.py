"""Learner experience research (docs/design.md §5): consent, records, the 🔔 feedback prompt and the
feedback conversation.

`session.py` only calls the hooks of `Research`; without consent, or with research turned off,
every hook does nothing. Records are JSON lines in research/<learner_id>/<date>.jsonl, collected
with research.sh over fly ssh; nothing serves them over HTTP.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .jsonfmt import dumps

LEARNER_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_NAME = 40
MAX_THREAD_TURNS = 12  # a restored thread is cut to this many turns
MAX_TURN_TEXT = 2000
MAX_GAP_S = 60  # a gap between interactions counts as active time up to this long
ICON = "🔔"
PROMPTS = [
    "Quick check-in: how is the tutor working for you so far? Anything confusing or annoying?",
    "How are you finding the tutor's help lately? Too much, too little, or about right?",
    "A moment to share your thoughts: what has the tutor done well, and what could it do better?",
]

EXPERIENCE_PROMPT = """You are checking in with a learner who uses an AI electronics tutor: a web app
where they build DC circuits on a grid while a tutor coaches them in a chat. You asked them
how the tutor is working for them. Your job is to understand their experience, not to teach.

- Reply to what they just said with at most one short follow-up question: what exactly
  happened, what they expected, or what would have helped.
- Never tutor: no physics, no hints, no circuit advice. If they ask about the circuit, say
  the tutor will help as soon as they are back on the board.
- Be warm and brief: one or two sentences.
- When followups_left is 0, or they have nothing more to add, thank them in one sentence
  and set done to true. Otherwise set done to false.
- Messages here may also be meant for the tutor: they keep building while this thread is
  open. If the learner's latest message is about their circuit or task (a question or a
  remark for the tutor) rather than about their experience with the tutor or the app, set
  handoff to true and leave text empty: the tutor answers it, and this thread ends.
  Feedback about the tutor's help, even when it mentions the circuit, is not a handoff.

Input: <thread> (your check-in and the conversation so far) and <followups_left>.
"""

EXPERIENCE_SCHEMA = {
    "type": "object",
    "properties": {"handoff": {"type": "boolean"}, "text": {"type": "string"}, "done": {"type": "boolean"}},
    "required": ["handoff", "text", "done"],
    "additionalProperties": False,
}


class ResearchLog:
    """The records on disk, one folder per learner, with a size cap per learner."""

    def __init__(self, directory: Path, max_mb_per_learner: float = 20, usage_log=None):
        self.directory = Path(directory)
        self.cap = int(max_mb_per_learner * 1024 * 1024)
        self.usage_log = usage_log
        self.sizes: dict[str, int] = {}  # bytes per learner, read from disk on first use
        self.full: set[str] = set()

    @classmethod
    def from_config(cls, config: dict, root: Path, usage_log=None) -> "ResearchLog | None":
        """None when research is off. SCHEMATICS_RESEARCH_DIR overrides `research.dir` (the Fly volume)."""
        settings = config.get("research") or {}
        if not settings.get("enabled"):
            return None
        directory = Path(os.environ.get("SCHEMATICS_RESEARCH_DIR") or root / settings.get("dir", "research"))
        return cls(directory, settings.get("max_mb_per_learner", 20), usage_log)

    def append(self, learner_id: str, record: dict) -> bool:
        """Append one record; False when the learner's cap is reached (logged once)."""
        if not LEARNER_ID.match(learner_id):
            return False
        folder = self.directory / learner_id
        if learner_id not in self.sizes:
            self.sizes[learner_id] = sum(f.stat().st_size for f in folder.glob("*.jsonl")) if folder.is_dir() else 0
        line = json.dumps(record, ensure_ascii=False) + "\n"
        size = len(line.encode())
        if self.sizes[learner_id] + size > self.cap:
            if learner_id not in self.full and self.usage_log:
                self.usage_log.event("research_cap_reached", learner_id=learner_id)
            self.full.add(learner_id)
            return False
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
            f.write(line)
        self.sizes[learner_id] += size
        return True


class Research:
    """One learning session's research: inert unless the learner consented."""

    def __init__(self, log: ResearchLog | None, config: dict, claude, usage_log, session_id: str = "",
                 clock=time.time):  # wall-clock: the last activity's time is kept across connections
        self.log = log
        self.settings = config.get("research") or {}
        self.claude_settings = (config.get("claude") or {}).get("experience") or {}
        self.claude = claude
        self.usage_log = usage_log
        self.session_id = session_id
        self.clock = clock
        self.learner_id: str | None = None
        self.last_activity: float | None = None
        self.active_s = 0.0  # active time since the last prompt (or the session start)
        self.prompts = 0
        self.thread: list[dict] | None = None  # the open feedback conversation's turns
        self.followups = 0
        self.thread_idle_s = 0.0  # active time since the thread last heard from the learner

    @property
    def active(self) -> bool:
        return self.learner_id is not None

    @property
    def thread_open(self) -> bool:
        return self.thread is not None

    @property
    def awaiting(self) -> bool:
        """The 🔔 question (the prompt or a follow-up) is waiting for the learner's answer: the
        session holds tutor reactions meanwhile, so they don't bury it."""
        return self.thread_open and self.thread[-1]["role"] == "tutor"

    def _record(self, kind: str, **fields) -> None:
        if self.active:
            now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            self.log.append(self.learner_id, {"ts": now, "session_id": self.session_id, "type": kind, **fields})

    def start(self, research, level: dict, profile: dict, progress) -> None:
        """Turn recording on when the learner consented with a well-formed learner_id. Active time
        continues from `research.active_s` and `last_ts`: each task is a new connection, so the
        browser keeps them, and the gap since the previous task's last activity counts too."""
        self.learner_id = None
        if self.log is None or not isinstance(research, dict) or research.get("consent") is not True:
            return
        learner_id = research.get("learner_id")
        if not isinstance(learner_id, str) or not LEARNER_ID.match(learner_id):
            return
        self.learner_id = learner_id
        saved = research.get("active_s")
        limit = self.settings.get("prompt_every_active_min", 10) * 60
        if isinstance(saved, (int, float)) and not isinstance(saved, bool):
            self.active_s = min(max(float(saved), 0.0), limit)
        last = research.get("last_ts")
        if isinstance(last, (int, float)) and not isinstance(last, bool) and last <= self.clock():
            self.last_activity = float(last)  # any gap still counts at most MAX_GAP_S
        self._restore_thread(research.get("thread"))
        name = research.get("name")
        name = name.strip()[:MAX_NAME] if isinstance(name, str) and name.strip() else "Anonymous"
        self._record("session", name=name, level=level, profile=profile, progress=progress)

    def state(self) -> dict | None:
        """What the browser keeps between connections: the active time since the last prompt."""
        if not self.active:
            return None
        thread = ({"turns": self.thread, "followups": self.followups, "idle_s": round(self.thread_idle_s)}
                  if self.thread_open else None)
        return {"active_s": round(self.active_s), "last_ts": self.last_activity, "thread": thread}

    def _restore_thread(self, saved) -> None:
        """An open feedback conversation from the browser: a reload or a reconnect doesn't end it."""
        self.thread = None
        if not isinstance(saved, dict) or not isinstance(saved.get("turns"), list):
            return
        turns = [{"role": t["role"], "text": t["text"][:MAX_TURN_TEXT]} for t in saved["turns"][-MAX_THREAD_TURNS:]
                 if isinstance(t, dict) and t.get("role") in ("tutor", "learner") and isinstance(t.get("text"), str)]
        if not turns:
            return
        followups, idle = saved.get("followups"), saved.get("idle_s")
        self.thread = turns
        self.followups = min(max(followups, 0), 10) if isinstance(followups, int) and not isinstance(followups, bool) else 0
        self.thread_idle_s = min(max(float(idle), 0.0), 3600.0) if isinstance(idle, (int, float)) and not isinstance(idle, bool) else 0.0

    def board(self, seq: int, board: dict, graph: dict, evaluation: dict) -> None:
        self._record("board", seq=seq, board=board, graph=graph, evaluation=evaluation)

    def chat(self, role: str, message: dict, **extra) -> None:
        """A learner turn ({text} or {action}) or a tutor reply ({meta, chat})."""
        self._record("chat", role=role, message=message, **extra)

    def activity(self) -> None:
        """An edit or a message: adds the time since the last one, up to MAX_GAP_S. An open thread
        that the learner hasn't answered for `thread_timeout_active_min` closes."""
        now = self.clock()
        if self.last_activity is not None:
            gap = min(now - self.last_activity, MAX_GAP_S)
            self.active_s += gap
            self.thread_idle_s += gap
        self.last_activity = now
        if self.thread_open and self.thread_idle_s >= self.settings.get("thread_timeout_active_min", 3) * 60:
            self.close_thread("timeout")

    def prompt_due(self, curriculum_level: int, status: str) -> dict | None:
        """The 🔔 chat message when it's time to ask (it opens the thread), else None. The session
        checks that the tutor isn't replying."""
        if not self.active or self.claude is None or self.thread_open or status == "short_circuit":
            return None
        if curriculum_level < self.settings.get("prompt_from_level", 3):
            return None
        if self.active_s < self.settings.get("prompt_every_active_min", 10) * 60:
            return None
        text = PROMPTS[self.prompts % len(PROMPTS)]
        self.prompts += 1
        self.active_s = 0.0
        self.thread, self.followups, self.thread_idle_s = [{"role": "tutor", "text": text}], 0, 0.0
        self._record("experience", experience=True, role="tutor", text=text, prompt=True)
        return {"kind": "experience", "icon": ICON, "title": None, "text": text, "terms": []}

    async def reply(self, learner_text: str) -> dict | None:
        """Claude's answer in the feedback conversation: a follow-up question, or thanks, which
        closes the thread. None when the message is for the tutor (a handoff): the thread closes
        and the session passes the message on. Raises anthropic.APIError on API failure (the
        thread stays open)."""
        self.thread.append({"role": "learner", "text": learner_text})
        self.thread_idle_s = 0.0
        left = max(self.settings.get("max_followups", 2) - self.followups, 0)
        settings = self.claude_settings
        content = f"<thread>\n{dumps(self.thread)}\n</thread>\n\n<followups_left>{left}</followups_left>"
        started = time.monotonic()
        response = await self.claude.with_options(timeout=settings.get("timeout_s", 30)).messages.create(
            model=settings.get("model", "claude-opus-5-5"),
            max_tokens=settings.get("max_tokens", 16000),
            system=[{"type": "text", "text": EXPERIENCE_PROMPT, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": settings.get("effort", "low"),
                           "format": {"type": "json_schema", "schema": EXPERIENCE_SCHEMA}},
            messages=[{"role": "user", "content": content}],
        )
        self.usage_log.claude_call(purpose="experience", model=settings.get("model", "claude-opus-5-5"),
                                   usage=_usage(response), session_id=self.session_id,
                                   stop_reason=response.stop_reason,
                                   duration_ms=int((time.monotonic() - started) * 1000))
        answer = _parse(response)
        # The learner's turn is recorded as a reply to the check-in either way, flagged when handed off.
        self._record("experience", experience=True, role="learner", text=learner_text,
                     **({"handoff": True} if answer["handoff"] else {}))
        if answer["handoff"]:
            self.close_thread("handoff")
            return None
        done = answer["done"] or left == 0
        text = answer["text"] or "Thank you for sharing!"
        self.thread.append({"role": "tutor", "text": text})
        self._record("experience", experience=True, role="tutor", text=text, done=done)
        if done:
            self.thread = None
        else:
            self.followups += 1
        return {"kind": "experience", "icon": ICON, "title": None, "text": text, "terms": []}

    def close_thread(self, reason: str) -> None:
        """The conversation ends early: a hint request, a handoff, or no reply for a while."""
        if self.thread_open:
            self.thread = None
            self._record("experience", experience=True, closed=reason)


def _parse(response) -> dict:
    text = next((b.text for b in response.content if b.type == "text"), None)
    try:
        answer = json.loads(text) if text else {}
    except json.JSONDecodeError:
        answer = {}
    return {"text": str(answer.get("text") or "").strip(), "done": bool(answer.get("done", True)),
            "handoff": answer.get("handoff") is True}


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    fields = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    return {f: getattr(usage, f, 0) or 0 for f in fields}
