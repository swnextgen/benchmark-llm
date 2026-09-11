#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
VENV="$ROOT/benchmark/.venv"
STATE="$ROOT/benchmark/.state"

mapfile -t swe_images < <(
  docker image ls --format '{{.Repository}}:{{.Tag}}' |
    awk '/^(docker\.io\/)?swebench\/sweb\.eval\./ { print }'
)
if (( ${#swe_images[@]} )); then
  docker image rm -f "${swe_images[@]}"
fi

if [[ -x "$VENV/bin/harbor" ]]; then
  XDG_CACHE_HOME="$STATE/cache" "$VENV/bin/harbor" cache clean -f
fi

echo "Benchmark Docker image cache removed."
