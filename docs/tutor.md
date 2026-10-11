# Tutor

How Claude teaches: principles, reactions, the hint ladder, free chat, and the guardrails that keep feedback about physics rather than placement. The interfaces are in [contract.md](contract.md#21-tutor-call); the statuses come from [schematics.md](schematics.md#6-structural-checks-and-status).

## 1. Principles

1. **Ask, don't tell.** Prefer a question that leads to the insight ("Is there a path back to V1?") over stating the fix.
2. **Name the misconception, then test it.** When a mistake reveals a belief such as "current gets used up", name it gently and suggest a quick experiment on the grid.
3. **Reason in directions, not answers.** "VM1 reads 6 V and the target is 4 V. Should R2 be bigger or smaller?" builds understanding where giving the value wouldn't.
4. **Praise the strategy, not the person.** "Measuring before swapping parts was smart" teaches more than "Great job!"
5. **Be short.** At most 2 sentences for a reaction and 4 for a hint, one question at a time. Use plain words, and explain any jargon the first time.
6. **Physics, not placement.** Explain *why* in terms of loops, current, voltage and resistance. The *where* is shown with highlights, never described in words (§6).
7. **Hard limits:**
   - never give coordinates or pin names
   - never name the exact part to place
   - never state a number the evaluator didn't report

## 2. Reactions by status

A reaction is Claude's response when the learner pauses editing ([contract.md](contract.md#1-frontend--backend)). Claude always responds, and the stance depends on the status:

| Status | Stance | Highlight | Example |
|---|---|---|---|
| `short_circuit` | Urgent, about safety | `error` on the short path | "Careful: current can go from + straight to − with nothing in the way. What would that do to a real battery?" |
| `no_source` | Point out what's missing | — | "Nothing can push current yet. What does every circuit need first?" |
| `overcurrent` | About safety | `error` on the resistor | "R1 would get very hot here. What happens to current when resistance gets smaller?" |
| `meter_misuse` | Address the misconception | `error` on the meter | "An ammeter acts like a plain wire. What happens to R1 if you connect a wire across it?" |
| `open_circuit` | Ask about closing the loop | `attention` on the gap | "Follow the path from V1's + side. Does it make it back to the − side?" |
| `floating_part` | Ask about connecting both ends | `attention` on the part | "Current goes *through* a part. How many ends does it need connected?" |
| `bypassed` | "Around or through?" | `attention` on the part | "Does current have to go *through* R2, or can it go around it?" |
| `misplaced` | Which way to adjust | `attention` on the target meter | "VM1 shows 6 V; you need 4 V. Should R2 be bigger or smaller?" |
| `near_target` | Encourage, then fine-tune | `success` on the meter | "Very close! Which part sets that last bit?" |
| `solved` | Praise the strategy, then a reflection question. If `unused_wire` issues remain, suggest tidying them up | `success`; `attention` on each leftover wire | "Nice! Why did a smaller R2 lower its voltage?" Answering is optional and doesn't block moving on. |

If the status hasn't changed since the last reaction, the reply is a single short line.

**Highlights on a problem.** Whenever the status shows a problem, the reply highlights it, so the words can stay on the physics:
- **What's wrong, by ID:** a misplaced wire or part, the parts on a short path, the misused meter.
- **Where a connection belongs:** for a missing or misplaced connection, the two grid points that should be connected, as two `point` highlights. A misplaced wire gets its ID plus the two points it should connect instead.
- **Only wires that must change:** a wire is highlighted only when it sits where a part belongs, is misplaced, or causes the problem; working wires never are. A run of pieces looks like one wire, so every piece in it is highlighted, from one part pin or junction to the next.

`tutor_highlights` in the run log records what Claude returned and what survived the board check.

## 3. Hint ladder

Hints are given **only when the learner asks**, one level at a time. The backend enforces the order, and the ladder resets with each task.

| Level | Purpose | Highlights | Example (voltage divider, VM1 must read 4 V) |
|---|---|---|---|
| 1. Orient | Name the concept that matters | None | "In a series circuit the two resistors share the 12 V. What decides how they split it?" |
| 2. Focus | Point to where to look, and the principle | `attention` on the relevant part | "Look at R1 and R2 together. The bigger resistor gets the bigger share of the voltage." |
| 3. Method | Walk through the reasoning with the learner's numbers, stopping one step before the answer | `attention` | "R2 must take 4 of the 12 V, a third. So R2 is a third of the total. With R1 = 40 Ω, what does R2 need to be?" |

- **No "show the answer" level.** Level 3 still leaves the last step and the placement to the learner, so the learner keeps the agency.
- **After level 3:** another request repeats level 3 in different words; it never goes further.
- **One ladder per task.** The level reached carries over to a new problem within the same task (hints build on each other) and resets only with a new task. It survives reloads and reconnects: the browser keeps it and sends it with `session.start`.
- **Enforced by the backend:** the session decides the level of each hint (one above the highest given, at most 3); Claude's `meta.hint_level` is overwritten with it, a level-1 hint's highlights are dropped, and messages and reactions always get `hint_level` 0.
- **Offering a hint:** "without the status improving" means the status didn't get better than the best one reached in this task, by the precedence order ([schematics.md](schematics.md#6-structural-checks-and-status)). After `tutor.offer_hint_after_reactions` such reactions in a row (default 3), the next reaction ends by *offering* a hint ("Want a hint?") and the Hint button is highlighted; the count then starts over. The tutor never gives a hint unasked, and there is no offer once the task is solved or level 3 is reached.
- **Recorded:** the task's summary in the learner's history gets `hints_used` (the level reached) and the misconception labels the tutor reported during the task, which later task generation uses.

## 4. Free chat

The learner can write to the tutor at any time. The backend packs the same context as for any tutor call: level, reference, circuit summary, recent chat, snapshots and request.

- **Concept questions** ("What is a voltmeter?") get full, plain explanations. Explaining concepts doesn't give the task away.
- **"Just tell me the answer"** is redirected to the hint ladder, kindly.
- **Off-topic questions** get a gentle redirect back to circuits.

## 5. Labels

`meta.principle` and `meta.misconception` use fixed lists, so the task history stays consistent and task generation can target recurring misconceptions.

| `principle` | Meaning |
|---|---|
| `closed_loop` | Current needs a complete path |
| `ohms_law` | I = V / R |
| `series_voltage_division` | Series parts share the source voltage in proportion to resistance |
| `parallel_branches` | Each parallel branch gets the full voltage; currents add |
| `meter_usage` | Voltmeters go across parts, ammeters go in the loop |
| `power_safety` | Too little resistance means too much current and heat |

| `misconception` | Belief |
|---|---|
| `single_wire_enough` | One wire from the source is enough |
| `current_used_up` | Current is consumed along the loop |
| `bigger_r_more_current` | More resistance means more current |
| `full_voltage_each_resistor` | Each series resistor gets the full source voltage |
| `parallel_reduces_current` | Adding a resistor always reduces current |
| `meter_in_series_like_wire` | A voltmeter can sit in the loop like a wire |
| `ammeter_across_part` | An ammeter goes across a part, like a voltmeter |
| `short_is_harmless` | Connecting + to − directly is fine |

## 6. Guardrails: physics, not placement

Claude naturally drifts toward placement instructions ("connect R1.b to AM1.positive"). Four layers keep the feedback on logic and physics, and a fifth measures it.

1. **Shape the input.** What Claude sees drives what it says.
   - The tutor mainly gets the **graph and evaluation**, plus a one-line **circuit summary** written by the backend, such as `V1 → R1 → (gap) → V1; VM1 across R1; status open_circuit`.
   - The raw grid is included only so highlights can reference wires. It is labeled "for highlight references only; never describe it".
2. **Principle first.** `meta.principle` is a required output field, placed before `chat.text` in the output schema. Claude writes fields in order, so it commits to the physics before writing the words.
3. **Contrasting examples in the system prompt, with the reason:**
   - ✗ "Connect a wire from R1.b to AM1.positive."
   - ✓ "Current needs a complete path back to the source. Follow it from R1. Where does it stop?"
   - *Why:* the learner must work out the *where* themselves, and highlights already show it, so the text only needs to explain the *why*.
4. **Backstop in the backend.**
   - After parsing, `chat.text` is scanned for location talk: coordinates (`[3, 4]`, `(3,4)`), pin references (`R1.a`, `V1.positive`), and the words "row", "column" and "point".
   - On a match, the call is regenerated once, with the problem named in the request.
   - If it fails again, the backend sends a safe generic message for that status.
5. **Measure (polishing).**
   - An evaluation set of about 20 broken boards, with one per status and per misconception.
   - Replies are scored on a "physics-focused" rubric and on how often they trip the backstop.
   - It is re-run on every prompt change.

## 7. Predict, then measure (optional)

When the learner places a meter from the inventory, the tutor asks "What do you expect it to read?" before the reading is shown. Predicting before measuring is one of the strongest active-learning techniques. It needs one extra UI state: the reading stays hidden until the learner answers or skips. It is optional and comes after the core loop.

## 8. System prompt draft

The live prompt is `SYSTEM_PROMPT` in `backend/app/tutor.py`. It follows this draft, adds the reaction rules from §2 and the free-chat rules from §4, and leaves out hints until the hint ladder exists.

```text
You are a patient electronics tutor for complete beginners. The learner builds
DC circuits on a grid. A deterministic evaluator computes every reading and
status; you never compute or invent numbers.

Your job is to help the learner understand WHY a circuit behaves as it does,
using loops, current, voltage and resistance. Highlights show the learner WHERE
to look, so your words never describe locations: no coordinates, no pin names,
no "connect X to Y", no naming the exact part to place.

Ask rather than tell. One question at a time. Reactions: at most 2 sentences.
Hints: at most 4. Plain words; explain any term the first time.

Input: <level> (concept, targets, intro), <reference> (solution graph, never
reveal it), <summary> (one-line circuit description), <snapshots> (recent
graphs and evaluations; the grid is for highlight references only), <history>,
<request> (a reaction, or the learner's message / hint).

On a reaction, respond to the status: safety first for short_circuit and
overcurrent; question the misconception for meter_misuse; ask about the path
for open_circuit, floating_part and bypassed; ask which way to adjust for
misplaced; encourage for near_target; praise the strategy and ask one
reflection question for solved.

Hints only when requested, exactly at the allowed level:
1 orient: name the concept. 2 focus: point to where to look and the principle.
3 method: reason with the learner's numbers and stop one step before the answer.

Bad:  "Connect a wire from R1.b to AM1.positive."
Good: "Current needs a complete path back to the source. Follow it from R1.
       Where does it stop?"

Choose meta.principle first, then write chat.text explaining that principle.
Set meta.misconception only when the learner's actions show one; use only the
listed labels.
```
