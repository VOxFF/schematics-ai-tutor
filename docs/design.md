# Design

Major design decisions for the system as a whole. For the product, its workflow and its constraints, see [task.md](task.md). Domain-specific design (circuits, the grid, levels) is in [schematics.md](schematics.md).

## 1. Separate ground truth from tutoring

The system separates deterministic code from Claude, with strictly divided responsibilities:

| Engine | Responsibility | Nature |
|---|---|---|
| Evaluator | Decides what is correct: validates generated tasks, computes target values, grades the learner's work | Deterministic code |
| Task generator (Claude) | Proposes new tasks tailored to the learner | LLM; output validated |
| Tutor (Claude) | Decides how to teach: feedback, hints, assessment of the learner's direction | LLM |

**Why:** LLMs make calculation errors, and a tutor that is confidently wrong does more harm than no tutor. Deterministic evaluation also makes results reproducible and testable.

**Rules:**
- Claude never produces or overrides a verdict or a computed value. It receives the evaluator's output as input and reasons about the *learner*.
- Everything Claude produces is untrusted input. Generated tasks pass the same validator as the learner's work, and the system falls back to curated content when they fail (curated levels are planned; today a failed generation shows an error with a retry).

## 2. The learner keeps agency

- The learner performs every action in the workspace. The tutor has no ability to modify it.
- Hints are given in response to learner actions or requests, not unprompted solutions.

## 3. System architecture

```mermaid
flowchart LR
    subgraph FE["Frontend (React)"]
        W[Interactive workspace]
        T[Tutor panel]
    end
    subgraph BE["Backend (Python)"]
        TG[Task generator]
        E["Evaluator (deterministic)"]
        TS[Tutor service]
        RC[Reply composer]
        LP[(Learner profile)]
    end
    C[(Claude API)]

    TG -- "skill level + task history" --> C
    C -- "task proposal" --> TG
    TG -- "validate + compute targets" --> E
    TG -- "task" --> W
    W -- "learner's work" --> E
    E -- verdict + results --> TS
    LP -- "focus topics + scores" --> TS
    TS -- "task context + results + profile" --> C
    C -- "feedback / hint / knowledge<br/>+ topic updates" --> RC
    RC -- "clamped score changes, new topics" --> LP
    RC -- "verdict + composed message + profile" --> T
```

