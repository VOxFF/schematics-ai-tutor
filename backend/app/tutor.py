"""Tutor call: context → Claude → validated TutorMessage (docs/contract.md §2.1, docs/tutor.md).

Two triggers: a learner message (`tutor.request`), and a reaction when the learner pauses
after editing the board.
"""

import json
import re
import time

import anthropic

from .evaluate import evaluate
from .formula import answer_in_text, answer_values, board_quantities, check
from .graph import to_graph
from .jsonfmt import dumps

PRINCIPLES = ["closed_loop", "ohms_law", "series_voltage_division", "parallel_branches", "meter_usage", "power_safety"]
MISCONCEPTIONS = [
    "single_wire_enough", "current_used_up", "bigger_r_more_current", "full_voltage_each_resistor",
    "parallel_reduces_current", "meter_in_series_like_wire", "ammeter_across_part", "short_is_harmless",
]
KINDS = ["feedback", "nudge", "hint", "question", "praise", "knowledge"]
STYLES = ["attention", "error", "success"]
MAX_HINT = 4  # the hint ladder's top rung (docs/tutor.md §3)


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
        # The learner profile (docs/design.md §4): bounded by the reply composer.
        "topic_updates": {"type": "array", "items": _object({
            "topic": {"type": "string"},
            "understanding": {"type": "integer"},
            "explained": {"type": "integer"},
        })},
        "new_topic": {"anyOf": [_object({
            "id": {"type": "string"},
            "name": {"type": "string"},
            "type": {"type": "string", "enum": ["principle", "term"]},
            "definition": {"type": "string"},
        }), {"type": "null"}]},
    }),
    "chat": _object({
        "kind": {"type": "string", "enum": KINDS},
        "text": {"type": "string"},
        # Lines of LaTeX shown under the text; checked by formula.py (docs/design.md §4).
        "formula": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]},
    }),
})

