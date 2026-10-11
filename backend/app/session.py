"""WebSocket learning session (docs/contract.md §1): session.start, board.update, tutor.request.

Every board.update records a snapshot; when editing pauses for `tutor.idle_threshold_ms`, the
tutor reacts to the snapshots since its last call. A learner message or hint request cancels a
pending reaction. The session runs the task's hint ladder (docs/tutor.md §3).
"""

import asyncio
import time
import uuid
from collections import deque

import anthropic

from .evaluate import STATUS_RANK, evaluate
from .graph import to_graph
from .grid import validate_grid
from .task_cache import solved
from .tutor import answer


class Session:
    def __init__(self, send, *, config: dict, claude, usage_log, references: dict, task_cache=None):
        self.send = send  # async callable taking a message dict
        self.config = config
        self.claude = claude
        self.usage_log = usage_log
        self.references = references
        self.task_cache = task_cache  # pre-generation (docs/design.md §3), or None
        self.id = uuid.uuid4().hex[:12]
        self.level: dict | None = None
        self.board: dict | None = None
        self.seq = 0  # seq of the board in `self.board` (0: the board from session.start)
        self.history: list[dict] = []
        self.busy = False
        self.calls: deque[float] = deque()
        self.tasks: set[asyncio.Task] = set()
        self.snapshots: list[dict] = []  # boards since the tutor's last call, oldest first
        self.started_at = time.monotonic()
        self.idle: asyncio.Task | None = None  # pending reaction timer
        self.hint_level = 0  # highest hint given in this task (0-3)
        self.best_rank = -1  # best status reached in this task, by STATUS_RANK
        self.stalled = 0  # reactions in a row without beating best_rank

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
        self.hint_level = min(max(hint_level, 0), 3) if isinstance(hint_level, int) else 0
        self.usage_log.event("session_started", session_id=self.id, level_id=level.get("id"))
        await self.send({"type": "evaluation", "seq": 0, "evaluation": self._evaluate()})
        # A resumed task (e.g. after a server restart, which empties the cache) gets its next
        # task generated in the background too, so Next doesn't wait.
        progress = message.get("progress")
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
        if await self._set_board(message.get("board")):
            self.seq = message.get("seq", 0)
            evaluation = self._evaluate()
            await self.send({"type": "evaluation", "seq": message.get("seq", 0), "evaluation": evaluation})
            self._record(message.get("seq", 0), evaluation)
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
        """A burst of quick edits gives one reaction: each edit restarts the timer."""
        self._cancel_idle_timer()
        if self.claude is not None:
            self.idle = self._start_task(self._react_after_pause())

    async def _react_after_pause(self) -> None:
        await asyncio.sleep(self.config.get("tutor", {}).get("idle_threshold_ms", 1500) / 1000)
        self.idle = None
        if self.busy:
            return  # a call is running; the next pause reacts to these snapshots too
        if self._over_rate_limit():
            self.usage_log.event("reaction_skipped", session_id=self.id, reason="rate_limited")
            return
        self.busy = True
        self.calls.append(time.monotonic())
        request_id = f"react-{uuid.uuid4().hex[:8]}"
        await self.send({"type": "tutor.started", "request_id": request_id, "trigger": "reaction"})
        await self._answer(request_id, None, offer_hint=self._offer_hint())

    def _offer_hint(self) -> bool:
        """Whether this reaction offers a hint: after `tutor.offer_hint_after_reactions` reactions in
        a row without the status beating the best one in this task (docs/tutor.md §3)."""
        status = self._evaluate()["status"]
        rank = STATUS_RANK.index(status) if status in STATUS_RANK else -1
        if rank > self.best_rank:
            self.best_rank, self.stalled = rank, 0
            return False
        self.stalled += 1
        if status == "solved" or self.hint_level >= 3:
            return False
        if self.stalled >= self.config.get("tutor", {}).get("offer_hint_after_reactions", 3):
            self.stalled = 0
            return True
        return False

    def _over_rate_limit(self) -> bool:
        limit = self.config.get("rate_limits", {}).get("tutor_calls_per_session_per_min", 6)
        now = time.monotonic()
        while self.calls and now - self.calls[0] > 60:
            self.calls.popleft()
        return len(self.calls) >= limit

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
        elif self.claude is None:
            await self.error("tutor_unavailable", "The tutor is not configured.", request_id)
        elif self.busy or self._over_rate_limit():
            await self.error("rate_limited", "The tutor needs a moment; try again shortly.", request_id)
        else:
            self._cancel_idle_timer()  # the learner's message takes priority over a pending reaction
            self.busy = True
            self.calls.append(time.monotonic())
            await self.send({"type": "tutor.started", "request_id": request_id, "trigger": "request"})
            # The server decides a hint's level: one above the highest given, at most 3.
            hint = min(self.hint_level + 1, 3) if action == "hint" else 0
            # Run the Claude call in the background so the session keeps receiving messages.
            self._start_task(self._answer(request_id, text or None, hint=hint, asked=True))

    async def _answer(self, request_id: str, text: str | None, *, hint: int = 0, asked: bool = False,
                      offer_hint: bool = False) -> None:
        """A tutor call for a learner request (`asked`: a message, or a hint of level `hint`) or
        a reaction, which may end by offering a hint."""
        # Earlier boards since the last call; the current board is added by the tutor context.
        snapshots, self.snapshots = self.snapshots[:-1], []
        board, seq = self.board, self.seq  # edits may arrive during the call; the reply is about this board
        try:
            reference = self.references.get(self.level.get("id"))
            reply, evaluation = await answer(
                self.claude, self.config, self.usage_log, level=self.level, board=board,
                reference=reference, history=self.history, learner_text=text, snapshots=snapshots,
                session_id=self.id, hint_level=hint, offer_hint=offer_hint,
            )
            if hint:
                self.hint_level = max(self.hint_level, hint)
                self.stalled = 0
                self.history.append({"role": "learner", "text": f"(asked for hint {hint}/3) {text or ''}".strip()})
            elif text is not None:
                self.history.append({"role": "learner", "text": text})
            self.history.append({"role": "tutor", "text": reply["chat"]["text"]})
            # `seq` names the board the reply is about: the client drops its highlights and
            # evaluation when the learner has edited since.
            await self.send({"type": "tutor.message", "request_id": request_id, "seq": seq,
                             "evaluation": evaluation, "message": reply, "hint_offered": offer_hint})
        except anthropic.APIError as e:
            purpose = "tutor_request" if asked else "tutor_reaction"
            self.usage_log.event("claude_error", purpose=purpose, session_id=self.id, error=str(e)[:300])
            # A failed reaction carries no request_id: the client stops "thinking" without a chat error.
            await self.error("tutor_unavailable", "The tutor is unavailable right now; try again shortly.",
                             request_id if asked else None)
        finally:
            self.busy = False
        if self.snapshots and self.idle is None:
            self._restart_idle_timer()  # edits arrived during the call: react to them after a pause
