#!/usr/bin/env bash
# Install reproducible dependencies and produce the local production frontend.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if ! command -v uv >/dev/null 2>&1; then
  echo "Install uv first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi
if ! command -v pnpm >/dev/null 2>&1; then
  echo "Install Node.js 24 LTS (or 22.13+) and pnpm, then run ./install.sh again." >&2
  exit 1
fi
uv sync --locked
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend run build
rm -rf src/anki_generator/web_assets
mkdir -p src/anki_generator/web_assets
cp -R frontend/dist/. src/anki_generator/web_assets/
echo "Installation complete. Launch with ./run.sh"
