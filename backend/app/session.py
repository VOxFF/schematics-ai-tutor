"""WebSocket learning session (docs/contract.md §1): session.start, board.update, tutor.request.

Every board.update records a snapshot; when editing pauses for `tutor.idle_threshold_ms`, the
tutor reacts to the snapshots since its last call. A learner message or hint request cancels a
pending reaction. The session runs the task's hint ladder (docs/tutor.md §3) and keeps the learner
profile, which the reply composer updates with each reply (docs/design.md §4). With the learner's
consent, research.py records the session and runs the 🔔 feedback prompt (docs/design.md §5). Its tutor calls,
board updates and board size are rate limited (rate_limits.py, docs/design.md §6).
"""

import asyncio
import time
import uuid

import anthropic

from .claude_status import available
from .evaluate import STATUS_RANK, evaluate
from .graph import circuit_key, to_graph
from .grid import validate_grid
from .learner_profile import focus, join, sanitize
from .rate_limits import RateLimiter
from .reply_composer import compose, guide
from .research import Research, ResearchLog
from .task_cache import solved
from .tutor import MAX_HINT, answer, fallback_message


RESTING = "The tutor is taking a short break; your circuit is still checked live."
GUIDE_DELAY_S = 1.0  # the how-to follows the welcome after the learner has glanced at the screen


