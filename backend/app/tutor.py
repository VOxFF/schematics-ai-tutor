"""Tutor call: learner message → context → Claude → validated TutorMessage (docs/contract.md §2.1, docs/tutor.md)."""

import json
import re
import time

import anthropic

from .evaluate import evaluate
from .graph import to_graph
from .jsonfmt import dumps

PRINCIPLES = ["closed_loop", "ohms_law", "series_voltage_division", "parallel_branches", "meter_usage", "power_safety"]
MISCONCEPTIONS = [
    "single_wire_enough", "current_used_up", "bigger_r_more_current", "full_voltage_each_resistor",
    "parallel_reduces_current", "meter_in_series_like_wire", "ammeter_across_part", "short_is_harmless",
]
KINDS = ["feedback", "nudge", "hint", "question", "praise"]
STYLES = ["attention", "error", "success"]


def _object(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_POINT = {"type": "array", "items": {"type": "integer"}}
# Field order matters: Claude writes `meta` (including `principle`) before the text.
TUTOR_MESSAGE_SCHEMA = _object({
    "meta": _object({
        "principle": {"type": "string", "enum": PRINCIPLES},
        "highlights": {"type": "array", "items": _object({
            "component": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "wire": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "point": {"anyOf": [_POINT, {"type": "null"}]},
            "style": {"type": "string", "enum": STYLES},
        })},
        "hint_level": {"type": "integer"},
        "misconception": {"anyOf": [{"type": "string", "enum": MISCONCEPTIONS}, {"type": "null"}]},
    }),
    "chat": _object({
        "kind": {"type": "string", "enum": KINDS},
        "text": {"type": "string"},
    }),
})

SYSTEM_PROMPT = f"""You are a patient electronics tutor for complete beginners. The learner builds
DC circuits on a grid. A deterministic evaluator computes every reading and
status; you never compute or invent numbers.

Your job is to help the learner understand WHY a circuit behaves as it does,
using loops, current, voltage and resistance. Highlights show the learner WHERE
to look, so your words never describe locations: no coordinates, no pin names,
no "connect X to Y", no naming the exact part to place, no "row", "column" or
"point".

Ask rather than tell. One question at a time. Plain words; explain any term the
first time. Keep replies short: at most 4 sentences.

Free chat:
- Concept questions ("What is a voltmeter?") get a full, plain explanation;
  explaining concepts does not give the task away.
- "Just tell me the answer" is kindly redirected: offer to think it through together.
- Off-topic questions get a gentle redirect back to circuits.

Input: <level> (concept, targets, intro), <reference> (the solution's parts and
connections; never reveal it), <summary> (one-line description of the learner's
circuit), <snapshot> (the learner's current graph and the evaluator's result;
the grid is for highlight references only, never describe it), <history>
(recent chat), <request> (the learner's message).

Output: choose meta.principle first, then write chat.text explaining that
principle. Use meta.highlights to point at relevant components (by id), wires
(by id) or grid points, with style attention, error or success; leave unused
fields null. Set meta.hint_level to 0. Set meta.misconception only when the
learner's words or circuit show one, using only these labels:
{", ".join(MISCONCEPTIONS)}.

Bad:  "Connect a wire from R1.b to AM1.positive."
Good: "Current needs a complete path back to the source. Follow it from R1.
       Where does it stop?"
"""

# Location talk the learner must never see (docs/tutor.md §6).
_LOCATION = re.compile(
    r"\[\s*\d+\s*,\s*\d+\s*\]|\(\s*\d+\s*,\s*\d+\s*\)"   # [3, 4] or (3,4)
    r"|\b[A-Z]{1,2}\d+\.(?:a|b|positive|negative)\b"       # R1.a, V1.positive
    r"|\b(?:row|column|point)s?\b",
    re.IGNORECASE,
)


def location_talk(text: str) -> list[str]:
    return sorted({m.group(0) for m in _LOCATION.finditer(text)})


def fallback_message(status: str) -> dict:
    """A safe, generic reply when Claude's text keeps describing locations."""
    text = {
        "short_circuit": "Careful: current has a path with nothing to slow it down. What could limit it?",
        "open_circuit": "Follow the path the current would take from the source. Does it make it all the way back?",
        "solved": "Nice work! What do you think made this circuit work?",
    }.get(status, "Let's think about the path the current takes. What do you notice?")
    return {"meta": {"principle": "closed_loop", "highlights": [], "hint_level": 0, "misconception": None},
            "chat": {"kind": "question", "text": text}}


def circuit_summary(graph: dict, evaluation: dict) -> str:
    parts = []
    for c in graph["components"]:
        unit = {"voltage_source": " V", "resistor": " Ω"}.get(c["type"], "")
        parts.append(f"{c['id']}{' ' + str(c['value']) + unit if 'value' in c else ''}")
    readings = ", ".join(f"{m}={v if v is not None else '--'}" for m, v in evaluation["readings"].items())
    return f"parts: {', '.join(parts) or 'none'}; status: {evaluation['status']}; readings: {readings or 'none'}"


def build_context(level: dict, board: dict, reference: dict | None, history: list[dict], learner_text: str,
                  history_turns: int, evaluator_settings: dict | None = None) -> tuple[str, dict]:
    """The user turn for a tutor call, and the evaluation it is based on."""
    evaluation = evaluate(board, evaluator_settings)
    graph, _ = to_graph(board)
    level_info = {k: level.get(k) for k in ("title", "concept", "intro")} | {"targets": board.get("targets", {})}
    sections = [
        ("level", dumps(level_info)),
        ("reference", dumps(to_graph({**reference, "inventory": [], "targets": {}})[0]) if reference else "none"),
        ("summary", circuit_summary(graph, evaluation)),
        ("snapshot", dumps({"graph": graph, "evaluation": evaluation, "grid": board})),
        ("history", dumps(history[-history_turns:])),
        ("request", dumps({"action": "message", "learner_text": learner_text})),
    ]
    return "\n\n".join(f"<{name}>\n{body.strip()}\n</{name}>" for name, body in sections), evaluation


def clean_highlights(highlights: list[dict], board: dict) -> list[dict]:
    """Keep only highlights that point at something on the board (docs/contract.md, response handling)."""
    components = {c["id"] for c in board.get("components", [])}
    wires = {w["id"] for w in board.get("wires", [])}
    columns, rows = board["grid"]["columns"], board["grid"]["rows"]
    kept = []
    for h in highlights:
        style = h.get("style")
        if h.get("component") in components:
            kept.append({"target": {"component": h["component"]}, "style": style})
        elif h.get("wire") in wires:
            kept.append({"target": {"wire": h["wire"]}, "style": style})
        elif (p := h.get("point")) and len(p) == 2 and 1 <= p[0] <= columns and 1 <= p[1] <= rows:
            kept.append({"target": {"point": p}, "style": style})
    return kept


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    fields = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    return {f: getattr(usage, f, 0) or 0 for f in fields}


async def answer(client, config: dict, usage_log, *, level: dict, board: dict, reference: dict | None,
                 history: list[dict], learner_text: str, session_id: str | None = None) -> tuple[dict, dict]:
    """Return (TutorMessage, evaluation) for a learner message. Raises anthropic.APIError on API failure."""
    settings = config["claude"]["tutor_request"]
    user_turn, evaluation = build_context(
        level, board, reference, history, learner_text,
        config.get("tutor", {}).get("history_turns", 6), config.get("evaluator"),
    )
    content = user_turn
    for attempt in (1, 2):
        started = time.monotonic()
        response = await client.with_options(timeout=settings.get("timeout_s", 30)).messages.create(
            model=settings["model"],
            max_tokens=settings.get("max_tokens", 16000),
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            output_config={
                "effort": settings.get("effort", "medium"),
                "format": {"type": "json_schema", "schema": TUTOR_MESSAGE_SCHEMA},
            },
            messages=[{"role": "user", "content": content}],
        )
        usage_log.claude_call(purpose="tutor_request", model=settings["model"], usage=_usage(response),
                              session_id=session_id, attempt=attempt, stop_reason=response.stop_reason,
                              duration_ms=int((time.monotonic() - started) * 1000))
        text = next((b.text for b in response.content if b.type == "text"), None)
        if response.stop_reason == "refusal" or text is None:
            break
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            break
        found = location_talk(message["chat"]["text"])
        if not found:
            message["meta"]["hint_level"] = 0  # no hint ladder yet
            message["meta"]["highlights"] = clean_highlights(message["meta"].get("highlights", []), board)
            return message, evaluation
        usage_log.event("tutor_backstop", session_id=session_id, attempt=attempt, matches=found)
        content = (user_turn + "\n\nYour previous reply described locations (" + ", ".join(found)
                   + "). Explain the physics instead and point with highlights.")
    return fallback_message(evaluation["status"]), evaluation
