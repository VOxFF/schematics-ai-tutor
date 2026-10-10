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
- Logs: `.run/backend.log`

## Test

```sh
backend/.venv/bin/pytest -q backend
```