class Session:
    def __init__(self, send, *, config: dict, claude, usage_log, references: dict, task_cache=None,
                 limits: RateLimiter | None = None, research_log: ResearchLog | None = None):
        self.send = send  # async callable taking a message dict
        self.config = config
        self.claude = claude
        self.usage_log = usage_log
        self.references = references
        self.task_cache = task_cache  # pre-generation (docs/design.md §3), or None
        self.limits = limits or RateLimiter(config.get("rate_limits", {}))
        self.id = uuid.uuid4().hex[:12]
        self.level: dict | None = None
        self.board: dict | None = None
        self.seq = 0  # seq of the board in `self.board` (0: the board from session.start)
        self.history: list[dict] = []
        self.busy = False
        self.deferred_update: dict | None = None  # the latest board.update over the rate limit
        self.deferred: asyncio.Task | None = None  # applies it once the limit allows
        self.tasks: set[asyncio.Task] = set()
        self.snapshots: list[dict] = []  # boards since the tutor's last call, oldest first
        self.started_at = time.monotonic()
        self.idle: asyncio.Task | None = None  # pending reaction timer
        self.quiet: asyncio.Task | None = None  # pending 🔔 prompt check, after a longer pause
        self.hint_level = 0  # highest hint rung given in this task (0-4)
        self.best_rank = -1  # best status reached in this task, by STATUS_RANK
        self.stalled = 0  # reactions in a row without beating best_rank
        self.replied_key = None  # circuit_key of the board Claude last replied about
        self.unchanged = 0  # pauses in a row skipped because the circuit hadn't changed since that reply
        self.profile = {"topics": []}  # the learner profile, kept by the browser between sessions
        self.research = Research(research_log, config, claude, usage_log, self.id)
        self.skill_level = 1

    async def handle(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "session.start":
            await self.start(message)
        elif kind == "board.update":
            await self.update(message)
        elif kind == "tutor.request":
            await self.request(message)
        else:
            await self.error("bad_message", f"unknown message type {kind!r}")

    async def error(self, code: str, text: str, request_id: str | None = None) -> None:
        await self.send({"type": "error", "code": code, "message": text, "request_id": request_id})

    def _evaluate(self) -> dict:
        return evaluate(self.board, self.config.get("evaluator"))

    async def _set_board(self, board, code: str = "bad_message") -> bool:
        errors = validate_grid(board, allow_null_targets=True) if isinstance(board, dict) else ["board must be an object"]
        errors = errors or self.limits.grid_errors(board)
        if errors:
            await self.error(code, "; ".join(errors[:5]))
            return False
        self.board = board
        return True

    async def start(self, message: dict) -> None:
        level = message.get("level")
        # session_rejected tells the client its saved task can't be resumed (e.g. after an update).
        if not isinstance(level, dict) or not isinstance(level.get("board"), dict):
            await self.error("session_rejected", "session.start needs a level with a board")
            return
        if not await self._set_board(message.get("board") or level["board"], code="session_rejected"):
            return
        self.seq = 0
        self.level = level
        self.history = [t for t in message.get("history", []) if isinstance(t, dict)]
        hint_level = message.get("hint_level", 0)
        self.hint_level = min(max(hint_level, 0), MAX_HINT) if isinstance(hint_level, int) else 0
        self.usage_log.event("session_started", session_id=self.id, level_id=level.get("id"))
        progress = message.get("progress")
        skill = progress.get("skill_level") if isinstance(progress, dict) else None
        self.skill_level = skill if isinstance(skill, int) and skill >= 1 else 1
        # The task's topics join the profile; the browser saves the profile that comes back.
        self.profile = sanitize(message.get("profile"))
        join(self.profile, level, level["board"], self.skill_level)
        self.research.start(message.get("research"), level, self.profile, progress)
        await self.send({"type": "evaluation", "seq": 0, "evaluation": self._evaluate(), "profile": self.profile,
                         **self._research_state()})
        if message.get("guide") is True:  # the browser's chat has no how-to yet (docs/gui.md §7)
            self._start_task(self._send_guide())
        # A resumed task (e.g. after a server restart, which empties the cache) gets its next
        # task generated in the background too, so Next doesn't wait.
        if self.task_cache and isinstance(progress, dict) and isinstance(progress.get("history"), list):
            try:
                self.task_cache.pregenerate(solved({"skill_level": int(progress.get("skill_level", 1)),
                                                    "history": progress["history"]}, level))
            except (KeyError, TypeError, ValueError):
                pass  # an incomplete saved level: Next generates on request

    async def update(self, message: dict) -> None:
        if self.level is None:
            await self.error("no_session", "send session.start first")
            return
        if not self.limits.board_updates.allow(self.id):
            # Over the limit: keep only the latest board, and evaluate it as soon as the limit allows.
            self.deferred_update = message
            if self.deferred is None:
                self.deferred = self._start_task(self._apply_deferred())
            return
        self.deferred_update = None  # this board is newer than any deferred one
        await self._apply_update(message)

    async def _apply_deferred(self) -> None:
        while self.deferred_update is not None:
            await asyncio.sleep(max(self.limits.board_updates.retry_after(self.id), 0.01))
            if self.deferred_update is not None and self.limits.board_updates.allow(self.id):
                message, self.deferred_update = self.deferred_update, None
                await self._apply_update(message)
        self.deferred = None

    async def _apply_update(self, message: dict) -> None:
        if await self._set_board(message.get("board")):
            self.seq = message.get("seq", 0)
            evaluation = self._evaluate()
            self._record(message.get("seq", 0), evaluation)
            self.research.board(self.seq, self.board, self.snapshots[-1]["graph"], evaluation)
            self.research.activity()
            await self.send({"type": "evaluation", "seq": message.get("seq", 0), "evaluation": evaluation,
                             **self._research_state()})
            self._restart_idle_timer()

    def _record(self, seq: int, evaluation: dict) -> None:
        limit = self.config.get("tutor", {}).get("max_snapshots", 10)
        self.snapshots.append({"seq": seq, "t_ms": int((time.monotonic() - self.started_at) * 1000),
                               "graph": to_graph(self.board)[0], "evaluation": evaluation})
        self.snapshots = self.snapshots[-limit:]

    def _start_task(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def _cancel_idle_timer(self) -> None:
        if self.idle and not self.idle.done():
            self.idle.cancel()
        self.idle = None

    def _restart_idle_timer(self) -> None:
        """A burst of quick edits gives one reaction: each edit restarts the timer. With research on,
        the 🔔 prompt's longer timer restarts too."""
        self._cancel_idle_timer()
        if self.claude is not None:
            self.idle = self._start_task(self._react_after_pause())
        if self.quiet and not self.quiet.done():
            self.quiet.cancel()
        if self.research.active and self.claude is not None:
            self.quiet = self._start_task(self._prompt_after_quiet())

    async def _prompt_after_quiet(self) -> None:
        """The 🔔 prompt waits for a real break: `research.prompt_idle_s` without edits, and the tutor
        done replying. A pause between two drops is the middle of a move, not a break."""
        await asyncio.sleep(self.config.get("research", {}).get("prompt_idle_s", 8))
        for _ in range(60):  # the reaction to the same pause may still be running
            if not self.busy:
                break
            await asyncio.sleep(0.5)
        else:
            return
        self.quiet = None
        if not self.limits.claude_allowed() or not available(self.claude):
            return  # its replies need Claude
        evaluation = self._evaluate()
        prompt = self.research.prompt_due((self.level.get("curriculum") or {}).get("level") or 1, evaluation["status"])
        if prompt:
            await self._send_plain(f"research-{uuid.uuid4().hex[:8]}", prompt, evaluation)

    async def _react_after_pause(self) -> None:
        await asyncio.sleep(self.config.get("tutor", {}).get("idle_threshold_ms", 1500) / 1000)
        self.idle = None
        if self.busy:
            return  # a call is running; the next pause reacts to these snapshots too
        if not self.limits.claude_allowed():
            self.usage_log.event("reaction_skipped", session_id=self.id, reason="claude_budget")
            return
        if not available(self.claude):
            self.usage_log.event("reaction_skipped", session_id=self.id, reason="claude_down")
            return
        # The 🔔 question waits for the learner's answer: reactions would bury it (docs/design.md §5).
        if self.research.awaiting:
            self.usage_log.event("reaction_skipped", session_id=self.id, reason="feedback_pending")
            return
        # The same circuit as Claude's last reply: same evaluation, nothing new to say. After
        # `tutor.react_after_unchanged` such pauses Claude is called anyway, to guide (docs/design.md §3).
        unchanged = circuit_key(to_graph(self.board)[0]) == self.replied_key
        if unchanged and self.unchanged + 1 < self.config.get("tutor", {}).get("react_after_unchanged", 4):
            self.unchanged += 1
            self.stalled += 1  # no progress: counts toward the hint offer like a reaction
            self.usage_log.event("reaction_skipped", session_id=self.id, reason="unchanged")
            return
        unchanged_moves = self.unchanged + 1 if unchanged else 0
        if not self.limits.tutor.allow(self.id):
            self.usage_log.event("reaction_skipped", session_id=self.id, reason="rate_limited")
            return
        self.unchanged = 0
        self.busy = True
        request_id = f"react-{uuid.uuid4().hex[:8]}"
        await self.send({"type": "tutor.started", "request_id": request_id, "trigger": "reaction"})
        await self._answer(request_id, None, offer_hint=self._offer_hint(), unchanged_moves=unchanged_moves)

    def _offer_hint(self) -> bool:
        """Whether this reaction offers a hint: after `tutor.offer_hint_after_reactions` reactions in
        a row without the status beating the best one in this task (docs/tutor.md §3)."""
        status = self._evaluate()["status"]
        rank = STATUS_RANK.index(status) if status in STATUS_RANK else -1
        if rank > self.best_rank:
            self.best_rank, self.stalled = rank, 0
            return False
        self.stalled += 1
        if status == "solved" or self.hint_level >= MAX_HINT:
            return False
        if self.stalled >= self.config.get("tutor", {}).get("offer_hint_after_reactions", 3):
            self.stalled = 0
            return True
        return False

    async def request(self, message: dict) -> None:
        request_id = message.get("request_id") or uuid.uuid4().hex[:8]
        text = str(message.get("learner_text") or "").strip()
        action = message.get("action")
        if self.level is None:
            # The server lost or never had the session (e.g. it restarted); the client resends session.start.
            await self.error("no_session", "send session.start first", request_id)
        elif action not in ("message", "hint") or (action == "message" and not text):
            await self.error("bad_message", "tutor.request needs action 'hint', or 'message' with learner_text",
                             request_id)
        elif not available(self.claude) or not self.limits.claude_allowed():
            # No Claude, Claude down or the budget spent: a plain message, not an error (docs/design.md §6).
            await self._resting(request_id, text or None)
        elif self.busy or not self.limits.tutor.allow(self.id):
            await self.error("rate_limited", "The tutor needs a moment; try again shortly.", request_id)
        else:
            self._cancel_idle_timer()  # the learner's message takes priority over a pending reaction
            self.busy = True
            self.research.activity()
            await self.send({"type": "tutor.started", "request_id": request_id, "trigger": "request"})
            if action == "message" and self.research.thread_open:
                # The learner answers the 🔔 check-in: the feedback conversation, not the tutor.
                self._start_task(self._experience(request_id, text))
                return
            self.research.close_thread("hint")  # a hint request goes back to tutoring
            # The server decides a hint's rung: one above the highest given, at most 4.
            hint = min(self.hint_level + 1, MAX_HINT) if action == "hint" else 0
            # Run the Claude call in the background so the session keeps receiving messages.
            self._start_task(self._answer(request_id, text or None, hint=hint, asked=True))

    async def _answer(self, request_id: str, text: str | None, *, hint: int = 0, asked: bool = False,
                      offer_hint: bool = False, unchanged_moves: int = 0) -> None:
        """A tutor call for a learner request (`asked`: a message, or a hint of level `hint`) or
        a reaction, which may end by offering a hint. A reaction that comes back after a newer edit
        is dropped unless it still holds (a lesson, or praise while still solved); the reaction to
        the newer board follows (docs/design.md §3)."""
        # Earlier boards since the last call; the current board is added by the tutor context.
        snapshots, self.snapshots = self.snapshots[:-1], []
        board, seq = self.board, self.seq  # edits may arrive during the call; the reply is about this board
        try:
            reference = self.references.get(self.level.get("id"))
            reply, evaluation = await answer(
                self.claude, self.config, self.usage_log, level=self.level, board=board,
                reference=reference, history=self.history, learner_text=text, snapshots=snapshots,
                session_id=self.id, hint_level=hint, offer_hint=offer_hint, unchanged_moves=unchanged_moves,
                formulas=self._formulas(),
                profile={"skill_level": self.skill_level, "focus": focus(self.profile, self.skill_level)},
            )
            if not asked and self.seq != seq and not self._still_true(reply):
                # Out of date: its text would answer a board that's gone. Nothing of it is kept.
                self.usage_log.event("reaction_dropped", session_id=self.id, seq=seq, current_seq=self.seq)
                self.research.chat("tutor", reply, seq=seq, trigger="reaction", dropped=True)
                if offer_hint:  # the offer it carried moves to the next reaction
                    self.stalled = max(self.stalled, self.config.get("tutor", {}).get("offer_hint_after_reactions", 3) - 1)
                await self.send({"type": "tutor.dropped", "request_id": request_id})
            else:
                await self._deliver(request_id, reply, evaluation, board, seq, text, hint, asked, offer_hint)
        except anthropic.APIError as e:
            purpose = "tutor_request" if asked else "tutor_reaction"
            self.usage_log.event("claude_error", purpose=purpose, session_id=self.id, error=str(e)[:300])
            if asked and not available(self.claude):  # the failure marked Claude down
                await self._resting(request_id, text)
            else:
                # A failed reaction carries no request_id: the client stops "thinking" without a chat error.
                await self.error("tutor_unavailable", "The tutor is unavailable right now; try again shortly.",
                                 request_id if asked else None)
        finally:
            self.busy = False
        if self.snapshots and self.idle is None:
            self._restart_idle_timer()  # edits arrived during the call: react to them after a pause

    async def _resting(self, request_id: str, text: str | None) -> None:
        """The tutor without Claude (docs/design.md §6): the plain message for the board's status,
        with a note that the tutor is resting. A hint asked now doesn't count on the ladder."""
        self.usage_log.event("tutor_resting", session_id=self.id, claude=self.claude is not None)
        evaluation = self._evaluate()
        reply = fallback_message(evaluation["status"])
        reply["chat"]["kind"] = "feedback"
        reply["chat"]["text"] = RESTING + "\n\n" + reply["chat"]["text"]
        await self._deliver(request_id, reply, evaluation, self.board, self.seq, text, 0, True, False)

    def _formulas(self) -> bool:
        """Whether replies may carry a formula: from curriculum level `tutor.formulas_from_level`."""
        level = (self.level.get("curriculum") or {}).get("level") or 1
        return level >= self.config.get("tutor", {}).get("formulas_from_level", 2)

    def _still_true(self, reply: dict) -> bool:
        """Whether an out-of-date reaction still holds for the current board (docs/design.md §3): a
        lesson always does; praise while the board is still solved. Questions, nudges and feedback
        describe the old board. A kept one is shown as text only: its `seq` makes the client drop
        its highlights and evaluation."""
        kind = reply["chat"]["kind"]
        return kind == "knowledge" or (kind == "praise" and self._evaluate()["status"] == "solved")

    async def _deliver(self, request_id: str, reply: dict, evaluation: dict, board: dict, seq: int,
                       text: str | None, hint: int, asked: bool, offer_hint: bool) -> None:
        """Compose a reply that's still current, record it, and send it."""
        self.replied_key = circuit_key(to_graph(board)[0])
        reply["chat"], dropped = compose(reply, self.profile, self.skill_level)
        if dropped:
            self.usage_log.event("profile_dropped", session_id=self.id, dropped=dropped)
        if hint:
            self.hint_level = max(self.hint_level, hint)
            self.stalled = 0
            self.history.append({"role": "learner", "text": f"(asked for hint {hint}/{MAX_HINT}) {text or ''}".strip()})
        elif text is not None:
            self.history.append({"role": "learner", "text": text})
        self.history.append({"role": "tutor", "text": reply["chat"]["text"]})
        if hint:
            self.research.chat("learner", {"action": "hint", "hint_level": hint, "text": text})
        elif text is not None:
            self.research.chat("learner", {"text": text})
        self.research.chat("tutor", reply, seq=seq, trigger="request" if asked else "reaction")
        # `seq` names the board the reply is about: for a message or hint answered after a newer
        # edit, the client shows the text but drops the highlights and the evaluation.
        await self.send({"type": "tutor.message", "request_id": request_id, "seq": seq,
                         "evaluation": evaluation, "message": reply, "hint_offered": offer_hint,
                         "profile": self.profile, **self._research_state()})

    def _research_state(self) -> dict:
        """`research` for an outgoing message, when recording is on: the browser keeps it (docs/design.md §5)."""
        state = self.research.state()
        return {"research": state} if state else {}

    async def _send_guide(self) -> None:
        """The how-to, 1 s after the session starts, and later while a tutor call is running, so it
        never cuts into a reply (docs/gui.md §7, Guide)."""
        await asyncio.sleep(GUIDE_DELAY_S)
        for _ in range(60):
            if not self.busy:
                break
            await asyncio.sleep(0.5)
        chat = guide(self.profile)
        self.research.chat("tutor", {"chat": chat}, seq=self.seq, trigger="guide")
        self.usage_log.event("guide_sent", session_id=self.id)
        await self._send_plain(f"guide-{uuid.uuid4().hex[:8]}", chat, self._evaluate())

    async def _send_plain(self, request_id: str, chat: dict, evaluation: dict) -> None:
        """A message that isn't a tutor reply (the 🔔 conversation, the guide), sent like one about
        the current board, with empty `meta`."""
        meta = {"principle": None, "highlights": [], "hint_level": 0, "misconception": None,
                "topic_updates": [], "new_topic": None}
        await self.send({"type": "tutor.message", "request_id": request_id, "seq": self.seq, "evaluation": evaluation,
                         "message": {"meta": meta, "chat": chat}, "hint_offered": False, "profile": self.profile,
                         **self._research_state()})

    async def _experience(self, request_id: str, text: str) -> None:
        """The learner's answer in the feedback conversation and Claude's follow-up (docs/design.md §5).
        A message meant for the tutor is handed off: the tutor answers it as a normal request."""
        try:
            chat = await self.research.reply(text)
        except anthropic.APIError as e:
            self.usage_log.event("claude_error", purpose="experience", session_id=self.id, error=str(e)[:300])
            await self.error("tutor_unavailable", "The tutor is unavailable right now; try again shortly.", request_id)
            self.busy = False
            return
        if chat is None:
            await self._answer(request_id, text, asked=True)  # releases `busy` when done
            return
        try:
            await self._send_plain(request_id, chat, self._evaluate())
        finally:
            self.busy = False
