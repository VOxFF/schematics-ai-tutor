#!/usr/bin/env bash
# Integrity checks before every PR: docs, config, layout, secrets, scripts, tests.
# Runs locally (uses backend/.venv when present) and in CI.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="$ROOT/backend/.venv/bin/python"
[ -x "$PY" ] || PY=python3

echo "== docs, config, layout, secrets"
"$PY" scripts/check_integrity.py

echo "== shell scripts"
for script in start.sh stop.sh check.sh test.sh; do
  bash -n "$script"
done
echo "scripts: ok"

echo "== backend tests"
"$PY" -m pytest -q backend
