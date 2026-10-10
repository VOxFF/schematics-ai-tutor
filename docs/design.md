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
- Everything Claude produces is untrusted input. Generated tasks pass the same validator as the learner's work, and the system falls back to curated content when they fail.

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
    end
    C[(Claude API)]

    TG -- "skill level + task history" --> C
    C -- "task proposal" --> TG
    TG -- "validate + compute targets" --> E
    TG -- "task" --> W
    W -- "learner's work" --> E
    E -- verdict + results --> TS
    TS -- task context + results --> C
    C -- feedback / hint --> TS
    TS -- verdict + tutor message --> T
```

- **Frontend:** JavaScript + React. It owns the interactive workspace and displays the tutor's messages. It holds no secrets and does no grading.
- **Backend:** Python. It owns the evaluator and all Claude API calls.
- **Task flow:** Claude proposes a task. The evaluator validates it and computes its targets, and the frontend receives the resulting task. Details are in [schematics.md](schematics.md#3-task-flow).
- **Request flow:** the frontend sends the learner's work. The backend runs the evaluator, passes its result together with the task context to Claude, and returns both the verdict and the tutor message.
- **Transport:** REST for static resources (curated levels), and one WebSocket per learning session for the interactive loop: live evaluation on every board edit and validated tutor messages. Details are in [contract.md](contract.md).

## 4. Security and operations

- The Claude API key exists only on the backend, loaded from the environment.
- The backend applies basic rate limiting, since the deployed prototype is public.

## 5. Configuration

The Claude models and behavior knobs live in one YAML file, `backend/config.yaml`, not in code. That lets us switch models, for example Opus vs. Haiku for reactions, and tune thresholds without code changes. The API key is never in this file; it comes from the environment.

```yaml
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
  task_generation:
    model: claude-opus-5-5
    effort: high
    max_tokens: 16000
    timeout_s: 120
    max_validate_calls: 5
    max_attempts: 2

tutor:
  idle_threshold_ms: 1500
  max_snapshots: 10
  history_turns: 6
  offer_hint_after_reactions: 3

task_generation:
  recent_tasks: 10

evaluator:
  near_target_ratio: 0.10      # "near_target" when within 10% of every target
  resistor_max_power_w: 5      # above this, a resistor is "overcurrent"
```

The values above are the defaults, as described in [contract.md](contract.md).

## 6. Stack

| Layer | Choice | Status |
|---|---|---|
| Backend | Python | Decided |
| Frontend | JavaScript + React | Decided |
| Frontend ↔ backend transport | REST + WebSocket | Decided |
| Workspace rendering | three.js | Decided |
| Hosting | — | Open |

**Why three.js:** every component and wire is its own scene node, so the learner can select, move and edit any of them individually.

## Open decisions

- Hosting and deployment
