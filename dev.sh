#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/uvicorn || ! -d frontend/node_modules ]]; then
  ./install.sh
fi
if ! command -v pnpm >/dev/null 2>&1; then
  echo "Node.js/pnpm is needed for the frontend development server." >&2
  exit 1
fi
.venv/bin/uvicorn anki_generator.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload &
backend_pid=$!
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT INT TERM
pnpm --dir frontend run dev
