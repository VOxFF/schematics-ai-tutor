# Plan

The major steps to build the product. A step is checked off when it is complete, and steps are added as development goes on.

## 1. Design

- [x] Project structure (`docs/`, `frontend/`, `backend/`)
- [x] Task: product, concept of operations, workflow, constraints ([task.md](task.md))
- [x] System design ([design.md](design.md))
- [x] Build plan (this file)
- [x] Contracts: frontend ↔ backend and backend ↔ Claude ([contract.md](contract.md))
- [x] Gitignore for the Python and React stack
- [ ] Tutor design: teaching behavior, system prompt, hint ladder content
- [x] Domain design: grid model, components, netlist mapping, evaluator checks ([schematics.md](schematics.md))
- [x] Board data format: the `grid` document ([schematics.md](schematics.md))
- [x] Graph format: the `graph` document with pin-pair edges ([schematics.md](schematics.md#2-graph-format-the-graph-document))
- [x] Task flow: generation, validation stages, derivation, grading ([schematics.md](schematics.md#3-task-flow))
- [ ] Evaluator design: revise `schematics.md` §4–8 for the grid and graph (solver with ammeter, structural checks including ammeter in parallel, rendering)
- [x] Terminology: "grid" across the docs
- [ ] Level design and progression
- [x] Workspace rendering decision: three.js
- [ ] Hosting decision

## 2. Backend

- [ ] Scaffold the Python service
- [ ] Grid format validation
- [ ] Grid-to-graph conversion
- [ ] Circuit solver (voltages and currents)
- [ ] Structural checks (shorts, open circuits, bypassed components)
- [ ] Meter readings: rounding to resolution, target tolerance check
- [ ] Curated levels (one per concept) and goal checking
- [ ] Task generation: Claude call, `validate_grid` tool, derivation, retries and fallback
- [ ] Background pre-generation of the next task
- [ ] Tutor service: Claude API integration and prompts
- [ ] REST endpoints and WebSocket session
- [ ] Rate limiting and API key handling
- [ ] Tests for the evaluator

## 3. Frontend

- [ ] Scaffold the React app
- [ ] Grid rendering
- [ ] Placing and removing components from inventory
- [ ] Wire pieces: straight, corner, T and +
- [ ] Level view: targets, inventory, check action, next task
- [ ] Live meter readings and tutor focus highlights
- [ ] Tutor panel
- [ ] Backend integration

## 4. Integration and deployment

- [ ] End-to-end playthrough of all levels
- [ ] Deploy backend and frontend
- [ ] Smoke test on the public URL

## 5. Polishing

- [ ] Revisit the redundancy of component `orientation` and `pins`

## 6. Submission

- [ ] Written design rationale
- [ ] Walkthrough video (8 minutes or less)
- [ ] Export Claude transcripts
- [ ] Submit by email: repo link, prototype link, transcripts, video and doc
