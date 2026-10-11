# schematics-ai-tutor

A Claude-based tutor for learning electric circuits and schematics on an interactive grid.

## Structure

- Full layout: [docs/design.md](docs/design.md#7-repository-layout)
- [`docs/`](docs/): design documents. Start with [task.md](docs/task.md), then [design.md](docs/design.md), [contract.md](docs/contract.md), [schematics.md](docs/schematics.md), [tutor.md](docs/tutor.md), [gui.md](docs/gui.md), [deployment.md](docs/deployment.md) and [plan.md](docs/plan.md).
- [`frontend/`](frontend/): grid editor and tutor UI
- [`backend/`](backend/): circuit evaluator and Claude API integration

## Run locally

```sh
# API key: backend/keys/apikey.txt (gitignored), or ANTHROPIC_API_KEY in .env
./start.sh              # starts backend (:8000) and frontend (:5173) in the background
./stop.sh
```

Open http://127.0.0.1:5173. Server output goes to `.run/backend.log` and `.run/frontend.log`. Usage and cost logs go to `logs/run-<timestamp>.jsonl` (toggle `logs.enabled` in [`config.yaml`](config.yaml)). Details are in [backend/README.md](backend/README.md).

## Deploy

Hosted on [Fly.io](https://fly.io) at https://schematics-ai-tutor.fly.dev. A merge to `main` will deploy automatically once checks pass (planned); details are in [docs/deployment.md](docs/deployment.md).

```sh
fly secrets set ANTHROPIC_API_KEY=...   # once
fly deploy                              # builds the Dockerfile remotely and rolls out
fly logs
```

## Tests

```sh
./test.sh            # unit + api tests: offline, free
./test.sh live       # real Claude calls: cost money (LIVE_TASKS=N for more)
```

## Checks

```sh
./check.sh    # links, config vs. docs, layout snapshot, secrets, scripts, backend and frontend tests
```

The same checks run in GitHub Actions on every pull request.
