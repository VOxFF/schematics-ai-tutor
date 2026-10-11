"""Pre-generated tasks cached by progress (docs/design.md §3)."""

import asyncio

from app.task_cache import FIRST_PROGRESS, TaskCache, progress_key, solved
from app.task_generation import GenerationResult


class Generator:
    """A fake generation: each call returns a new level; `fail` makes the next ones fail."""

    def __init__(self, delay=0.0):
        self.calls: list[dict] = []
        self.delay = delay
        self.fail = 0

    async def __call__(self, progress):
        self.calls.append(progress)
        await asyncio.sleep(self.delay)
        if self.fail:
            self.fail -= 1
            return GenerationResult(attempts=2, errors=["invalid"])
        n = len(self.calls)
        level = {"id": f"gen-{n}", "title": f"Task {n}", "concept": "c", "difficulty": 2,
                 "shape": "V + R", "signature": f"sig-{n}"}
        return GenerationResult(spec={"complete_board": {}}, level=level, attempts=1)


def run(coroutine):
    return asyncio.run(coroutine)


def test_the_browsers_next_progress_matches_the_one_the_cache_assumes():
    level = {"title": "Split", "concept": "divider", "difficulty": 3, "shape": "V + 2R", "signature": "s"}
    browser = {"skill_level": 2, "history": [{"title": "Split", "concept": "divider", "shape": "V + 2R",
                                              "difficulty": 3, "hints_used": 1, "misconceptions": ["x"],
                                              "signature": "s"}]}
    assert progress_key(solved({"skill_level": 1, "history": []}, level)) == progress_key(browser)


def test_first_tasks_come_from_the_pool_and_the_next_task_is_generated_in_the_background():
    async def scenario():
        produce = Generator()
        cache = TaskCache(produce, first_task_pool=2)
        cache.fill_first_task_pool()
        await asyncio.sleep(0)  # the pool generates
        assert produce.calls == [FIRST_PROGRESS, FIRST_PROGRESS]
        first = await cache.get(FIRST_PROGRESS)  # from the pool: no new generation for it
        await asyncio.sleep(0)
        after = solved(FIRST_PROGRESS, first.level)
        # Then: the pool is topped up and the task after the served one is generated.
        assert produce.calls[2:] == [after, FIRST_PROGRESS]
        second = await cache.get(after)  # Next: already generated
        assert second.level is not None and produce.calls.count(after) == 1
        cache.close()
    run(scenario())


def test_a_request_waits_for_the_generation_already_under_way():
    async def scenario():
        produce = Generator(delay=0.01)
        cache = TaskCache(produce, first_task_pool=0)
        cache.pregenerate(FIRST_PROGRESS)
        result = await cache.get(FIRST_PROGRESS)  # still running: awaited, not started again
        await asyncio.sleep(0)
        assert produce.calls == [FIRST_PROGRESS, solved(FIRST_PROGRESS, result.level)]
        cache.close()
    run(scenario())


def test_a_failed_background_generation_is_retried_on_request():
    async def scenario():
        produce = Generator()
        produce.fail = 1
        cache = TaskCache(produce, first_task_pool=0)
        cache.pregenerate(FIRST_PROGRESS)
        await asyncio.sleep(0)
        result = await cache.get(FIRST_PROGRESS)
        assert result.level is not None and produce.calls[:2] == [FIRST_PROGRESS, FIRST_PROGRESS]
        cache.close()
    run(scenario())


def test_a_served_task_leaves_the_cache():
    async def scenario():
        produce = Generator()
        cache = TaskCache(produce, first_task_pool=0)
        one = await cache.get(FIRST_PROGRESS)
        two = await cache.get(FIRST_PROGRESS)  # e.g. after Restart Learning: a fresh task
        assert one.level["id"] != two.level["id"]
        cache.close()
    run(scenario())


def test_expired_and_excess_entries_are_dropped():
    async def scenario():
        now = [0.0]
        cache = TaskCache(Generator(delay=1), first_task_pool=0, max_entries=2, ttl_s=10, clock=lambda: now[0])
        for level in (1, 2, 3):
            cache.pregenerate({"skill_level": level, "history": []})
        assert sum(len(q) for q in cache.entries.values()) == 2  # the oldest went
        now[0] = 11
        cache.pregenerate({"skill_level": 9, "history": []})
        assert list(cache.entries) == [progress_key({"skill_level": 9, "history": []})]  # the rest expired
        cache.close()
    run(scenario())
