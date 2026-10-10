"""Task generation: backend → Claude → backend (docs/contract.md §2.2).

Claude proposes a TaskSpec. It can check drafts with the `validate_grid` tool,
and its final answer is structured output. The backend checks the format,
retries once with the errors, and derives the learner's task grid.
"""

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from .jsonfmt import dumps
from .task_spec import TASK_SPEC_SCHEMA, build_level, normalize, validate
from .usage_log import UsageLog

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "data" / "examples"

VALIDATE_TOOL = {
    "name": "validate_grid",
    "description": (
        "Check a draft TaskSpec before answering: grid format, whether the complete board is a "
        "working circuit, and whether removing the listed parts leaves an unsolved task. Returns "
        "ok, a list of errors, and the meter readings of the complete board. Call it with your "
        "full draft; fix every error and call it again until ok is true."
    ),
    "input_schema": TASK_SPEC_SCHEMA,
}

SYSTEM_RULES = """You design one small DC circuit task for a beginner learning electricity.

The learner works on a grid of points. You propose a TaskSpec: the complete,
working circuit, which parts or wires to remove (the learner must put them back),
optional decoy parts, and which meters define the goal. The backend derives the
learner's starting grid and computes all target values itself.

Task rules
- Choose the concept and complexity from the learner context: build on what the
  learner has done, raise difficulty gradually, and never repeat a recent task.
- Follow the context's `variation` hints (layout, source voltage, resistor range) so that tasks differ
  even for identical learners. Never copy the examples' layouts or values; they only
  show the format.
- Keep circuits small: one voltage source, at most 4 resistors, 1-2 meters.
- The complete board must be a working circuit with no problems: a closed loop, no
  short circuit, no floating or bypassed parts, no meter misuse, and no resistor
  dissipating more than 5 W. Every target meter must read a non-zero value.
- The removed parts must matter: without them the task is not solved.
- Never compute or state target values; the backend computes them.
- Resistor values have at most two significant digits (e.g. 20, 60, 120, 4700).
- Write `intro` in plain language for a beginner, without numbers that depend
  on solving the circuit. Fill `rationale` with one sentence on why this task
  fits this learner now.

Grid format
- A point is [col, row], 1-based; row 1 is the top. Stay inside the grid size given.
- Component types and pin names: voltage_source (positive, negative),
  resistor (a, b), voltmeter (positive, negative), ammeter (positive, negative).
  In `pins`, set the type's two pins and set every other pin name to null.
  `value`: volts for voltage_source, ohms for resistor, null for meters.
- A component spans three points in a straight line: first pin, body, second pin.
  `orientation` (N, E, S, W) is the direction the FIRST pin points from the body.
  Example: body [6, 3] with orientation W gives a = [5, 3] and b = [7, 3].
  N means the first pin is one row above the body (smaller row number).
- No two components may share any point (pins or bodies). Components connect only
  through wires.
- A wire piece is {id, segments}. A segment joins two orthogonally adjacent points.
  A piece is a straight (1 segment), a corner (2 perpendicular segments sharing a
  point), a T (3 segments sharing a center) or a + (4 segments sharing a center).
  Long wires are chains of pieces that share end points.
- Wires must not pass through a component body point.
- IDs are unique across components, wires and decoys: V1, R1, VM1, AM1, W1, ...
- Points connect only through wire segments; a pin connects to the wires touching it.

Before answering, call validate_grid with your full draft and fix every error.

Examples of valid TaskSpecs:
"""


def load_examples() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(EXAMPLES_DIR.glob("*.json"))]


def system_prompt(examples: list[dict]) -> str:
    return SYSTEM_RULES + "\n".join(dumps(e) for e in examples)


# Variation hints: identical learner contexts (e.g. every fresh start) still get different tasks.
LAYOUT_HINTS = [
    "put the voltage source on the left edge",
    "put the voltage source on the right edge",
    "put the voltage source along the top",
    "put the voltage source along the bottom",
    "place the circuit in the upper half of the grid",
    "place the circuit in the lower half of the grid",
    "use a tall, narrow loop",
    "use a wide, flat loop",
]
SOURCE_HINTS = ["use a 6 V source", "use a 9 V source", "use a 12 V source", "use a 5 V source"]
RESISTOR_HINTS = [
    "use resistors between 10 and 47 Ω",
    "use resistors between 47 and 220 Ω",
    "use resistors between 220 Ω and 1 kΩ",
    "use resistors of 1 kΩ or more",
]


