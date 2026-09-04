#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python3 scripts/preflight.py >/dev/null
valheim_dir="$(python3 - <<'PY'
import json
from pathlib import Path
cfg=json.loads(Path('.valheim/dev.json').read_text())
print(cfg['valheimInstall'])
PY
)"
assembly="$valheim_dir/valheim_Data/Managed/Assembly-CSharp.dll"

printf 'Valheim directory: %s\n' "$valheim_dir"
printf 'Assembly-CSharp: %s\n' "$assembly"
sha256sum "$assembly"

echo
echo "Harmony targets requiring revalidation:"
if [[ -f docs/patch-ledger.md ]]; then
  grep -nE '^## |^Feature:|^Target ' docs/patch-ledger.md || true
else
  echo "No patch ledger found."
fi
