#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
portable=0
build=0
for arg in "$@"; do
  case "$arg" in
    --portable) portable=1 ;;
    --build) build=1 ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [[ $portable -eq 1 ]]; then
  ./scripts/preflight.sh --portable
else
  ./scripts/preflight.sh
fi

./scripts/test.sh

if [[ $build -eq 1 ]]; then
  ./scripts/build.sh Debug
fi

echo "Bootstrap validation completed."
if [[ $build -eq 0 ]]; then
  echo "Run ./scripts/build.sh Debug when local Jotunn/game references are ready, or rerun bootstrap with --build."
fi