- **Frontend:** JavaScript + React. It owns the interactive workspace and displays the tutor's messages. It holds no secrets and does no grading.
- **Backend:** Python. It owns the evaluator and all Claude API calls.
- **Task flow:** Claude proposes a task. The evaluator validates it and computes its targets, and the frontend receives the resulting task. Details are in [schematics.md](schematics.md#3-task-flow).
- **Tasks are pre-generated and cached on the backend.** A generated task takes 20–90 s depending on the level (first tasks ~25 s, level 14 ~60 s at `high` effort), which is too long to wait at Start or Next.
  - *Cache by progress:* the cache key is the learner's progress (skill level and task history). A request for a progress gets the cached task at once; if that task is still being generated, it waits for the same generation instead of starting another; otherwise it generates one now. A task is removed from the cache when it's served, so the same progress later (e.g. after Restart Learning) gets a fresh task.
  - *Next task in the background:* after serving a task, the backend generates the next one, for the progress as if the served task is solved. By the time the learner presses Next it's usually ready. A resumed task (e.g. after a server restart, which empties the cache) does the same when its session starts, from the progress the browser sends with `session.start`.
  - *First-task pool:* for the start screen, the server keeps a small pool of ready first tasks, filled at startup and topped up as they are served, so even a first visit doesn't wait.
  - *Bounds:* the cache has a size cap and an expiry, and pre-generation counts against the daily Claude budget: it stops at 80% of it, leaving the rest for learners who are waiting (§5).
  - *Accepted loss:* the next task is generated before the current one is finished, so it doesn't know that task's hints or misconceptions. A wait at Next costs more.
  - *Why the backend, not the browser:* the browser stays a plain client (it calls the generate endpoint as before), the cache survives reloads because the same progress gets the same entry, and every decision to spend a Claude call is made on the server, next to the rate limits and the budget. The cost is in-memory server state, lost on restart and not shared between instances, which is acceptable for one prototype server.

  ```mermaid
  sequenceDiagram
      participant FE as Frontend
      participant BE as Backend
      participant C as Claude

      Note over BE,C: startup: fill the first-task pool
      FE->>BE: generate (progress: level 1)
      BE-->>FE: task A, from the pool (no wait)
      BE->>C: background: refill the pool
      BE->>C: background: task after A (progress: A solved)
      Note over FE: the learner solves A
      FE->>BE: generate (progress: A solved)
      BE-->>FE: task B, cached (no wait)
      BE->>C: background: task after B
  ```
- **Two feedbacks per edit, fast and slow.** Every finished edit is sent to the backend.
  - *Fast:* the evaluator runs at once, with no Claude call, and its readings and status reach the browser within a split second. The edit also clears Claude's highlights, which described the previous board.
  - *Slow:* when editing pauses, the backend passes the evaluator's results, the task context and the learner's profile to Claude, validates the reply, composes it (§4), and sends the composed message and new highlights.
  - *Why:* readings must feel like a real meter, and Claude takes seconds. A reply is tagged with the board it is about, so one that arrives after a newer edit shows its text but never overwrites the fresh readings or draws highlights on a changed board ([contract.md](contract.md#1-frontend--backend)).

  ```mermaid
  sequenceDiagram
      participant L as Learner
      participant FE as Frontend
      participant EV as Evaluator
      participant C as Backend + Claude

      L->>FE: edit (board #5)
      FE->>FE: clear Claude's highlights
      FE->>EV: board #5
      EV-->>FE: readings + status (#5), within a split second
      Note over FE,C: fast feedback ends here
      Note over L,FE: learner pauses
      Note over C: idle timer fires: reaction on board #5
      L->>FE: edit (board #6) while Claude thinks
      FE->>EV: board #6
      EV-->>FE: readings + status (#6)
      C-->>FE: reply about #5: text shown, highlights and readings dropped
      Note over L,FE: learner pauses again
      Note over C: idle timer fires: reaction on board #6
      C-->>FE: reply about #6: text and highlights shown
  ```
- **Editor and inventory are one three.js widget.** The grid and the inventory are drawn in a single scene with a single camera, not as separate widgets.
  - *Why:* parts must look the same size in the inventory and on the board. With two widgets, each one's size depended on the other's (board scale → inventory size → editor width → board scale), and the layout kept resizing. In one scene they share a scale by construction.
  - *Scale:* the scene's bounds are computed once per task from its starting board (the inventory reserves the starting rows), so editing never rescales; only a window resize refits the camera.
  - Details are in [gui.md](gui.md#6-inventory).
- **Picking is by drawn shape, and one drag serves the inventory and the board.** Hit-testing walks the scene nodes' own meshes (planes, circles, rings), grown by 2 screen pixels, instead of slot rectangles or raycasts. A drag keeps the grab offset, so the element never jumps to the pointer.
  - *Why:* bounding boxes made empty space around symbols clickable, and a rectangular hotspot can't tell a thin wire from the gap next to it. One mechanism for every source keeps the inventory and the board behaving alike. Details are in [gui.md](gui.md#4-grid).
- **Reference solutions stay on the server.** When a task is generated, the backend keeps its complete board in memory by level ID (bounded). The tutor uses it as `<reference>`; the browser only ever receives the task board.
- **Transport:** REST for resources and task generation (`/api/tasks/generate`; `/api/levels` is planned with the curated levels), and one WebSocket per learning session for the interactive loop: live evaluation on every board edit and validated tutor messages. Details are in [contract.md](contract.md).

## 4. Tutoring experience: learning path, learner profile, reply composer

**Problem.** Claude only gets the task, the board and the evaluation, so it can only coach the task. Every reply sounds the same: a question about the circuit. Claude doesn't know which ideas are new to the learner, which ones it has already explained, or which ones the learner has shown they understand. So it can't decide when to stop asking and teach a fundamental rule instead.

**Decision.** The learner gets a **profile** of the topics they have met, with two scores per topic. Claude reads the recent and weak topics with every call, decides what to teach, and reports how the scores change. A backend step, the **reply composer**, applies those changes within strict bounds and prepares the message for the chat.

### Learning path: topics

A **topic** is either a fundamental **principle** ("current needs a complete path") or a **term** ("ammeter", "resistance"). A catalog, `backend/data/topics.yaml`, lists the topics with an ID, name, type, a one-line definition, and where the learner first meets each one: a curriculum level, or a component type first seen on the board.

| Curriculum level | Principles | Terms |
|---|---|---|
| 1 Closed loop | `closed_loop` | circuit, current, voltage source, open circuit |
| 2 Ohm's law | `ohms_law` | resistance, ohm, volt, ampere |
| 3 Ohm's law, more choices | — | resistor color code |
| 4 Series resistors | `series_voltage_division` | series, voltage drop |
| 5 Parallel resistors | `parallel_branches` | parallel, branch, junction |
| 6 Series–parallel | — | equivalent resistance |
| 7 Measuring right | `meter_usage` | measuring across, measuring in the loop |
| 8 Power and safety | `power_safety` | power, watt, short circuit |
| First on the board | — | ammeter, voltmeter |

- The principles are the existing `meta.principle` labels ([tutor.md](tutor.md#5-labels)), so there is one list of principles.
- **Claude can add topics.** When a reply teaches something the catalog doesn't have (e.g. "conductor"), Claude can add it as a new topic: an ID, a name, a type and a one-line definition. Claude can also bring a catalog topic forward, e.g. "short circuit" when the learner makes one at level 1. Either way the topic joins this learner's profile only; the catalog doesn't change.

### Learner profile

The profile is the learner's knowledge list: every topic they have met, with two scores from 0 to 3.

| Field | Meaning |
|---|---|
| `id`, `name`, `type` | The topic (`principle` or `term`) |
| `introduced` | The skill level at which the learner met it; recency is measured from it |
| `understanding` | What the learner has shown: 0 not yet seen, 1 shaky, 2 mostly, 3 solid |
| `explained` | How much the tutor has explained it: 0 never, 1 mentioned, 2 explained, 3 explained more than once |
| `source` | `catalog` or `claude` |

- **Joining:** when a task starts, the topics of its curriculum level (and of earlier levels, if missing), and of any component type new on its board, join the profile with both scores at 0. Topics from Claude join when it adds them.
- **Stored with the session.** Like the progress and the chat, the profile is kept in the browser's `localStorage`, sent with `session.start`, and returned in the reply to it and with each tutor message. A reload or a server restart loses nothing.
- **Focus.** Claude doesn't get the whole profile, only up to 8 **focus topics**: the most recently introduced first, then any older ones with `understanding` 0 or 1. Recent topics are what the current tasks teach. Old weak ones are what keeps tripping the learner up.

### Rules for Claude

The system prompt gives Claude the rules for the scores and lets it decide what to do with them in each reply:

- **Raise `understanding`** (+1) only on evidence: the learner fixed a problem without a hint, answered a reflection question correctly, or explained the idea in their own words. **Lower it** (−1) when a mistake or a misconception shows a gap in that topic.
- **Raise `explained`** (+1) when this reply explains the topic.
- **Choosing the reply:**

  | Topic state | What the tutor does |
  |---|---|
  | `explained` 0, and the moment touches it | Teach it: a `knowledge` message, two sentences tied to what's on the grid ("An ammeter has almost no resistance, so current flows through it. That's why it goes in the loop.") |
  | `explained` ≥ 1, `understanding` ≤ 1 | Don't re-explain. Ask a question that tests it ("Do you need a larger or a smaller resistance?") |
  | `understanding` ≥ 2 | Keep it short: confirm, or praise the strategy, and move on |

- **Safety first:** for `short_circuit` and `overcurrent` the reply is about safety. A `knowledge` message waits until that's settled.
- **At most one topic** is taught per reply, and at most one new topic is added.
- The tutor's other rules don't change: physics, not placement; no invented numbers; the hint ladder ([tutor.md](tutor.md)).

### Reply composer

The tutor service validates Claude's reply and runs the backstop ([tutor.md](tutor.md#6-guardrails-physics-not-placement)). The reply composer then turns it into what the chat shows:

1. **Score changes:** each change must name a topic in the profile, or the topic Claude added. Changes are clamped to ±1 per reply and kept within 0–3, and `explained` never goes down. Anything else is dropped and logged.
2. **New topic:** its ID must be new and its name and definition short. It joins the profile with `source: claude`.
3. **Presentation:** it adds the icon for the message's kind and, for a `knowledge` message, the topic's name as a title. It also marks the first mention of each profile topic in the text ("voltage source" before "voltage", plurals included), and the chat shows those words in bold, so the learner sees the vocabulary they are building.
4. **Message:** it sends the composed chat message and the updated profile in `tutor.message`.

The composer is plain code, so it is unit tested like the evaluator. It is also the place for later changes to presentation and tone (e.g. not opening three replies in a row with a question), with no change to the prompt.

**Message kinds.** `knowledge` joins the existing kinds. Each kind has its own tint and icon, so a lesson, a hint and praise look different at a glance:

| Kind | Purpose | Tint | Icon |
|---|---|---|---|
| `praise` | Praise the strategy | green | 🎉 |
| `nudge` | Point at a misstep | orange | 👉 |
| `feedback` | Comment on the circuit | blue | 💡 |
| `question` | Ask the learner to reason | pink | ❓ |
| `knowledge` | Teach a principle or a term | gold | 📘 |
| `hint` | A step of the hint ladder | purple | 🔑 |

```mermaid
flowchart LR
    subgraph IN["Context for Claude"]
        L[Task + evaluation]
        F["Focus topics<br/>(recent, weak)"]
        H[Chat history]
    end
    IN --> C[(Claude)]
    C -- "kind, text, highlights,<br/>topic updates, new topic" --> V["Validate + backstop"]
    V --> RC["Reply composer"]
    RC -- "clamp, apply" --> P[(Learner profile)]
    RC -- "icon, title" --> M["Composed message"]
    M --> FE["Chat bubble<br/>(tint by kind)"]
    P -- "returned to the browser,<br/>sent back with session.start" --> F
```

- **Why Claude decides and the code bounds it.** Judging evidence of understanding from a learner's edits and words is what Claude is good at. Code can't do it. But scores that drift by several points per reply, or topics added in bulk, would make the profile meaningless. So the backend clamps every change, the same split as for verdicts and readings (§1).
- **Build status.** Built: the catalog, the profile (`learner_profile.py`), the reply composer (`reply_composer.py`), the prompt rules and the chat bubbles. Interfaces are in [contract.md](contract.md), the prompt rules in [tutor.md](tutor.md#teaching-from-the-learner-profile).
- **Later uses.** The profile is ready to feed task generation (target weak topics) and the Learning Path screen ([gui.md](gui.md#9-learning-path-screen-bonus)). Neither is part of this change.

## 5. Security and operations

- The Claude API key exists only on the backend, loaded from the environment or the gitignored `backend/keys/apikey.txt`.
- The deployed prototype is public and uses our API key, so the backend enforces the rate limits below. They protect the cost of Claude calls and the server. **Evaluation never depends on Claude**, so when a Claude limit is hit, the grid, the readings and the status keep working. Only the tutor goes quiet, or generation pauses.

### Rate limits

One module, [`rate_limits.py`](../backend/app/rate_limits.py), with its own configuration file, [`ratelimiting.yaml`](../ratelimiting.yaml) in the repo root. The backend reads it at startup, together with `config.yaml`.

| Scope | Limit (default) | When exceeded |
|---|---|---|
| Daily Claude budget | $20 of estimated spend per day, all calls; the day resets at 00:00 UTC | Pre-generation stops at 80% (`background_share`), keeping the rest for learners who are waiting. At 100%: tutor requests get `error: tutor_unavailable` ("the tutor has reached today's limit"), reactions are skipped, and generation gets `429`. Evaluation is unaffected. |
| Tutor calls per session | 6 per minute (reactions and messages together), one in flight | Reactions are skipped silently. A learner message gets `error: rate_limited`, shown as "The tutor needs a moment; try again shortly". |
| Task generations per IP | 10 per hour | `429` with "Task generation is paused; please try again in N min" and `Retry-After`. Curated levels will be served here once they exist. |
| WebSocket sessions per IP | 30 per hour (reconnects included), 3 open at once | The server sends `error: rate_limited` and closes with code `1008`; the client waits 30 s before reconnecting instead of 2 s |
| REST requests per IP | 60 per minute, except `/api/health` | `429` with `Retry-After` |
| Board updates per session | 20 per second | Coalesced: the latest board waits until the limit allows, then it's evaluated; older ones in between are dropped |
| Grid size | 30 × 30 points, 40 components, 300 wire pieces; learner boards and generated tasks | `error: bad_message` for a learner board; a generated task fails validation. This also bounds solver and validation time. |

Where each limit applies on the way to Claude: a per-session or per-IP rate first, then the shared daily budget. Evaluation has no budget gate.

```mermaid
flowchart LR
    subgraph IN["Requests"]
        WS["WebSocket connect"]
        GEN["POST /api/tasks/generate"]
        BU["board.update"]
        TR["tutor.request / reaction"]
        PRE["Pre-generation<br/>(background)"]
    end
    WS -->|"sessions per IP<br/>30/h, 3 open"| S[Session]
    GEN -->|"REST per IP 60/min<br/>generations per IP 10/h"| B1{"Budget<br/>< 100%?"}
    BU -->|"20/s per session<br/>(coalesced) + grid size"| EV["Evaluator<br/>no Claude, never limited by budget"]
    TR -->|"6/min per session<br/>one in flight"| B1
    PRE --> B2{"Budget<br/>< 80%?"}
    B1 -->|yes| C[(Claude)]
    B2 -->|yes| C
    C -->|"cost of each call"| BUD["Daily budget<br/>$20, resets 00:00 UTC<br/>state/claude-budget.json"]
```

- **Budget in dollars, not calls.** Calls differ a lot in cost (a generation turn costs about 2.5 times a reaction), so the budget counts the estimated spend that the usage log already computes from the `pricing` table in `config.yaml`. Every Claude call adds its cost as it completes. A call is only checked before it starts, so the last calls of the day can overshoot the cap slightly.
- **Pre-generation stops first.** Background generations (the first-task pool, the next task) need the budget under `background_share`; a learner waiting for a task or the tutor can use the rest.
- **The budget survives restarts.** The day's spend is kept in `state/claude-budget.json` (gitignored), on the Fly volume when deployed ([deployment.md](deployment.md#5-logs)), so a deploy doesn't reset it. All other counters are in memory and start from zero on a restart; that's harmless.
- **Per IP, where there's no session.** Generation is a REST call without a session ID, so it's limited per IP. The IP is the `Fly-Client-IP` header, set by Fly's proxy; locally, the socket's address.
- **Implementation.** Sliding windows per key and a daily budget, in memory in the single backend process. Running several instances would need a shared store such as Redis; that is noted for scale, not built for the prototype.

```yaml
claude_budget:
  usd_per_day: 20              # estimated spend of all Claude calls (pricing in config.yaml); resets 00:00 UTC
  background_share: 0.8        # pre-generation stops at this share, keeping the rest for waiting learners
  state_dir: state             # the day's spend survives restarts; SCHEMATICS_STATE_DIR overrides it (Fly: /data/state)

tutor:
  calls_per_session_per_min: 6   # reactions and learner requests together; one call in flight

task_generation:
  per_ip_per_hour: 10          # REST generation has no session, so it's counted per IP

sessions:
  per_ip_per_hour: 30          # WebSocket sessions, reconnects included
  open_per_ip: 3

rest:
  requests_per_ip_per_min: 60  # /api/*, except /api/health

board_updates:
  per_session_per_sec: 20      # beyond this, updates are coalesced: only the latest board is evaluated

grid:                          # learner boards and generated tasks; also bounds solver time
  max_points: 30               # per side
  max_components: 40
  max_wires: 300
```

### Operations

- **Usage and cost log.** When `logs.enabled` is on, the backend writes one JSON-lines log per run, `logs/run-<timestamp>.<part>.jsonl` (gitignored). It records server start and stop, every Claude call (purpose, model, learner session ID, token usage, estimated cost from the `pricing` table), each log archive, and a run summary with totals. Each `./start.sh` is one run; a code reload continues it in a new part. Earlier parts are gzipped into `logs/history/` within a size budget ([deployment.md](deployment.md#5-logs)).
- **Deployment.** Fly.io: one Docker image on one always-on machine, shipped from GitHub Actions with the `deploy` label: deployed, smoke tested live, then merged, or rolled back. Details are in [deployment.md](deployment.md).
- **Message size.** No fixed limit yet; the grid size caps already bound it indirectly. Typical message sizes will be observed in practice before a limit is set.

## 6. Configuration

The Claude models, behavior knobs, logging and pricing live in one YAML file, [`config.yaml`](../config.yaml) in the repo root, not in code. Rate limits have a file of their own, [`ratelimiting.yaml`](../ratelimiting.yaml) (§5). That lets us switch models, for example Opus vs. Haiku for reactions, and tune thresholds without code changes. The API key is never in this file; it comes from the environment.

```yaml
public: false                  # true for a public deployment: hides debug features
                               # (read by the frontend build; restart the dev server after a change;
                               # SCHEMATICS_PUBLIC overrides it, and the Dockerfile sets true)

logs:                          # archived at startup, by size and nightly (deployment.md §5)
  enabled: true                # usage and cost log per backend run
  dir: logs                    # SCHEMATICS_LOGS_DIR overrides it (Fly: /data/logs)
  history_dir: history         # gzipped earlier parts, inside dir
  max_file_mb: 20              # archive when a log's current part grows past this
  history_max_mb: 200          # history budget for all logs; oldest files deleted first
  nightly_utc: "10:00"         # daily archive (3 am Pacific)

pricing:                       # USD per million tokens, for cost estimates
  claude-opus-5-5: { input: 4.00, output: 20.00, cache_read: 0.20, cache_write: 5.00 }

claude:
  tutor_reaction:              # idle-triggered reactions
    model: claude-opus-5-5
    effort: low
    max_tokens: 16000
    timeout_s: 30
  tutor_request:               # learner message / hint
    model: claude-opus-5-5
    effort: medium             # rarer than reactions and matter more
    max_tokens: 16000
    timeout_s: 30
  skill_summary:               # bonus: Learning Path screen
    model: claude-opus-5-5
    effort: low
    max_tokens: 16000
    timeout_s: 30
  task_generation:
    model: claude-opus-5-5
    effort: high
    max_tokens: 16000
    timeout_s: 120
    max_validate_calls: 5        # validate_grid tool calls per attempt
    max_attempts: 2              # failed attempts before giving up and telling the learner

tutor:
  idle_threshold_ms: 1500
  max_snapshots: 10
  history_turns: 6
  offer_hint_after_reactions: 3

task_generation:
  recent_tasks: 10

pregeneration:                 # tasks generated ahead of time and cached (§3)
  enabled: true
  first_task_pool: 2           # ready first tasks for new learners, filled at startup
  max_entries: 50              # cached or running generations, oldest dropped first
  ttl_s: 3600                  # a cached task older than this is dropped

evaluator:
  near_target_ratio: 0.10      # "near_target" when within 10% of every target
  resistor_max_power_w: 5      # above this, a resistor is "overcurrent"
```

The values above are the defaults, as described in [contract.md](contract.md). The backend reads the file at startup, so changes need a restart (`./stop.sh && ./start.sh`).

## 7. Stack

| Layer | Choice | Status |
|---|---|---|
| Backend | Python, FastAPI + uvicorn | Decided |
| Frontend | JavaScript + React, built with Vite | Decided |
| Frontend ↔ backend transport | REST + WebSocket | Decided |
| Workspace rendering | three.js | Decided |
| Hosting | Fly.io: one Docker image, one always-on machine ([deployment.md](deployment.md)) | Decided |

**Why three.js:** every component and wire is its own scene node, so the learner can select, move and edit any of them individually.

## 8. Repository layout

A snapshot of the repository; it is updated as the structure changes. Entries marked *(gitignored)* exist only locally.

```text
schematics-ai-tutor/
├── README.md                  project overview and how to run
├── LICENSE
├── config.yaml                models, knobs, logging, pricing (§6)
├── ratelimiting.yaml          rate limits and the daily Claude budget (§5)
├── Dockerfile                 production image: built frontend + backend (docs/deployment.md)
├── fly.toml                   Fly.io app: region, one always-on machine, health check
├── .dockerignore
├── start.sh                   start the backend and frontend in the background
├── stop.sh                    stop it
├── check.sh                   integrity checks: docs, config, layout, secrets, tests
├── test.sh                    backend tests: unit + api, or live (real Claude)
├── smoke.sh                   smoke test of a deployed app (docs/deployment.md)
├── .env.example               optional local overrides (copy to .env)
├── .gitignore
├── .github/
│   └── workflows/
│       ├── ci.yml             ./check.sh on every PR push and on main
│       └── deploy.yml         `deploy` label: check, deploy, smoke, merge; rollback on failure
├── scripts/
│   └── check_integrity.py     docs, config, layout and secrets checks used by check.sh
├── docs/
│   ├── task.md                product, concept of operations, constraints
│   ├── design.md              system design (this file)
│   ├── contract.md            frontend ↔ backend and backend ↔ Claude interfaces
│   ├── schematics.md          grid and graph formats, task flow, evaluator, levels
│   ├── tutor.md               tutor behavior, hint ladder, guardrails
│   ├── gui.md                 screens, layout, interaction, learner journey
│   ├── deployment.md          hosting, secrets, continuous deployment, operations
│   ├── plan.md                build plan with checklist
│   └── images/
│       └── gui-layout.png     GUI layout sketch
├── backend/
│   ├── README.md
│   ├── pyproject.toml         FastAPI service and dependencies
│   ├── app/
│   │   ├── main.py            FastAPI app: REST endpoints, startup and shutdown
│   │   ├── config.py          loads the root config.yaml
│   │   ├── usage_log.py       per-run usage and cost log
│   │   ├── log_archive.py     log files in parts; gzip into history/, size cap, nightly
│   │   ├── rate_limits.py     rate limits and the daily Claude budget (ratelimiting.yaml)
│   │   ├── grid.py            grid format validation
│   │   ├── graph.py           grid → graph conversion, nets
│   │   ├── solver.py          DC modified nodal analysis
│   │   ├── evaluate.py        status, readings and issues
│   │   ├── task_spec.py       TaskSpec schema, validation stages, targets, task-grid derivation
│   │   ├── curriculum.py      skill level → curriculum level and task; level-fit and centering checks
│   │   ├── task_generation.py Claude task generation with the validate_grid tool
│   │   ├── task_cache.py      pre-generated tasks cached by progress; the first-task pool
│   │   ├── tutor.py           tutor call: context, TutorMessage schema, backstop
│   │   ├── learner_profile.py learner profile: topic catalog, sanitizing, topics joining per task, focus topics
│   │   ├── reply_composer.py  bounds Claude's profile changes; icon and title per message kind
│   │   ├── session.py         WebSocket learning session
│   │   └── jsonfmt.py         readable JSON formatting
│   ├── data/
│   │   ├── curriculum.yaml    curriculum levels: tasks per level, rules for generation
│   │   ├── topics.yaml        topic catalog: principles and terms per curriculum level and component type
│   │   └── examples/          example TaskSpecs for the generation prompt
│   ├── tests/
│   │   ├── conftest.py        examples and a fake Claude client
│   │   ├── unit/              pure logic, offline
│   │   ├── api/               endpoints with a fake Claude
│   │   └── live/              real Claude calls, opt-in (./test.sh live)
│   ├── keys/
│   │   ├── README.md
│   │   └── apikey.txt         Anthropic API key (gitignored)
│   └── .venv/                 Python virtualenv, created by start.sh (gitignored)
├── frontend/
│   ├── README.md
│   ├── package.json           React app; Vite for dev server and build, Vitest for tests
│   ├── package-lock.json
│   ├── vite.config.js         dev server on :5173, proxies /api and /ws to the backend; reads `public` from config.yaml
│   ├── index.html
│   ├── src/
│   │   ├── main.jsx           entry point
│   │   ├── App.jsx            screen switching, session, task fetching
│   │   ├── App.test.jsx
│   │   ├── public.test.jsx    a public build hides debug features
│   │   ├── index.css          layout and styles
│   │   ├── components/
│   │   │   ├── StartScreen.jsx
│   │   │   └── TutorScreen.jsx  learning screen layout (header, task, editor, inventory, chat)
│   │   ├── editor/
│   │   │   ├── GridEditor.jsx three.js renderer, camera fit, label layer
│   │   │   ├── scene.js       scene graph: one node per component and wire; the inventory region; outlines and highlights
│   │   │   ├── placement.js   where a dragged part or wire piece goes, whether it fits, the new board
│   │   │   ├── naming.js      captions and names of inventory parts (20 Ω, 4.7 kΩ)
│   │   │   ├── colorCode.js   resistor 4-band color code
│   │   │   ├── schematic-style.yaml  sizes and colors of the schematic (wires, pins, symbols)
│   │   │   └── style.js       loads the style file; grid spacing
│   │   └── lib/
│   │       ├── api.js         backend calls
│   │       ├── session.js     localStorage session
│   │       ├── tutorSession.js WebSocket session hook (chat, live evaluation)
│   │       ├── jsonfmt.js     readable JSON, same rules as the backend formatter
│   │       └── build.js       build-time settings from config.yaml (`public`)
│   ├── node_modules/          npm packages, installed by start.sh (gitignored)
│   └── dist/                  production build output (gitignored)
├── logs/                      usage and cost logs, one per run (gitignored)
├── state/                     state kept across restarts: the day's Claude spend (gitignored)
└── .run/                      PID files and server output from start.sh (gitignored)
```

### Conventions

- **Readable JSON.** JSON files in the repo, and JSON embedded in Claude prompts, are human-readable: indented, short arrays and objects on one line (`[5, 3]`), and arrays longer than 6 elements wrapped 6 per line. `backend/app/jsonfmt.py` implements it, and `./check.sh` enforces it for tracked `.json` files. Exceptions: JSONL logs (one event per line) and files written by tools in their own format (`package.json`, `package-lock.json`).

## Open decisions

None at the moment.
