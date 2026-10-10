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
- [x] Domain design: breadboard model, components, netlist mapping, evaluator checks ([schematics.md](schematics.md))
- [ ] Level design and progression
- [x] Workspace rendering decision: three.js
- [ ] Hosting decision

## 2. Backend

- [ ] Scaffold the Python service
- [ ] Breadboard-to-netlist conversion
- [ ] Circuit solver (voltages and currents)
- [ ] Structural checks (shorts, open circuits, bypassed components)
- [ ] Level definitions and goal checking
- [ ] Tutor service: Claude API integration and prompts
- [ ] REST endpoints and WebSocket session
- [ ] Rate limiting and API key handling
- [ ] Tests for the evaluator

## 3. Frontend

- [ ] Scaffold the React app
- [ ] Breadboard rendering
- [ ] Placing and removing components and wires
- [ ] Level view: goal, available components, check action
- [ ] Tutor panel
- [ ] Backend integration

## 4. Integration and deployment

- [ ] End-to-end playthrough of all levels
- [ ] Deploy backend and frontend
- [ ] Smoke test on the public URL

## 5. Submission

- [ ] Written design rationale
- [ ] Walkthrough video (8 minutes or less)
- [ ] Export Claude transcripts
- [ ] Submit by email: repo link, prototype link, transcripts, video and doc
