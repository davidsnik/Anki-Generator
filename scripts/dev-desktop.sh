#!/usr/bin/env bash
# Run the desktop shell against source Python and production frontend assets.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
hmr=false
shell_arguments=()
for argument in "$@"; do
  case "$argument" in
    --hmr) hmr=true ;;
    --help)
      echo "Usage: ./scripts/dev-desktop.sh [--hmr] [desktop options]"
      echo "--hmr owns a strict-port Vite server at http://127.0.0.1:5173."
      exit 0 ;;
    *) shell_arguments+=("$argument") ;;
  esac
done
for tool in uv node pnpm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Development requirement missing: $tool. See docs/desktop.md." >&2
    exit 1
  fi
done
uv sync --locked
pnpm --dir frontend install --frozen-lockfile
pnpm --dir desktop install --frozen-lockfile
pnpm --dir desktop exec install-electron
pnpm --dir frontend run build
python_command="$(uv run --no-sync python -c 'import sys; print(sys.executable)')"
# Editors may themselves be Electron processes and export Node-only startup flags.
unset ELECTRON_RUN_AS_NODE NODE_OPTIONS
electron_command="$(node -p 'require("./desktop/node_modules/electron")')"
if ! $hmr; then
  exec "$electron_command" "$project_root/desktop" --backend-command "$python_command" \
    --backend-arg=-m --backend-arg=anki_generator.desktop "${shell_arguments[@]}"
fi

# Fail on an occupied development port rather than attaching to another service.
node - <<'JS'
const net = require('node:net');
const server = net.createServer();
server.once('error', () => {
  console.error('Development port 5173 is occupied; stop that server before using --hmr.');
  process.exit(1);
});
server.listen(5173, '127.0.0.1', () => server.close());
JS
frontend_pid=''
desktop_pid=''
cleanup() {
  for child in "$desktop_pid" "$frontend_pid"; do
    if [[ -n "$child" ]]; then
      kill -TERM "$child" 2>/dev/null || true
      wait "$child" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
node "$project_root/frontend/node_modules/vite/bin/vite.js" "$project_root/frontend" \
  --host 127.0.0.1 --port 5173 --strictPort &
frontend_pid=$!
node --input-type=module - "$frontend_pid" <<'JS'
const pid = Number(process.argv[2]);
const deadline = Date.now() + 30_000;
while (Date.now() < deadline) {
  try {
    process.kill(pid, 0);
    const response = await fetch('http://127.0.0.1:5173', { signal: AbortSignal.timeout(1000) });
    if (response.ok && (await response.text()).includes('/@vite/client')) process.exit(0);
  } catch (error) {
    if (error.code === 'ESRCH') throw new Error('Vite stopped before becoming ready.');
  }
  await new Promise(resolve => setTimeout(resolve, 100));
}
throw new Error('Vite did not become ready within 30 seconds.');
JS
"$electron_command" "$project_root/desktop" --backend-command "$python_command" \
  --backend-arg=-m --backend-arg=anki_generator.desktop \
  --frontend-url http://127.0.0.1:5173 "${shell_arguments[@]}" &
desktop_pid=$!
wait "$desktop_pid"
