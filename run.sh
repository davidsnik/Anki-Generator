#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/anki-generator || ! -f frontend/dist/index.html ]]; then
  ./install.sh
fi
exec .venv/bin/anki-generator serve --open-browser "$@"
