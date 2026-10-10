#!/usr/bin/env bash
# Backend tests.
#   ./test.sh           unit + api tests (offline, free)
#   ./test.sh live      live Claude tests (cost money; LIVE_TASKS=N for more tasks)
#   ./test.sh -k grid   extra arguments are passed to pytest
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY=python3

if [ "${1:-}" = "live" ]; then
  shift
  KEY_FILE="$ROOT/backend/keys/apikey.txt"
  if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$KEY_FILE" ]; then
    ANTHROPIC_API_KEY="$(tr -d '[:space:]' < "$KEY_FILE")"
    export ANTHROPIC_API_KEY
  fi
  cd "$ROOT/backend" && exec "$PY" -m pytest -m live -s "$@"
fi

cd "$ROOT/backend" && exec "$PY" -m pytest -q "$@"
