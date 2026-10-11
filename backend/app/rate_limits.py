"""Rate limits and the daily Claude budget (docs/design.md §6), configured in the root ratelimiting.yaml.

They protect the cost of Claude calls and the server. Evaluation never depends on Claude, so
when a Claude limit is hit the grid, readings and status keep working; only the tutor goes quiet
or generation pauses. Counters are in memory, in the single backend process, except the day's
Claude spend, which is kept in a state file so a restart or deploy doesn't reset it.
"""

import json
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from .config import REPO_ROOT


def client_ip(conn) -> str:
    """The learner's IP: Fly's proxy sets Fly-Client-IP; locally, the socket's address."""
    return conn.headers.get("fly-client-ip") or (conn.client.host if conn.client else "unknown")


class SlidingWindow:
    """At most `limit` events per `seconds` for each key. Thread-safe."""

    def __init__(self, limit: int, seconds: float, clock=time.monotonic):
        self.limit = limit
        self.seconds = seconds
        self.clock = clock
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _expire(self, key: str, now: float) -> deque[float]:
        events = self.events[key]
        while events and now - events[0] >= self.seconds:
            events.popleft()
        return events

    def allow(self, key: str) -> bool:
        """Record an event for `key` and return True, or return False when it's over the limit."""
        with self._lock:
            now = self.clock()
            events = self._expire(key, now)
            if len(events) >= self.limit:
                return False
            events.append(now)
            if len(self.events) > 10_000:  # forget idle keys
                for k in [k for k in self.events if not self._expire(k, now)]:
                    del self.events[k]
            return True

    def retry_after(self, key: str) -> float:
        """Seconds until `key` may have another event."""
        with self._lock:
            now = self.clock()
            events = self._expire(key, now)
            return 0.0 if len(events) < self.limit else max(0.0, self.seconds - (now - events[0]))


class DailyBudget:
    """The day's estimated Claude spend in USD against a daily cap; the day resets at 00:00 UTC.
    Background work (pre-generation) stops at `background_share` of the cap, keeping the rest
    for learners who are waiting. Persisted to `state_file` when one is given."""

    def __init__(self, usd_per_day: float, background_share: float = 0.8, state_file: Path | None = None,
                 today=lambda: datetime.now(timezone.utc).date().isoformat()):
        self.usd_per_day = usd_per_day
        self.background_share = background_share
        self.state_file = state_file
        self.today = today
        self.day = today()
        self.usd = 0.0
        self._lock = threading.Lock()
        if state_file and state_file.exists():
            try:
                saved = json.loads(state_file.read_text())
                if saved.get("day") == self.day:
                    self.usd = float(saved.get("usd", 0))
            except (ValueError, OSError):
                pass  # an unreadable file starts the day at zero

    def _roll(self) -> None:
        if (day := self.today()) != self.day:
            self.day, self.usd = day, 0.0

    def spend(self, usd: float | None) -> None:
        if not usd:
            return
        with self._lock:
            self._roll()
            self.usd += usd
            if self.state_file:
                self.state_file.write_text(json.dumps({"day": self.day, "usd": round(self.usd, 6)}))

    def allows(self, background: bool = False) -> bool:
        with self._lock:
            self._roll()
            cap = self.usd_per_day * (self.background_share if background else 1)
            return self.usd < cap


class RateLimiter:
    """Every limit in ratelimiting.yaml. One instance per backend process, shared by all sessions."""

    def __init__(self, settings: dict, state_dir: Path | None = None, clock=time.monotonic):
        def section(name: str) -> dict:
            return settings.get(name) or {}

        budget = section("claude_budget")
        state_file = state_dir / "claude-budget.json" if state_dir else None
        self.budget = DailyBudget(budget.get("usd_per_day", 20), budget.get("background_share", 0.8), state_file)
        self.tutor = SlidingWindow(section("tutor").get("calls_per_session_per_min", 6), 60, clock)
        self.generations = SlidingWindow(section("task_generation").get("per_ip_per_hour", 10), 3600, clock)
        sessions = section("sessions")
        self.sessions = SlidingWindow(sessions.get("per_ip_per_hour", 30), 3600, clock)
        self.open_per_ip = sessions.get("open_per_ip", 3)
        self.open: dict[str, int] = defaultdict(int)
        self.rest = SlidingWindow(section("rest").get("requests_per_ip_per_min", 60), 60, clock)
        self.board_updates = SlidingWindow(section("board_updates").get("per_session_per_sec", 20), 1, clock)
        self.grid = section("grid")
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: dict, root: Path = REPO_ROOT) -> "RateLimiter":
        """With the state dir for the budget: SCHEMATICS_STATE_DIR (the Fly volume), else
        `claude_budget.state_dir` under the repo root."""
        relative = (settings.get("claude_budget") or {}).get("state_dir", "state")
        state_dir = Path(os.environ.get("SCHEMATICS_STATE_DIR") or root / relative)
        state_dir.mkdir(parents=True, exist_ok=True)
        return cls(settings, state_dir)

    def claude_allowed(self, background: bool = False) -> bool:
        return self.budget.allows(background)

    def session_opened(self, ip: str) -> bool:
        """Admit a new WebSocket session from `ip`; call session_closed when it ends."""
        with self._lock:
            if self.open[ip] >= self.open_per_ip or not self.sessions.allow(ip):
                return False
            self.open[ip] += 1
            return True

    def session_closed(self, ip: str) -> None:
        with self._lock:
            self.open[ip] -= 1
            if self.open[ip] <= 0:
                del self.open[ip]

    def grid_errors(self, board: dict) -> list[str]:
        """Size limits for a board: they also bound solver and validation time."""
        errors = []
        size = board.get("grid") or {}
        if (side := self.grid.get("max_points")) and (size.get("columns", 0) > side or size.get("rows", 0) > side):
            errors.append(f"grid larger than {side} x {side}")
        if (n := self.grid.get("max_components")) and len(board.get("components") or []) > n:
            errors.append(f"more than {n} components")
        if (n := self.grid.get("max_wires")) and len(board.get("wires") or []) > n:
            errors.append(f"more than {n} wire pieces")
        return errors
