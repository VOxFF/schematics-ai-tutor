#!/usr/bin/env bash
# Stop everything started by ./start.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN="$ROOT/.run"

stop_service() {
  local name="$1" pidfile="$RUN/$1.pid"
  # Only stop a live uvicorn process; a stale PID may now belong to something else.
  if [ ! -f "$pidfile" ] || ! ps -p "$(cat "$pidfile")" -o command= 2>/dev/null | grep -q uvicorn; then
    echo "$name not running"
    rm -f "$pidfile"
    return
  fi
  local pid
  pid="$(cat "$pidfile")"
  kill "$pid"
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "$name did not stop in time; killing"
    kill -9 "$pid"
  fi
  rm -f "$pidfile"
  echo "$name stopped"
}

stop_service backend
