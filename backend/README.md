# Backend

Deterministic circuit evaluator and Claude API integration, as a FastAPI service. See [docs/design.md](../docs/design.md).

## Run

From the repo root:

```sh
cp .env.example .env    # optional; or put the key in backend/keys/apikey.txt
./start.sh              # creates backend/.venv, installs, starts on :8000
./stop.sh
```

- Health check: `curl http://127.0.0.1:8000/api/health`
- Server output: `.run/backend.log`
- Usage and cost log: `logs/run-<timestamp>.jsonl`, one per `./start.sh`; on/off via `logs.enabled` in the root `config.yaml`

## Test

```sh
./test.sh            # unit + api (offline; Claude is faked)
./test.sh live       # live Claude task generation; costs money
```

| Tier | Folder | Claude |
|---|---|---|
| unit | `tests/unit/` | not used |
| api | `tests/api/` | fake client |
| live | `tests/live/` | real API, opt-in |

## Try task generation

```sh
curl -s -X POST http://127.0.0.1:8000/api/tasks/generate \
  -H 'content-type: application/json' -d '{"skill_level": 2}'
```
