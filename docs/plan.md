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
- [x] Tutor design: principles, reactions, hint ladder, free chat, guardrails, system prompt ([tutor.md](tutor.md))
- [x] Domain design: grid model, components, netlist mapping, evaluator checks ([schematics.md](schematics.md))
- [x] Board data format: the `grid` document ([schematics.md](schematics.md))
- [x] Graph format: the `graph` document with pin-pair edges ([schematics.md](schematics.md#2-graph-format-the-graph-document))
- [x] Task flow: generation, validation stages, derivation, grading ([schematics.md](schematics.md#3-task-flow))
- [x] Task generation input: task context, learner context, skill level ([contract.md](contract.md#22-task-generation-call))
- [x] Evaluator design: pipeline, solver with ammeter, structural checks, rendering ([schematics.md](schematics.md#4-evaluation-pipeline))
- [x] Evaluation result: status, readings of all placed meters, issues ([schematics.md](schematics.md#6-structural-checks-and-status))
- [x] GUI layout and learner concept of operations ([gui.md](gui.md))
- [x] Learning trajectory: curriculum levels 1–8 and tasks per level ([schematics.md](schematics.md#progression))
- [x] Workspace rendering decision: three.js

## 2. Backend

- [x] Scaffold the Python service (FastAPI, `/api/health`, pytest)
- [x] `start.sh` / `stop.sh` in the repo root
- [x] Grid format validation
- [x] Grid-to-graph conversion
- [x] Circuit solver (voltages and currents)
- [x] Structural checks and status precedence
- [x] Meter readings: rounding to resolution, target tolerance check
- [x] Task generation pipeline: Claude call with the `validate_grid` tool (format checks), structured `TaskSpec`, retry with errors, task-grid derivation, `POST /api/tasks/generate`
- [x] Task generation: electrical validation (working circuit, reconstruction from the task board, not already solved) and computed target values
- [ ] Curated fallback levels (tagged by curriculum level) when generation fails, validated by playtesting
- [ ] Server-side refusal fallbacks for Claude calls
- [x] Background pre-generation of the next task: a backend cache keyed by progress, and a pool of first tasks
- [x] Skill level and task history (`Progress`): kept in the browser, sent with every generation request
- [x] Repeat check against recent tasks (circuit signature)
- [x] Variety for identical contexts: random variation hints (layout, source voltage, resistor range)
- [x] Curriculum levels 1–8 (`backend/data/curriculum.yaml`): skill → level and task, rules in the prompt, deterministic level-fit and centering checks
- [ ] Level 9, troubleshooting: format extension for replaced parts
- [x] Prompt examples as files (`backend/data/examples/`), validated in tests
- [x] Tutor chat pipeline: learner message → backend context → Claude → validated `TutorMessage` (no hint ladder)
- [x] Tutor reactions on editing pauses
- [x] Snapshot recording and idle-triggered reactions
- [x] Highlights in replies: the cause of a problem by ID, and the two grid points a missing or misplaced connection should join
- [x] Leftover wires: `unused_wire` issue (no status change); on `solved` the tutor suggests tidying up and highlights them
- [x] Circuit summary line for the tutor
- [x] Location-talk backstop with regeneration and fallback messages
- [x] WebSocket session: `session.start`, `board.update`, `tutor.request` (message), per-session rate limit
- [ ] WebSocket task delivery (`task.next`, `task.ready`)
- [x] Configuration loader for the root `config.yaml`
- [x] Usage and cost log per backend run (`logs/`, on/off in `config.yaml`)
- [x] Integrity checks: `./check.sh` locally and in GitHub Actions on every PR
- [x] Rate limiting (per session, per IP, daily Claude budget in dollars) in `rate_limits.py` with `ratelimiting.yaml`; API key handling ([design.md](design.md#rate-limits))
- [x] Test suite tiers: `unit`, `api` (fake Claude), `live` (real Claude, opt-in); `./test.sh`
- [x] Tests for the evaluator

## 3. Frontend

- [x] Scaffold the React app (Vite, Vitest, dev proxy to the backend; started by `start.sh`)
- [x] Start screen: what it is, how it works, learning path, Start Learning
- [x] Learning screen layout: header, task/targets panel, editor, hint bar, inventory, chat
- [x] Grid rendering: schematic symbols, labels, resistor color bands, live readings (three.js, one scene node per element; JSON view behind a toggle)
- [x] Schematic style config: `frontend/src/editor/schematic-style.yaml`
- [x] Drag from the inventory and the wire palette onto the grid: ghost preview, blue/red target points, R to rotate, Esc and release-outside snap back, live `board.update`
- [x] Picking by drawn shape (grown by 2 px), drag without a jump (grab offset), and moving placed parts and wires with the same drag as the inventory
- [x] Selection on the grid: click to select, on release (a 4 px move makes it a drag), outline highlight (color in `schematic-style.yaml`), R to rotate in place, Del to remove (parts back to the inventory)
- [x] Wire palette: horizontal, vertical, corner, T, + (non-depleting, R to rotate)
- [x] Inventory drawn inside the editor scene: same scale as the board, two columns, fixed width, scale fixed per task, grid centered, lifted slot and floating ghost while dragging
- [x] Hint bar: idle, dragging, can't-place and selection hints
- [x] Reset board button (back to the task's starting board)
- [x] Skill level badge in the header; chat spans the full height
- [x] Visual style: neutral chrome, one accent, meaning colors as CSS variables
- [x] Header: tasks solved, Restart Learning (confirm, wipe, start screen)
- [x] Completing a task: when the status becomes `solved`, a bright green checkmark appears in the editor's top-left corner and Next is enabled; Next records the solved task and raises the skill level (replaces the temporary always-enabled Next)
- [x] Session persistence in `localStorage`: progress and level; resume on reload
- [x] Persist the chat
- [x] Persist the edited grid
- [x] Live meter readings on the grid and in the Targets column
- [x] Tutor highlights on the grid (components, wires, points)
- [x] Tutor panel: chat bubbles, thinking indicator, errors; live readings in the Task panel
- [x] Backend integration: task generation over REST, session, evaluation and tutor over the WebSocket

## 4. Integration and deployment ✅

- [x] `public` flag in `config.yaml`: a public build hides debug features (the editor's JSON view)
- [x] Hosting decision: Fly.io ([deployment.md](deployment.md))
- [x] Deploy backend and frontend: `Dockerfile` and `fly.toml`, one image serving both, at https://schematics-ai-tutor.fly.dev
- [x] Continuous deployment: GitHub Actions deploys each pull request and smoke tests it before the merge (replaced by the `deploy` label, below)
- [x] Ship with the `deploy` label: merge only after a live smoke test passes; automatic rollback on failure ([deployment.md](deployment.md#3-continuous-deployment))
- [x] Log archive on a Fly volume: startup, size and nightly triggers, compressed history with a size cap ([deployment.md](deployment.md#5-logs))
- [x] Smoke test on the public URL
- [x] Rate limiting and the daily Claude budget, live ([design.md](design.md#rate-limits))
- [x] Rollback drill: a deliberately failing smoke test, rolled back automatically ([deployment.md](deployment.md#7-status))

## 5. Learning depth

Built after the core workflow runs end to end.

- [x] Hint ladder: three levels, server-side enforcement, hint button in the UI
- [x] Offer a hint after stalled reactions
- [ ] Optional: predict, then measure (hide a new meter's reading until the learner predicts)

## 6. Polishing

Not Boring Chat ([design.md](design.md#4-tutoring-experience-learning-path-learner-profile-reply-composer)):

- [x] Design: learning path topics, learner profile, rules for Claude, reply composer, message kinds
- [x] Chat bubbles: a tint and an icon per message kind; the `knowledge` kind
- [x] Topic catalog `backend/data/topics.yaml`: principles and terms per curriculum level and per component type
- [x] Learner profile in the session: topics join per task, saved in `localStorage`, sent with `session.start`
- [x] Tutor context and prompt: focus topics, score rules, when to teach (`knowledge`) and when to ask
- [x] Reply composer: clamp and apply score changes, add Claude's new topics, icon and title, profile in `tutor.message`
- [x] Contract and tutor docs for the profile, the new `meta` fields and the `knowledge` kind

Other polishing:

- [ ] Solved checkmark fades out after ~2 s and leaves a small green check in the Task / Targets panel
- [x] If the learner breaks a solved circuit, the checkmark disappears and Next is disabled again
- [ ] Tutor highlights: glow and pulsing (`attention` pulses)
- [ ] Tutor highlights: different visuals for "remove this" and "connect here" (e.g. a dashed line between the two points); if Claude still highlights part of a wire run, extend wire highlights to the whole run in the backend
- [ ] Status display on the learning screen (e.g. a colored badge in the Task / Targets panel)
- [ ] Learner experience collection from the deployed app (moved from §4: product work, not deployment)
- [ ] Event log for measuring success: task started/solved, status changes, tutor calls, misconception labels
- [ ] State the supported devices (desktop: mouse and keyboard)
- [ ] Revisit the redundancy of component `orientation` and `pins`
- [ ] Compact reaction context: one-line action descriptions and evaluation deltas instead of full snapshots
- [ ] Append-only multi-turn tutor conversation, so earlier turns are served from the prompt cache
- [ ] Tutor evaluation set: ~20 broken boards, physics-focus rubric, backstop trip rate
- [ ] Experiment: let Claude stay silent on neutral moves
- [ ] Adaptive communication style: fewer questions when the learner doesn't engage in the chat (e.g. short statements and highlights instead), more dialogue when they do
- [ ] Observe typical WebSocket message sizes, then set a message size limit
- [ ] Tune the idle threshold for reactions
- [ ] Choose the model for reactions (Opus 5.5 at low effort vs. Haiku 5.5) by measuring cost and quality; switched in `config.yaml`

## 7. Bonus

Built only if time allows; nothing else depends on it.

- [ ] Learning Path screen and navigation from the header
- [ ] Skill summary call: strengths, needs attention, trends; cached until the next solved task
- [ ] Store each solved task's final grid in `Progress.history`
- [ ] Read-only grid view for solved tasks

## 8. Submission

- [ ] End-to-end playthrough of all levels on the public URL (moved from §4: the final sign-off)
- [ ] Written design rationale
- [ ] Walkthrough video (8 minutes or less)
- [ ] Export Claude transcripts
- [ ] Submit by email: repo link, prototype link, transcripts, video and doc
