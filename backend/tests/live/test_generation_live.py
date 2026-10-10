"""Live task generation against the real Claude API. Costs money; run with ./test.sh live.

LIVE_TASKS sets how many tasks to generate (default 1); the test reports the pass rate.
"""

import asyncio
import json
import os

import anthropic
import pytest

from app.config import REPO_ROOT
from app.task_generation import generate_task
from app.usage_log import UsageLog

pytestmark = pytest.mark.live


def test_generate_tasks(config, tmp_path):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set (./test.sh live loads backend/keys/apikey.txt)")
    count = int(os.environ.get("LIVE_TASKS", "1"))
    # Live runs are logged to the real logs/ directory, so their cost shows up there.
    usage_log = UsageLog.from_config(config, REPO_ROOT, "live-test")

    async def run_all():
        client = anthropic.AsyncAnthropic()
        return [await generate_task(client, config, usage_log, skill_level=2, history=[]) for _ in range(count)]

    results = asyncio.run(run_all())
    passed = [r for r in results if r.level is not None]
    for r in results:
        summary = {"ok": r.level is not None, "attempts": r.attempts, "errors": r.errors[:3]}
        if r.spec:
            summary.update(title=r.spec["title"], concept=r.spec["concept"], difficulty=r.spec["difficulty"])
        print(json.dumps(summary))
    print(f"pass rate: {len(passed)}/{count}; cost so far: ${usage_log.totals['cost_usd']:.4f}")
    assert passed, "no generated task passed the format checks"
