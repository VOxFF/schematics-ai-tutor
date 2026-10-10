# Plan

The major steps to build the product. A step is checked off when it is complete, and steps are added as development goes on.

## 1. Design

- [x] Project structure (`docs/`, `frontend/`, `backend/`)
- [x] Task: product, concept of operations, workflow, constraints ([task.md](task.md))
- [x] System design ([design.md](design.md))
- [x] Build plan (this file)
- [x] Contracts: frontend ↔ backend and backend ↔ Claude ([contract.md](contract.md))
- [x] Gitignore for the Python and React stack
- [x] Tutor triggers: idle-triggered reactions on snapshots, plus learner requests ([contract.md](contract.md#21-tutor-call))
- [ ] Tutor design: teaching behavior, system prompt, hint ladder content
- [x] Domain design: grid model, components, netlist mapping, evaluator checks ([schematics.md](schematics.md))
- [x] Board data format: the `grid` document ([schematics.md](schematics.md))
- [x] Graph format: the `graph` document with pin-pair edges ([schematics.md](schematics.md#2-graph-format-the-graph-document))
- [x] Task flow: generation, validation stages, derivation, grading ([schematics.md](schematics.md#3-task-flow))
- [x] Task generation input: task context, learner context, skill level ([contract.md](contract.md#22-task-generation-call))
- [x] Evaluator design: pipeline, solver with ammeter, structural checks, rendering ([schematics.md](schematics.md#4-evaluation-pipeline))
- [x] Terminology: "grid" across the docs
- [ ] Level design: validate the curated levels by playtesting
- [x] Workspace rendering decision: three.js

## 2. Backend

- [ ] Scaffold the Python service
- [ ] Grid format validation
- [ ] Grid-to-graph conversion
- [ ] Circuit solver (voltages and currents)
- [ ] Structural checks (shorts, open circuits, bypassed components)
- [ ] Meter readings: rounding to resolution, target tolerance check
- [ ] Curated levels (tagged by skill level) and goal checking
- [ ] Task generation: Claude call, `validate_grid` tool, derivation, retries and fallback
- [ ] Background pre-generation of the next task
- [ ] Skill level and task history (`Progress`)
- [ ] Repeat check against recent task graphs
- [ ] Prompt examples as files, validated in tests
- [ ] Tutor service: Claude API integration and prompts
- [ ] Snapshot recording and idle-triggered reactions
- [ ] REST endpoints and WebSocket session
- [ ] Configuration loader for `config.yaml`
- [ ] Rate limiting and API key handling
- [ ] Tests for the evaluator

## 3. Frontend

- [ ] Scaffold the React app
- [ ] Grid rendering
- [ ] Placing and removing components from inventory
- [ ] Wire pieces: straight, corner, T and +
- [ ] Level view: targets, inventory, check action, next task
- [ ] Live meter readings and tutor highlights (components, wires, points)
- [ ] Tutor panel
- [ ] Backend integration

## 4. Integration and deployment

- [ ] End-to-end playthrough of all levels
- [ ] Hosting decision
- [ ] Deploy backend and frontend
- [ ] Smoke test on the public URL

## 5. Polishing

- [ ] Revisit the redundancy of component `orientation` and `pins`
- [ ] Compact reaction context: one-line action descriptions and evaluation deltas instead of full snapshots, and a `dangling_wire` issue for spatial missteps
- [ ] Append-only multi-turn tutor conversation, so earlier turns are served from the prompt cache
- [ ] Experiment: let Claude stay silent on neutral moves
- [ ] Tune the idle threshold for reactions
- [ ] Choose the model for reactions (Opus 5.5 at low effort vs. Haiku 5.5) by measuring cost and quality; switched in `config.yaml`

## 6. Submission

- [ ] Written design rationale
- [ ] Walkthrough video (8 minutes or less)
- [ ] Export Claude transcripts
- [ ] Submit by email: repo link, prototype link, transcripts, video and doc
