# Source before launching development tools. Child build tools also invoke node/pnpm
# by name, so explicit executable overrides must be visible in their PATH.
for selected_tool in "${UV:-uv}" "${PNPM:-pnpm}" "${NODE:-node}"; do
  selected_path="$(command -v "$selected_tool" 2>/dev/null || true)"
  if [[ "$selected_path" == */* ]]; then
    selected_directory="$(cd -- "$(dirname -- "$selected_path")" && pwd)"
    export PATH="$selected_directory:$PATH"
  fi
done
unset selected_tool selected_path selected_directory
