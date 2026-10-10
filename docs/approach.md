# Approach

Living document. It records the decisions made so far and what is still open.

## Context

This is a take-home prototype for Anthropic Education Labs. We chose **Option B, learning through collaboration with Claude**: a feature that helps users build real domain expertise while working with AI, not just complete tasks.

## Product

An AI tutor that teaches **electric circuits and schematics** to entry-level learners.

- **Interactive part:** a classic breadboard with pin holes. The learner places components (resistors, voltmeters, wires) to build circuits.
- **AI part:** Claude gives feedback and hints, and evaluates the learner's overall direction.
- **Progression:** multi-step levels that start with basic circuits and grow more complex. A typical task: place components or missing wires to reach a target voltage or current at a specific point in the circuit.

## Why this domain

Circuits are objectively checkable: a node is at 3 V or it isn't. That gives us a reliable ground truth to tutor against and a concrete way to measure whether learning happened.

## Architecture principle

The work is split into two parts:

| Concern | Owner |
|---|---|
| Electrical correctness (voltages, currents, connectivity) | Deterministic evaluator |
| Feedback, hints, evaluation of the learner's direction | Claude |

Claude is never the source of truth for electrical values. LLMs make arithmetic and circuit-analysis mistakes, and a tutor that is confidently wrong does more harm than no tutor. Claude receives the evaluator's results and reasons about the *learner*.

The breadboard layout is converted into a netlist: each row strip is one node, each power rail is one node, and a wire merges two nodes. The evaluator works on that netlist.

## Open questions

- Claude's exact responsibilities: what it sees, when it speaks, how hints escalate, what "evaluating direction" means.
- Level design and progression.
- Tech stack and deployment.

## Repository layout

| Directory | Contents |
|---|---|
| `docs/` | Design documents and rationale |
| `frontend/` | Breadboard editor and tutor UI |
| `backend/` | Evaluator and Claude API integration |
