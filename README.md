# schematics-ai-tutor

A Claude-based tutor for learning electric circuits and schematics on an interactive grid.

## Structure

- [`docs/`](docs/): design documents. Start with [task.md](docs/task.md), then [design.md](docs/design.md), [contract.md](docs/contract.md), [schematics.md](docs/schematics.md), [tutor.md](docs/tutor.md), [gui.md](docs/gui.md) and [plan.md](docs/plan.md).
- [`frontend/`](frontend/): grid editor and tutor UI
- [`backend/`](backend/): circuit evaluator and Claude API integration

## Run locally

```sh
cp .env.example .env    # once; add ANTHROPIC_API_KEY
./start.sh              # starts the backend in the background
./stop.sh
```

Logs are in `.run/`. Details are in [backend/README.md](backend/README.md).
