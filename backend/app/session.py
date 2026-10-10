"""WebSocket learning session (docs/contract.md §1): session.start, board.update, tutor.request."""

import asyncio
import time
import uuid
from collections import deque

import anthropic

from .evaluate import evaluate
from .grid import validate_grid
from .tutor import answer


class Session:
    def __init__(self, send, *, config: dict, claude, usage_log, references: dict):
        self.send = send  # async callable taking a message dict
        self.config = config
        self.claude = claude
        self.usage_log = usage_log
        self.references = references
        self.id = uuid.uuid4().hex[:12]
        self.level: dict | None = None
        self.board: dict | None = None
        self.history: list[dict] = []
        self.busy = False
        self.calls: deque[float] = deque()
        self.tasks: set[asyncio.Task] = set()

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
        self.level = level
        self.history = [t for t in message.get("history", []) if isinstance(t, dict)]
        self.usage_log.event("session_started", session_id=self.id, level_id=level.get("id"))
        await self.send({"type": "evaluation", "seq": 0, "evaluation": self._evaluate()})

    async def update(self, message: dict) -> None:
        if self.level is None:
            await self.error("no_session", "send session.start first")
            return
        if await self._set_board(message.get("board")):
            await self.send({"type": "evaluation", "seq": message.get("seq", 0), "evaluation": self._evaluate()})

    def _over_rate_limit(self) -> bool:
        limit = self.config.get("rate_limits", {}).get("tutor_calls_per_session_per_min", 6)
        now = time.monotonic()
        while self.calls and now - self.calls[0] > 60:
            self.calls.popleft()
        return len(self.calls) >= limit

    async def request(self, message: dict) -> None:
        request_id = message.get("request_id") or uuid.uuid4().hex[:8]
        text = str(message.get("learner_text") or "").strip()
        if self.level is None:
            # The server lost or never had the session (e.g. it restarted); the client resends session.start.
            await self.error("no_session", "send session.start first", request_id)
        elif message.get("action") != "message" or not text:
            await self.error("bad_message", "tutor.request needs action 'message' and learner_text", request_id)
        elif self.claude is None:
            await self.error("tutor_unavailable", "The tutor is not configured.", request_id)
        elif self.busy or self._over_rate_limit():
            await self.error("rate_limited", "The tutor needs a moment; try again shortly.", request_id)
        else:
            self.busy = True
            self.calls.append(time.monotonic())
            await self.send({"type": "tutor.started", "request_id": request_id, "trigger": "request"})
            # Run the Claude call in the background so the session keeps receiving messages.
            task = asyncio.create_task(self._answer(request_id, text))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def _answer(self, request_id: str, text: str) -> None:
        try:
            reference = self.references.get(self.level.get("id"))
            reply, evaluation = await answer(
                self.claude, self.config, self.usage_log, level=self.level, board=self.board,
                reference=reference, history=self.history, learner_text=text, session_id=self.id,
            )
            self.history += [{"role": "learner", "text": text}, {"role": "tutor", "text": reply["chat"]["text"]}]
            await self.send({"type": "tutor.message", "request_id": request_id, "evaluation": evaluation,
                             "message": reply})
        except anthropic.APIError as e:
            self.usage_log.event("claude_error", purpose="tutor_request", session_id=self.id, error=str(e)[:300])
            await self.error("tutor_unavailable", "The tutor is unavailable right now; try again shortly.", request_id)
        finally:
            self.busy = False