def variation(rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    return {
        "seed": rng.randrange(10_000),
        "layout": rng.choice(LAYOUT_HINTS),
        "source": rng.choice(SOURCE_HINTS),
        "resistors": rng.choice(RESISTOR_HINTS),
    }


def learner_context(skill_level: int, history: list[dict], grid: dict, recent: int,
                    rng: random.Random | None = None) -> dict:
    recent_tasks, older = history[-recent:], history[:-recent] if len(history) > recent else []
    return {
        "skill_level": skill_level,
        "grid": grid,
        "recent_tasks": recent_tasks,
        "older_tasks": {"count": len(older), "concepts": sorted({t.get("concept", "") for t in older})},
        "variation": variation(rng),
    }


def tool_result(draft: dict, grid_limits: dict, settings: dict, recent_signatures=()) -> str:
    result = validate(normalize(draft), grid_limits, settings, recent_signatures)
    return json.dumps({"ok": not result["errors"], "errors": result["errors"], "readings": result["readings"]})


@dataclass
class GenerationResult:
    spec: dict | None = None
    level: dict | None = None
    attempts: int = 0
    errors: list[str] = field(default_factory=list)


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    fields = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    return {f: getattr(usage, f, 0) or 0 for f in fields}


async def generate_task(
    client,
    config: dict,
    usage_log: UsageLog,
    *,
    skill_level: int,
    history: list[dict],
    session_id: str | None = None,
) -> GenerationResult:
    settings = config["claude"]["task_generation"]
    generation = config.get("task_generation", {})
    limits = config.get("rate_limits", {})
    evaluator = config.get("evaluator", {})
    recent = [t["signature"] for t in history[-generation.get("recent_tasks", 10):] if t.get("signature")]
    system = [{"type": "text", "text": system_prompt(load_examples()), "cache_control": {"type": "ephemeral"}}]
    context = learner_context(skill_level, history, generation.get("grid", {"columns": 12, "rows": 8}),
                              generation.get("recent_tasks", 10))
    prompt = "Learner context:\n" + dumps(context) + "\nPropose the next task."

    result = GenerationResult()
    feedback: list[str] = []
    for attempt in range(1, settings.get("max_attempts", 2) + 1):
        result.attempts = attempt
        content = prompt
        if feedback:
            content += "\n\nYour previous proposal was rejected. Fix these errors:\n- " + "\n- ".join(feedback)
        messages = [{"role": "user", "content": content}]
        spec, failure = await _run_conversation(client, settings, system, messages, (limits, evaluator, recent), usage_log,
                                                session_id, attempt)
        if spec is None:
            feedback = [failure]
            continue
        validation = validate(spec, limits, evaluator, recent)
        errors = validation["errors"]
        if not errors:
            result.spec, result.errors = spec, []
            result.level = build_level(spec, skill_level, validation["board"])
            usage_log.event("task_generated", session_id=session_id, attempts=attempt,
                            concept=spec["concept"], difficulty=spec["difficulty"])
            return result
        feedback = errors
    result.errors = feedback
    usage_log.event("task_generation_failed", session_id=session_id, attempts=result.attempts, errors=feedback[:10])
    return result


async def _run_conversation(client, settings, system, messages, checks, usage_log, session_id, attempt):
    """One generation conversation, with validate_grid tool turns. Returns (spec, failure reason)."""
    max_validate = settings.get("max_validate_calls", 5)
    validate_calls = 0
    for _ in range(max_validate + 2):
        started = time.monotonic()
        try:
            response = await client.with_options(timeout=settings.get("timeout_s", 120)).messages.create(
                model=settings["model"],
                max_tokens=settings.get("max_tokens", 16000),
                system=system,
                tools=[VALIDATE_TOOL],
                output_config={
                    "effort": settings.get("effort", "high"),
                    "format": {"type": "json_schema", "schema": TASK_SPEC_SCHEMA},
                },
                messages=messages,
            )
        except anthropic.APIError as e:
            usage_log.event("claude_error", purpose="task_generation", session_id=session_id, error=str(e)[:300])
            return None, f"Claude API error: {e.__class__.__name__}"
        usage_log.claude_call(
            purpose="task_generation", model=settings["model"], usage=_usage(response), session_id=session_id,
            attempt=attempt, stop_reason=response.stop_reason,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        if response.stop_reason == "refusal":
            return None, "The request was declined; propose a different, simple task."

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if tool_uses:
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in tool_uses:
                validate_calls += 1
                if validate_calls > max_validate:
                    text = json.dumps({"ok": False, "errors": ["Validation limit reached. Give your final answer now."]})
                else:
                    text = tool_result(block.input, *checks)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": text})
            messages.append({"role": "user", "content": results})
            continue

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            return None, f"No final answer (stop reason {response.stop_reason})."
        try:
            return normalize(json.loads(text)), ""
        except (json.JSONDecodeError, AttributeError, TypeError):
            return None, "The final answer was not valid TaskSpec JSON."
    return None, "Too many tool turns without a final answer."
