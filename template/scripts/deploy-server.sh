#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
configuration="Debug"
if [[ $# -gt 0 && "$1" != --* ]]; then
  configuration="$1"
  shift
fi
exec python3 scripts/deploy.py --target server --configuration "$configuration" "$@"
