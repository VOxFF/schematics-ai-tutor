"""Generate the fallback pack: tasks for every skill level of the learning path, served when a
generated task isn't available (docs/design.md §6, Fallback when Claude is unavailable).

For each skill level, `task_generation.fallback_variants` tasks from the real generator, with a
plausible history (the earlier skill levels' concepts, no hints, no misconceptions), each with a
circuit of its own. Writes backend/data/fallback/skill-<n>.json; a skill level whose tasks don't
all succeed keeps its old file. The sizes come from curriculum.yaml. Costs Claude calls: about one
generation per task.

Usage: python3 scripts/generate_fallback.py [--skill N ...] [--jobs 4]
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import anthropic  # noqa: E402

from app import fallback  # noqa: E402
from app.config import load_config  # noqa: E402
from app.curriculum import position  # noqa: E402
from app.jsonfmt import dumps  # noqa: E402
from app.task_generation import generate_task  # noqa: E402
from app.task_spec import signature  # noqa: E402
from app.usage_log import UsageLog  # noqa: E402

TRIES = 3  # generations per task before the skill level is given up


def history(skill: int) -> list[dict]:
    """A learner who solved the skill levels before this one, without hints or misconceptions."""
    out = []
    for k in range(1, skill):
        rules, task = position(k)
        out.append({"title": f"{rules['concept']} ({task} of {rules['tasks']})", "concept": rules["concept"],
                    "shape": "", "difficulty": min(5, 1 + (rules["level"] - 1) // 2), "hints_used": 0,
                    "misconceptions": [], "signature": ""})
    return out


async def generate_skill(claude, config: dict, usage_log: UsageLog, skill: int, variants: int,
                         jobs: asyncio.Semaphore) -> bool:
    specs, past = [], history(skill)
    async with jobs:
        for tries in range(variants * TRIES):
            if len(specs) == variants:
                break
            # The repeat check gives each variant its own circuit; the learner's history doesn't
            # include them: a learner meets one of them, not all.
            try:
                result = await generate_task(claude, config, usage_log, skill_level=skill, history=past,
                                             avoid_signatures=tuple(signature(s) for s in specs))
            except Exception as e:  # one bad generation doesn't stop the other skill levels
                print(f"skill {skill}: a generation crashed ({e.__class__.__name__}: {e})", flush=True)
                continue
            if result.spec is None:
                print(f"skill {skill}: a generation failed ({'; '.join(result.errors[:2])})", flush=True)
                continue
            errors = fallback.check(result.spec, skill, config)["errors"]
            if errors or signature(result.spec) in {signature(s) for s in specs}:
                print(f"skill {skill}: rejected ({'; '.join(errors[:2]) or 'a repeated circuit'})", flush=True)
                continue
            specs.append(result.spec)
            print(f"skill {skill}: {len(specs)}/{variants} {result.spec['title']!r}", flush=True)
    if len(specs) < variants:
        print(f"skill {skill}: FAILED, {len(specs)}/{variants}; the old file is kept", flush=True)
        return False
    fallback.path(skill).write_text(dumps(specs))
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--skill", type=int, action="append", help="only this skill level (repeatable)")
    parser.add_argument("--jobs", type=int, default=4, help="skill levels generated at once")
    args = parser.parse_args()

    key_file = ROOT / "backend" / "keys" / "apikey.txt"
    if not os.environ.get("ANTHROPIC_API_KEY") and key_file.exists():
        os.environ["ANTHROPIC_API_KEY"] = key_file.read_text().strip()
    config = load_config()
    count = fallback.skill_levels()
    skills = args.skill or list(range(1, count + 1))
    if any(not 1 <= s <= count for s in skills):
        parser.error(f"skill levels run from 1 to {count} (curriculum.yaml)")
    variants = config["task_generation"].get("fallback_variants", 3)
    usage_log = UsageLog(None, config.get("pricing"))
    fallback.FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
    if not args.skill:  # a full run: files left over from a longer curriculum go
        for file in fallback.FALLBACK_DIR.glob("skill-*.json"):
            if file.name not in {fallback.path(n).name for n in range(1, count + 1)}:
                file.unlink()
                print(f"removed {file.name}")

    started = time.monotonic()
    jobs = asyncio.Semaphore(args.jobs)
    claude = anthropic.AsyncAnthropic()
    done = await asyncio.gather(*(generate_skill(claude, config, usage_log, s, variants, jobs) for s in skills))
    totals = usage_log.totals
    print(f"\n{sum(done)}/{len(skills)} skill levels written, {totals['claude_calls']} Claude calls, "
          f"${totals['cost_usd']:.2f}, {time.monotonic() - started:.0f} s")
    return 0 if all(done) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
