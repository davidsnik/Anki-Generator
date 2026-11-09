#!/usr/bin/env bash
# Build Linux releases; no developer tools are required by the resulting application.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source "$project_root/scripts/toolchain.sh"

skip_checks=false
backend_only=false
appimage_only=false
directory_only=false
uv_command="${UV:-uv}"
pnpm_command="${PNPM:-pnpm}"
node_command="${NODE:-node}"
for argument in "$@"; do
  case "$argument" in
    --skip-checks) skip_checks=true ;;
    --backend-only) backend_only=true ;;
    --appimage-only) appimage_only=true ;;
    --dir) directory_only=true ;;
    --help)
      echo "Usage: ./scripts/build-desktop.sh [--skip-checks] [--backend-only|--appimage-only|--dir]"
      echo "Default: check code, freeze backend, build AppImage and RPM in dist/desktop/."
      exit 0 ;;
    *) echo "Unknown build option: $argument" >&2; exit 2 ;;
  esac
done

output_count=0
for selected in "$backend_only" "$appimage_only" "$directory_only"; do
  if "$selected"; then output_count=$((output_count + 1)); fi
done
if (( output_count > 1 )); then
  echo 'Choose only one of --backend-only, --appimage-only or --dir.' >&2
  exit 2
fi
for tool in "$uv_command" "$node_command" "$pnpm_command"; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Build requirement missing: $tool. See docs/desktop.md." >&2
    exit 1
  fi
done
if [[ "$(uname -s)" != Linux ]]; then
  echo "This release build currently supports Linux only." >&2
  exit 1
fi
if ! $backend_only && ! $appimage_only && ! $directory_only && ! command -v rpmbuild >/dev/null 2>&1; then
  echo "Install rpm-build, or explicitly select --appimage-only." >&2
  exit 1
fi

# A dedicated build environment avoids changing the browser/development environment.
export UV_PROJECT_ENVIRONMENT="$project_root/build/desktop/venv"
"$uv_command" sync --locked --group desktop-build
"$pnpm_command" --dir frontend install --frozen-lockfile
"$pnpm_command" --dir desktop install --frozen-lockfile
if ! $skip_checks; then
  "$uv_command" run --no-sync ruff check .
  "$uv_command" run --no-sync ruff format --check .
  "$uv_command" run --no-sync pytest
  "$pnpm_command" --dir frontend run format:check
  "$pnpm_command" --dir frontend test
  "$pnpm_command" --dir desktop test
else
  echo "Checks explicitly skipped; release verification must run them separately."
fi

"$pnpm_command" --dir frontend run build
"$uv_command" run --no-sync python scripts/copy-web-assets.py
"$uv_command" run --no-sync python packaging/create_icons.py
"$uv_command" run --no-sync python -m PyInstaller --noconfirm --clean \
  --distpath "$project_root/build/desktop/backend" \
  --workpath "$project_root/build/desktop/pyinstaller" packaging/backend.spec

if $backend_only; then
  echo "Frozen backend: build/desktop/backend/anki-generator-backend/anki-generator-backend"
  exit 0
fi
if $directory_only; then
  "$pnpm_command" --dir desktop run package:dir
  echo 'Runnable desktop application: dist/desktop/linux-unpacked/anki-generator'
  exit 0
elif $appimage_only; then
  "$pnpm_command" --dir desktop exec electron-builder --config electron-builder.cjs \
    --linux AppImage --publish never
else
  "$pnpm_command" --dir desktop run package
fi
echo "Desktop release files:"
find dist/desktop -maxdepth 1 -type f \( -name '*.AppImage' -o -name '*.rpm' \) \
  -printf '  %p (%s bytes)\n'
