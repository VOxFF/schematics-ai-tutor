# Task

## Product description

**Schematics AI Tutor** is a web app where entry-level learners learn basic electricity by building circuits on a virtual breadboard. The learner builds the circuit, a deterministic evaluator checks it, and Claude acts as a tutor: it gives feedback, hints and an assessment of the learner's direction.

The goal is understanding, not task completion. The learner should leave able to reason about why a circuit behaves the way it does.

**Target user:** a beginner with little or no electronics background, such as a student, a hobbyist starting with Arduino, or a career switcher.

## Concept of operations

### Actors

| Actor | Role |
|---|---|
| Learner | Builds circuits on the breadboard and responds to the tutor |
| Breadboard editor | Lets the learner place and remove components and wires; produces the circuit layout |
| Evaluator | Deterministic. Converts the layout to a netlist, computes voltages and currents, and checks them against the level goal |
| Claude tutor | Reads the level, the learner's circuit and the evaluator's results, then gives feedback, hints and an assessment of the learner's direction |

### Operating principles

1. **The learner does the work.** The tutor never places components or hands over the solution.
2. **The evaluator is the source of truth.** Every electrical value shown to the learner or given to Claude comes from the evaluator, never from the model.
3. **Claude reasons about the learner, not the circuit.** It turns evaluator results into teaching: what the learner seems to believe, what to try next, and why.

### Levels

The learning path is a sequence of levels that grow in complexity, starting with basic circuits. Each level defines:

- a starting breadboard (empty or partially built)
- the available components (resistors, voltmeters, wires, power source)
- a goal: a target voltage or current at a specific point in the circuit
- the concept being taught

## Workflow

1. The learner opens a level and sees the goal, the starting breadboard and the available components.
2. The learner places components and wires into breadboard holes.
3. The learner submits the circuit for checking.
4. The evaluator builds the netlist and computes the values. It reports whether the goal is met, along with structural issues such as shorts, open circuits and components bypassed in the same row.
5. Claude receives the level, the circuit and the evaluator results and responds with feedback and, if needed, a hint.
6. The learner revises and repeats from step 2, or advances when the goal is met.

## Major constraints

| Constraint | Implication |
|---|---|
| Built in under a day | One core loop done well; a handful of levels; minimal polish |
| Must be deployed and usable by reviewers | Public URL; Claude API key stays server-side; basic rate limiting |
| Must use the Claude API | Claude provides the tutoring layer |
| Claude must not be trusted for electrical math | Deterministic evaluator; Claude only interprets its output |
| Entry-level audience | Simple DC circuits only (resistors, sources, meters); plain language, no jargon without explanation |
| Enhance, not replace, human agency | No auto-solve; hints escalate only when the learner asks |
| Stack | Python backend; JavaScript/React frontend |

## To be defined

- Claude's exact responsibilities and the hint escalation policy
- Level list and progression
- Breadboard rendering (three.js or SVG)
- Whether current is measured with an ammeter component or reported directly by the evaluator
