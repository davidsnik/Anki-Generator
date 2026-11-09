#!/usr/bin/env bash
# Small shared operations behind the developer-facing Makefile.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source "$project_root/scripts/toolchain.sh"
uv_command="${UV:-uv}"
pnpm_command="${PNPM:-pnpm}"
node_command="${NODE:-node}"

require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required tool missing: $1. Run make doctor for setup guidance." >&2
    exit 1
  fi
}

doctor() {
  local missing=0 package_mode=false tool version package
  if [[ "${1:-}" == --package ]]; then
    package_mode=true
    shift
  fi
  if [[ $# -ne 0 ]]; then
    echo 'Usage: make doctor [ARGS=--package]' >&2
    return 2
  fi
  echo 'Required development tools:'
  for tool in "$uv_command" "$node_command" "$pnpm_command" make; do
    if command -v "$tool" >/dev/null 2>&1; then
      version="$("$tool" --version 2>&1)" || { echo "  FAIL $tool could not report its version"; missing=1; continue; }
      printf '  OK   %s: %s\n' "$tool" "${version%%$'\n'*}"
    else
      printf '  FAIL %s is not on PATH\n' "$tool"
      missing=1
    fi
  done
  if command -v "$node_command" >/dev/null 2>&1; then
    if ! "$node_command" -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 13) ? 0 : 1)'; then
      echo '  FAIL Node.js 24 LTS (or 22.13+) is required.'
      missing=1
    fi
  fi
  if command -v rpmbuild >/dev/null 2>&1; then
    echo '  OK   rpmbuild is available for Fedora RPM packaging.'
  elif $package_mode; then
    echo '  FAIL RPM packaging needs rpm-build: sudo dnf install rpm-build'
    missing=1
  else
    echo '  INFO RPM packaging: install rpm-build, or use PACKAGE_ARGS=--appimage-only.'
  fi
  echo
  echo 'Optional desktop and document support (absence does not fail development checks):'
  if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
    echo '  OK   A graphical session is advertised; actual desktop launch still needs testing.'
  else
    echo '  INFO No graphical session detected. Unit/build checks work; GUI checks need a desktop/Xvfb.'
  fi
  if [[ -e /dev/fuse ]]; then
    echo '  OK   /dev/fuse exists; AppImage mount permission still depends on the host.'
  else
    echo '  INFO No /dev/fuse. Use the RPM or AppImage --appimage-extract-and-run.'
  fi
  for tool in libreoffice bwrap; do
    if command -v "$tool" >/dev/null 2>&1; then
      printf '  OK   %s is available for isolated Office rendering.\n' "$tool"
    else
      printf '  INFO %s is optional; native Office extraction remains available.\n' "$tool"
    fi
  done
  if command -v rpm >/dev/null 2>&1; then
    for package in gtk3 nss libXScrnSaver alsa-lib libXtst mesa-libgbm libsecret xdg-utils; do
      if ! rpm -q "$package" >/dev/null 2>&1; then
        printf '  INFO Desktop runtime package not installed: %s\n' "$package"
      fi
    done
  fi
  echo
  echo 'Use Node.js 24 LTS and pnpm 11.19.0 (the committed package-manager pin).'
  echo 'uv obtains the locked Python environment; system Python is not required.'
  echo 'Tool overrides: make UV=/path/to/uv PNPM=/path/to/pnpm NODE=/path/to/node <target>'
  echo 'Fedora guide and browser setup: docs/development.md'
  return "$missing"
}

case "${1:-}" in
  setup|setup-browser)
    require_tool "$uv_command"
    require_tool "$pnpm_command"
    require_tool "$node_command"
    "$uv_command" sync --locked
    "$pnpm_command" --dir frontend install --frozen-lockfile
    if [[ "$1" == setup ]]; then
      "$pnpm_command" --dir desktop install --frozen-lockfile
      "$pnpm_command" --dir desktop exec install-electron
    fi
    echo 'Dependencies ready. Start with make dev, or build with make build.'
    ;;
  build-web)
    require_tool "$uv_command"
    require_tool "$pnpm_command"
    "$pnpm_command" --dir frontend run build
    "$uv_command" run --locked python scripts/copy-web-assets.py
    ;;
  run)
    shift
    executable="$project_root/dist/desktop/linux-unpacked/anki-generator"
    if [[ ! -x "$executable" ]]; then
      echo 'No built desktop application found. Run make build first.' >&2
      exit 1
    fi
    unset ELECTRON_RUN_AS_NODE NODE_OPTIONS
    exec "$executable" "$@"
    ;;
  clean)
    # Fixed repository-relative allowlist. Never use XDG paths, data/, outputs/,
    # dependency environments, or desktop/build (which contains tracked metadata).
    for generated in build dist frontend/dist src/anki_generator/web_assets \
      .pytest_cache .ruff_cache frontend/test-results frontend/playwright-report \
      frontend/tsconfig.tsbuildinfo; do
      if [[ -e "$generated" || -L "$generated" ]]; then
        printf 'Removing generated output: %s\n' "$generated"
        rm -rf -- "$generated"
      fi
    done
    ;;
  doctor)
    shift
    doctor "$@"
    ;;
  *)
    echo 'Usage: scripts/workflow.sh {setup|setup-browser|build-web|run|clean|doctor}' >&2
    exit 2
    ;;
esac
