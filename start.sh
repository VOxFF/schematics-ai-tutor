#!/usr/bin/env bash
# Start the local dev stack in the background. Logs and PIDs go to .run/.
# Usage: ./start.sh            (BACKEND_PORT defaults to 8000)
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

is_running() {
  [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null
}

start_backend() {
  local pidfile="$RUN/backend.pid"
  if is_running "$pidfile"; then
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

  for _ in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:$BACKEND_PORT/api/health" > /dev/null; then
      echo "backend ready: http://127.0.0.1:$BACKEND_PORT (log: .run/backend.log)"
      return
    fi
    sleep 0.5
  done
  echo "backend did not become healthy; see .run/backend.log" >&2
  exit 1
}

start_backend
# The frontend will be started here once it exists.