SYSTEM_PROMPT = f"""You are a patient electronics tutor for complete beginners. The learner builds
DC circuits on a grid. A deterministic evaluator computes every reading and
status; you never invent numbers. Math goes in chat.formula, which the backend
recomputes.

Your job is to help the learner understand WHY a circuit behaves as it does,
using loops, current, voltage and resistance. Highlights show the learner WHERE
to look, so your words never describe locations: no coordinates, no pin names,
no "connect X to Y", no naming the exact part to place, no "row", "column" or
"point".

Ask rather than tell, except when teaching a topic that is new to the learner
(see Learner profile). One question at a time. Plain words; explain any term the
first time. Keep replies short: at most 4 sentences. Separate ideas with a blank
line: a hint, a chat answer or a knowledge message of more than 2 sentences gets
paragraphs; a reaction stays one paragraph.

Formulas: only when the request has "formulas": true; else chat.formula is null.
chat.formula is a list of lines of LaTeX, shown under the text, at most 8 lines,
one step per line. Use it when the math helps; most reactions need none. Use only:
symbols with subscripts (R_1, V_{{R2}}, R_{{\\text{{total}}}}), numbers with units
(40\\,\\Omega, 2\\,\\mathrm{{k\\Omega}}, 12\\,\\mathrm{{V}}, 300\\,\\mathrm{{mA}}, 0.3\\,\\mathrm{{A}},
2\\,\\mathrm{{W}}), + - \\cdot \\frac{{}}{{}}, parentheses, ^2, = and \\approx. No \\sqrt, no
words, no \\Rightarrow. Numbers only from the board: part values (placed or in the
inventory), readings, targets, and results of earlier lines; small whole numbers
for algebra (2 R_2). The backend recomputes every = and drops a wrong formula.
Never give the answer, the value of a part the learner still has to place, in the
formula or the text, except on hint rung 4. A knowledge message about a topic
with a formula in <profile> shows that formula, symbolic.

Reactions (request trigger "reaction"): the learner just edited the board and paused. The
<snapshots> show what changed, oldest first, with the evaluator's result for each. Respond
to the latest status, in at most 2 sentences:
- short_circuit, overcurrent: safety first, ask what would limit the current.
- meter_misuse: question the belief behind it (e.g. what a meter needs around it).
- open_circuit, floating_part, bypassed: ask about the path the current takes.
- misplaced: ask which way to adjust (bigger or smaller).
- near_target: encourage, then ask what sets the last bit.
- solved: praise the strategy and ask one short reflection question. If the evaluation
  also lists unused_wire issues (leftover wire pieces that connect nothing), suggest
  tidying them up and highlight each one by wire id with style attention.
If nothing meaningful changed, keep it to one short line. Never give the solution.
If the request has "unchanged_moves": N, the learner has made N moves in a row that
didn't change the circuit: they are trying things without progress. Guide more
directly: highlight exactly what has to change and ask about that one spot. Look at
the <snapshots> to see what they tried.
If the request has "offer_hint": true, end the reaction by briefly offering a hint
(e.g. "Want a hint?"), without giving it.

Hints (request action "hint"): give exactly the rung in request.hint_level, in at
most 4 sentences, with highlights (attention) on the parts that matter:
1 text: the concept that matters and where to look. No formula.
2 formula: the symbolic formula and what each symbol is on this board. No
  numbers in it.
3 partial numbers: the formula with the known values from the board put in, the
  unknown left as a symbol for the learner to work out. No answer.
4 full computation: rearrange, substitute and compute, one step per line, up to
  8 lines; the value the learner needs may be given. Never the placement. A
  repeated rung-4 hint says it differently.
Without "formulas": true (curriculum level 1) all rungs are text: 1 the concept and
where to look, 2 the principle with the parts involved, 3 walk the path with the
learner, 4 the full explanation of what is wrong and why.

Free chat (request action "message"):
- Concept questions ("What is a voltmeter?") get a full, plain explanation;
  explaining concepts does not give the task away.
- "Just tell me the answer" is kindly redirected: offer to think it through together.
- Off-topic questions get a gentle redirect back to circuits.

Learner profile: <profile> lists the learner's focus topics, the principles and terms
they met most recently plus older ones they are weak on, each with two scores from 0
to 3 and tasks_ago (0: met in this task):
- understanding: what the learner has SHOWN (0 not yet, 1 shaky, 2 mostly, 3 solid).
- explained: how much you have explained it (0 never, 1 mentioned, 2 explained,
  3 more than once).
Choose the reply by the topic the moment touches:
- explained 0: teach it. chat.kind "knowledge": two sentences on the idea, tied to
  what is on the grid (e.g. "An ammeter has almost no resistance, so current flows
  through it. That's why it goes in the loop."). You may end with a short question;
  a knowledge reaction may take 3 sentences.
- explained 1 or more, understanding 0-1: don't re-explain; ask one question that
  tests it (e.g. "Do you need a larger or a smaller resistance?").
- understanding 2 or more: keep it short; confirm or praise the strategy. For a problem
  the learner has fixed before, one short line is enough ("Still a gap; follow the
  path."): don't explain the cause again.
Never open a reply with the same words as your previous message in <history>.
Safety first: for short_circuit and overcurrent talk about safety; teaching waits.
Teach at most one topic per reply, and prefer recent topics (small tasks_ago).
Report score changes in meta.topic_updates, one entry per topic, by id:
- understanding +1 only on evidence: the learner fixed a problem without a hint,
  answered a question correctly, or explained the idea in their own words. Evidence
  counts for every topic it shows, terms as well as principles: closing an open loop
  without a hint shows open_circuit and current, not only closed_loop.
  understanding -1 when a mistake or misconception shows a gap in that topic.
- explained +1 when this reply explains the topic; else 0.
Leave meta.topic_updates empty when nothing shows. You may name any topic in
<profile>, or a known topic id not listed there (it joins the profile). If you
teach an idea that no topic covers, add it as meta.new_topic (id in snake_case,
a short name, type principle or term, a one-line definition) and report its
explained +1; else leave new_topic null. At most one new topic per reply.

Input: <level> (concept, targets, intro), <reference> (the solution's parts and
connections; never reveal it), <summary> (one-line description of the learner's
circuit), <snapshots> (the learner's board after each recent edit, oldest first:
graph and evaluation; the last one also has the grid, for highlight references
only, never describe it), <profile> (focus topics), <history> (recent chat), <request> (a reaction, or the
learner's message).

chat.kind says what the message does; the chat shows each kind differently:
- praise: what went right, naming the strategy.
- nudge: points at a misstep, gently.
- feedback: says what the circuit does now (e.g. what changed after an edit).
- question: asks the learner to reason about one thing.
- knowledge: teaches a principle or a term (see Learner profile).
- hint: set for hint requests; don't choose it otherwise.
Pick the kind that fits the moment, and vary: not every reply has to be a question.

Output: choose meta.principle first, then write chat.text explaining that
principle. meta.highlights point at components (by id), wires (by id) or grid
points ([column, row], as in the grid), with style attention, error or success;
leave unused fields null. They show the learner WHERE, so your words don't have to.
When the status shows a problem, always highlight it:
- the parts and wires that cause it, by id: a misplaced wire or part, the parts
  on a short path, the misused meter. Style error for short_circuit, overcurrent
  and meter_misuse; attention otherwise.
- short_circuit: highlight EVERY element of the shorted loop with style error:
  the source, every wire piece and every part (e.g. an ammeter) on the path that
  takes the current from its + side back to its - side without passing through
  a resistor. Trace that path in the graph; the learner must see the whole loop.
- open_circuit: the issue's open_ends are the points where the loop is broken;
  highlight each as a point (attention). Highlight the source only if one of its
  own pins is an open end.
- a missing or misplaced connection: the two grid points that should be
  connected, as two point highlights with style attention. A misplaced wire gets
  its id plus the two points it should connect instead.
Highlight a wire only when it has to change: it sits where a part belongs, it is
misplaced, or it causes the problem (every wire of a shorted loop does). Never highlight wires that work as they
should. A wire on the grid is made of pieces; the learner sees a straight run of
pieces as one wire, so when a run has to change, highlight every piece in it,
from one part pin or junction to the next.
For misplaced, also highlight the target meter (attention); for near_target and
solved, highlight the target meter with success. no_source needs no highlight.
Set meta.hint_level to request.hint_level for a hint, else 0. Set meta.misconception only when the
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
    return {"meta": {"principle": "closed_loop", "highlights": [], "hint_level": 0, "misconception": None,
                     "topic_updates": [], "new_topic": None},
            "chat": {"kind": "question", "text": text, "formula": None}}


def circuit_summary(graph: dict, evaluation: dict) -> str:
    parts = []
    for c in graph["components"]:
        unit = {"voltage_source": " V", "resistor": " Ω"}.get(c["type"], "")
        parts.append(f"{c['id']}{' ' + str(c['value']) + unit if 'value' in c else ''}")
    readings = ", ".join(f"{m}={v if v is not None else '--'}" for m, v in evaluation["readings"].items())
    return f"parts: {', '.join(parts) or 'none'}; status: {evaluation['status']}; readings: {readings or 'none'}"


def build_context(level: dict, board: dict, reference: dict | None, history: list[dict], request: dict,
                  history_turns: int, evaluator_settings: dict | None = None,
                  snapshots: list[dict] | None = None, profile: dict | None = None) -> tuple[str, dict]:
    """The user turn for a tutor call, and the evaluation it is based on.

    `snapshots` are earlier boards since the last call ({seq, t_ms, graph, evaluation}); the
    current board is always added last, with its grid. `profile` is {skill_level, focus} from
    the learner profile, or None.
    """
    evaluation = evaluate(board, evaluator_settings)
    graph, _ = to_graph(board)
    timeline = [{k: s[k] for k in ("seq", "t_ms", "graph", "evaluation") if k in s} for s in snapshots or []]
    timeline.append({"current": True, "graph": graph, "evaluation": evaluation, "grid": board})
    level_info = {k: level.get(k) for k in ("title", "concept", "intro")} | {"targets": board.get("targets", {})}
    sections = [
        ("level", dumps(level_info)),
        ("reference", dumps(to_graph({**reference, "inventory": [], "targets": {}})[0]) if reference else "none"),
        ("summary", circuit_summary(graph, evaluation)),
        ("snapshots", dumps(timeline)),
        ("profile", dumps(profile) if profile else "none"),
        ("history", dumps(history[-history_turns:])),
        ("request", dumps(request)),
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


def _accept(message: dict, hint_level: int, board: dict, evaluation: dict, usage_log, purpose: str,
            session_id: str | None) -> dict:
    """A reply that passed the checks, with the hint ladder and the highlights enforced here, not
    by Claude (docs/tutor.md §3)."""
    message["meta"]["hint_level"] = hint_level
    if hint_level:
        message["chat"]["kind"] = "hint"
    message["chat"].setdefault("formula", None)
    returned = message["meta"].get("highlights", [])
    message["meta"]["highlights"] = clean_highlights(returned, board)
    # What Claude pointed at and what survived the board check, to see why nothing shows.
    usage_log.event("tutor_highlights", purpose=purpose, session_id=session_id, status=evaluation["status"],
                    returned=returned, kept=message["meta"]["highlights"])
    return message


def _usage(response) -> dict:
    usage = getattr(response, "usage", None)
    fields = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    return {f: getattr(usage, f, 0) or 0 for f in fields}


async def answer(client, config: dict, usage_log, *, level: dict, board: dict, reference: dict | None,
                 history: list[dict], learner_text: str | None = None, snapshots: list[dict] | None = None,
                 session_id: str | None = None, hint_level: int = 0, offer_hint: bool = False,
                 profile: dict | None = None, unchanged_moves: int = 0,
                 formulas: bool = False) -> tuple[dict, dict]:
    """Return (TutorMessage, evaluation) for a learner message, a hint of `hint_level` (1-4, decided
    by the session), or a reaction when both are absent; a reaction with `offer_hint` ends by
    offering a hint. `unchanged_moves` (a reaction) counts the learner's moves that didn't change the
    circuit since the last reply. `profile` is the learner's focus topics for the context.
    `formulas`: the reply may carry a formula (from curriculum level `tutor.formulas_from_level`).
    Raises anthropic.APIError on API failure."""
    reaction = learner_text is None and not hint_level
    purpose = "tutor_reaction" if reaction else "tutor_request"
    settings = config["claude"][purpose]
    if hint_level:
        request = {"action": "hint", "hint_level": hint_level}
        if learner_text:
            request["learner_text"] = learner_text
    elif reaction:
        request = {"trigger": "reaction"}
        if offer_hint:
            request["offer_hint"] = True
        if unchanged_moves:
            request["unchanged_moves"] = unchanged_moves
    else:
        request = {"action": "message", "learner_text": learner_text}
    if formulas:
        request["formulas"] = True
    user_turn, evaluation = build_context(
        level, board, reference, history, request,
        config.get("tutor", {}).get("history_turns", 6), config.get("evaluator"), snapshots, profile,
    )
    placed, inventory = board_quantities(board, evaluation)
    answers = [] if hint_level == 4 else answer_values(reference, placed)
    max_lines = config.get("tutor", {}).get("formula_max_lines", 8)
    content, message, found = user_turn, None, []
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
        usage_log.claude_call(purpose=purpose, model=settings["model"], usage=_usage(response),
                              session_id=session_id, attempt=attempt, stop_reason=response.stop_reason,
                              duration_ms=int((time.monotonic() - started) * 1000))
        text = next((b.text for b in response.content if b.type == "text"), None)
        if response.stop_reason == "refusal" or text is None:
            message = None
            break
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            message = None
            break
        chat = message["chat"]
        # No formula before the formulas level or on hint rung 1: dropped without a retry.
        if chat.get("formula") and (not formulas or hint_level == 1):
            usage_log.event("formula_dropped", session_id=session_id, attempt=attempt, formula=chat["formula"],
                            problems=["no formula allowed here"])
            chat["formula"] = None
        found = location_talk(chat["text"])
        leaked = answer_in_text(chat["text"], answers)
        problems = (check(chat["formula"], allowed=placed + inventory, answers=answers, rung=hint_level,
                          max_lines=max_lines) if chat.get("formula") else [])
        if not found and not leaked and not problems:
            return _accept(message, hint_level, board, evaluation, usage_log, purpose, session_id), evaluation
        notes = []
        if found:
            usage_log.event("tutor_backstop", session_id=session_id, attempt=attempt, matches=found)
            notes.append("Your previous reply described locations (" + ", ".join(found)
                         + "). Explain the physics instead and point with highlights.")
        if leaked:
            usage_log.event("tutor_answer", session_id=session_id, attempt=attempt, matches=leaked)
            notes.append("Your previous reply gave the answer (" + ", ".join(leaked)
                         + "). Lead the learner to it instead.")
        if problems:
            usage_log.event("formula_dropped" if attempt == 2 else "formula_retry", session_id=session_id,
                            attempt=attempt, formula=chat["formula"], problems=problems)
            notes.append("Your previous chat.formula failed the math check: " + "; ".join(problems) + ".")
        content = user_turn + "\n\n" + " ".join(notes)
    if message is not None and not found and not leaked:  # only the formula is wrong: send the text
        message["chat"]["formula"] = None
        return _accept(message, hint_level, board, evaluation, usage_log, purpose, session_id), evaluation
    fallback = fallback_message(evaluation["status"])
    if hint_level:  # still a hint: it counts on the ladder and shows as one
        fallback["meta"]["hint_level"] = hint_level
        fallback["chat"]["kind"] = "hint"
    return fallback, evaluation
