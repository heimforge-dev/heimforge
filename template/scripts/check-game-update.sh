#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

if ! preflight="$(python3 scripts/preflight.py --json)"; then
  python3 -c 'import json, sys; print("preflight error: {}".format(json.load(sys.stdin)["error"]), file=sys.stderr)' <<<"$preflight"
  exit 2
fi
valheim_dir="$(python3 -c 'import json, sys; print(json.load(sys.stdin)["checks"]["environmentValheimInstall"])' <<<"$preflight")"
assembly="$(python3 -c 'import json, sys; print(json.load(sys.stdin)["checks"]["gameAssembly"])' <<<"$preflight")"

printf 'Valheim directory: %s\n' "$valheim_dir"
printf 'Gameplay assembly: %s\n' "$assembly"
sha256sum "$assembly"

echo
echo "Harmony targets requiring revalidation:"
if [[ -f docs/patch-ledger.md ]]; then
  grep -nE '^## |^Feature:|^Target ' docs/patch-ledger.md || true
else
  echo "No patch ledger found."
fi
