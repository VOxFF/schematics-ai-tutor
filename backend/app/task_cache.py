"""Pre-generated tasks, cached by the learner's progress (docs/design.md §3).

A generated task takes 20-30 s, too long to wait at Start or Next. After serving a task, the
cache generates the next one in the background, for the progress as if the served task is
solved, and it keeps a small pool of first tasks for new learners.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable

FIRST_PROGRESS = {"skill_level": 1, "history": []}


def progress_key(progress: dict) -> tuple:
    """Which tasks a progress asks for: the skill level and the tasks done, by title and signature.
    Hint and misconception fields are left out, so the progress the cache assumes for a solved
    task matches the one the browser sends."""
    done = tuple((t.get("title", ""), t.get("signature", "")) for t in progress.get("history", []))
    return progress.get("skill_level", 1), done


def solved(progress: dict, level: dict) -> dict:
    """The progress after `level` is solved: what the browser sends at Next (App.jsx, advance)."""
    summary = {
        "title": level["title"],
        "concept": level["concept"],
        "shape": level.get("shape") or "",
        "difficulty": level.get("difficulty") or progress["skill_level"],
        "hints_used": 0,
        "misconceptions": [],
        "signature": level.get("signature") or "",
    }
    return {"skill_level": progress["skill_level"] + 1, "history": [*progress["history"], summary]}


class TaskCache:
    """Generations by progress key, each an asyncio.Task that returns a GenerationResult.

    `produce(progress)` runs one generation. A served task leaves the cache.
    """

    def __init__(self, produce: Callable[[dict], Awaitable], *, first_task_pool: int = 2,
                 max_entries: int = 50, ttl_s: float = 3600, usage_log=None, clock=time.monotonic,
                 allow_background: Callable[[], bool] = lambda: True):
        self.produce = produce
        self.allow_background = allow_background  # False stops pre-generation, e.g. near the Claude budget
        self.first_task_pool = first_task_pool
        self.max_entries = max_entries
        self.ttl_s = ttl_s
        self.usage_log = usage_log
        self.clock = clock
        self.entries: dict[tuple, list[tuple[float, asyncio.Task]]] = {}  # oldest first per key

    def _event(self, kind: str, **fields) -> None:
        if self.usage_log is not None:
            self.usage_log.event(kind, **fields)

    def _start(self, progress: dict) -> asyncio.Task:
        task = asyncio.create_task(self.produce(progress))
        # A background generation nobody waits for must not log "exception never retrieved".
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        return task

    def _prune(self) -> None:
        """Drop expired entries, then the oldest ones beyond the size cap."""
        now = self.clock()
        for key in list(self.entries):
            kept = []
            for created, task in self.entries[key]:
                if now - created > self.ttl_s:
                    task.cancel()
                else:
                    kept.append((created, task))
            self.entries[key] = kept
        everything = sorted(((created, key, task) for key, queue in self.entries.items() for created, task in queue),
                            key=lambda entry: entry[0])
        for _, key, task in everything[:max(0, len(everything) - self.max_entries)]:
            task.cancel()
            self.entries[key] = [(c, t) for c, t in self.entries[key] if t is not task]
        self.entries = {k: q for k, q in self.entries.items() if q}

    def pregenerate(self, progress: dict, count: int = 1) -> None:
        """Start background generations until `count` are cached or running for this progress."""
        queue = self.entries.setdefault(progress_key(progress), [])
        if len(queue) < count and not self.allow_background():
            self._event("task_pregeneration_skipped", skill_level=progress["skill_level"], reason="claude_budget")
            return
        while len(queue) < count:
            queue.append((self.clock(), self._start(progress)))
            self._event("task_pregeneration_started", skill_level=progress["skill_level"])
        self._prune()

    def fill_first_task_pool(self) -> None:
        self.pregenerate(FIRST_PROGRESS, self.first_task_pool)

    async def get(self, progress: dict, produce: bool = True):
        """A task for `progress`: cached if one is ready or under way, else generated now (with
        `produce`; else None). Then the task after it is generated in the background."""
        self._prune()
        queue = self.entries.get(progress_key(progress), [])
        # Prefer a finished generation, then the oldest one still running.
        queue.sort(key=lambda entry: not entry[1].done())
        result = None
        if queue:
            _, task = queue.pop(0)
            self._event("task_cache_hit", skill_level=progress["skill_level"], ready=task.done())
            try:
                result = await task
            except asyncio.CancelledError:
                raise
            except Exception:  # e.g. an API error in the background
                result = None
            if result is not None and result.level is None:
                result = None
            # A failed background generation is retried once now, below.
        if result is None:
            self._event("task_cache_miss", skill_level=progress["skill_level"])
            if not produce:
                return None
            result = await self.produce(progress)
        if result.level is not None:
            self.pregenerate(solved(progress, result.level))
            if progress_key(progress) == progress_key(FIRST_PROGRESS):
                self.fill_first_task_pool()
        return result

    def close(self) -> None:
        for queue in self.entries.values():
            for _, task in queue:
                task.cancel()
        self.entries = {}
