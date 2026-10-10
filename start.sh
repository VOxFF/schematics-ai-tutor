#!/usr/bin/env bash
# Start the local dev stack in the background. Logs and PIDs go to .run/.
# Usage: ./start.sh            (BACKEND_PORT defaults to 8000, FRONTEND_PORT to 5173)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN="$ROOT/.run"
mkdir -p "$RUN"

# Local secrets and overrides, e.g. ANTHROPIC_API_KEY (see .env.example).
if [ -f "$ROOT/.env" ]; then
  set -a
  . "$ROOT/.env"
  set +a
fi
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export BACKEND_PORT FRONTEND_PORT
# One run id per ./start.sh: the backend writes logs/run-<id>.jsonl (if enabled in config.yaml).
export SCHEMATICS_RUN_ID="$(date +%Y%m%d-%H%M%S)"
export SCHEMATICS_CONFIG="$ROOT/config.yaml"

# Fall back to the gitignored key file when the key isn't set (see backend/keys/README.md).
KEY_FILE="$ROOT/backend/keys/apikey.txt"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$KEY_FILE" ]; then
  ANTHROPIC_API_KEY="$(tr -d '[:space:]' < "$KEY_FILE")"
  export ANTHROPIC_API_KEY
fi
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "warning: ANTHROPIC_API_KEY is not set; Claude features will be unavailable" >&2
fi

# True when the PID file ($1) points at a live process whose command contains $2
# (guards against stale PIDs reused by unrelated processes).
is_running() {
  [ -f "$1" ] && ps -p "$(cat "$1")" -o command= 2>/dev/null | grep -q "$2"
}

# Wait until $1 answers, then print $2; fail with a pointer to the log $3.
wait_for() {
  for _ in $(seq 1 40); do
    if curl -sf "$1" > /dev/null; then
      echo "$2"
      return
    fi
    sleep 0.5
  done
  echo "not ready: $1; see $3" >&2
  exit 1
}

start_backend() {
  local pidfile="$RUN/backend.pid"
  if is_running "$pidfile" uvicorn; then
    echo "backend already running (pid $(cat "$pidfile"))"
    return
  fi

  local venv="$ROOT/backend/.venv"
  if [ ! -x "$venv/bin/python" ]; then
    echo "creating backend virtualenv..."
    python3 -m venv "$venv"
  fi
  # Reinstall only when pyproject.toml changed since the last install.
  local stamp="$venv/.installed"
  if [ ! -f "$stamp" ] || [ "$ROOT/backend/pyproject.toml" -nt "$stamp" ]; then
    echo "installing backend dependencies..."
    "$venv/bin/pip" install -q --upgrade pip
    "$venv/bin/pip" install -q -e "$ROOT/backend[dev]"
    touch "$stamp"
  fi

  (
    cd "$ROOT/backend"
    nohup "$venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" --reload \
      > "$RUN/backend.log" 2>&1 &
    echo $! > "$pidfile"
  )

  wait_for "http://127.0.0.1:$BACKEND_PORT/api/health" \
    "backend ready:  http://127.0.0.1:$BACKEND_PORT (log: .run/backend.log)" .run/backend.log
}

start_frontend() {
  local pidfile="$RUN/frontend.pid"
  if is_running "$pidfile" vite; then
    echo "frontend already running (pid $(cat "$pidfile"))"
    return
  fi

  local dir="$ROOT/frontend"
  # Reinstall only when package-lock.json changed since the last install.
  if [ ! -d "$dir/node_modules" ] || [ "$dir/package-lock.json" -nt "$dir/node_modules/.package-lock.json" ]; then
    echo "installing frontend dependencies..."
    (cd "$dir" && npm ci --silent)
  fi

  (
    cd "$dir"
    nohup ./node_modules/.bin/vite > "$RUN/frontend.log" 2>&1 &
    echo $! > "$pidfile"
  )
  wait_for "http://127.0.0.1:$FRONTEND_PORT/" \
    "frontend ready: http://127.0.0.1:$FRONTEND_PORT (log: .run/frontend.log)" .run/frontend.log
}

start_backend
start_frontend
