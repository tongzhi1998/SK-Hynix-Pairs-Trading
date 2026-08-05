#!/usr/bin/env bash
set -euo pipefail

cleanup() {
  kill "$backend_pid" "$frontend_pid" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

.venv/bin/uvicorn backend.main:app --reload --port 8010 &
backend_pid=$!

npm run dev &
frontend_pid=$!

wait "$backend_pid" "$frontend_pid"
