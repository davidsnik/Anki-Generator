#!/usr/bin/env bash
# Build Linux releases; no developer tools are required by the resulting application.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

skip_checks=false
backend_only=false
appimage_only=false
for argument in "$@"; do
  case "$argument" in
    --skip-checks) skip_checks=true ;;
    --backend-only) backend_only=true ;;
    --appimage-only) appimage_only=true ;;
    --help)
      echo "Usage: ./scripts/build-desktop.sh [--skip-checks] [--backend-only] [--appimage-only]"
      echo "Default: check code, freeze backend, build AppImage and RPM in dist/desktop/."
      exit 0 ;;
    *) echo "Unknown build option: $argument" >&2; exit 2 ;;
  esac
done

for tool in uv node pnpm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Build requirement missing: $tool. See docs/desktop.md." >&2
    exit 1
  fi
done
if [[ "$(uname -s)" != Linux ]]; then
  echo "This release build currently supports Linux only." >&2
  exit 1
fi
if ! $backend_only && ! $appimage_only && ! command -v rpmbuild >/dev/null 2>&1; then
  echo "Install rpm-build, or explicitly select --appimage-only." >&2
  exit 1
fi

# A dedicated build environment avoids changing the browser/development environment.
export UV_PROJECT_ENVIRONMENT="$project_root/build/desktop/venv"
uv sync --locked --group desktop-build
pnpm --dir frontend install --frozen-lockfile
pnpm --dir desktop install --frozen-lockfile
if ! $skip_checks; then
  uv run --no-sync ruff check .
  uv run --no-sync ruff format --check .
  uv run --no-sync pytest
  pnpm --dir frontend run format:check
  pnpm --dir frontend test
  pnpm --dir desktop test
else
  echo "Checks explicitly skipped; release verification must run them separately."
fi

pnpm --dir frontend run build
uv run --no-sync python - <<'PY'
from pathlib import Path
import shutil

source = Path("frontend/dist")
destination = Path("src/anki_generator/web_assets")
if destination.exists():
    shutil.rmtree(destination)
shutil.copytree(source, destination)
PY
uv run --no-sync python packaging/create_icons.py
uv run --no-sync python -m PyInstaller --noconfirm --clean \
  --distpath "$project_root/build/desktop/backend" \
  --workpath "$project_root/build/desktop/pyinstaller" packaging/backend.spec

if $backend_only; then
  echo "Frozen backend: build/desktop/backend/anki-generator-backend/anki-generator-backend"
  exit 0
fi
if $appimage_only; then
  pnpm --dir desktop exec electron-builder --config electron-builder.cjs \
    --linux AppImage --publish never
else
  pnpm --dir desktop run package
fi
echo "Desktop release files:"
find dist/desktop -maxdepth 1 -type f \( -name '*.AppImage' -o -name '*.rpm' \) \
  -printf '  %p (%s bytes)\n'
