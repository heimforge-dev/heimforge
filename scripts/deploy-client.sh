#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
configuration="${1:-Debug}"
exec python3 scripts/deploy.py --target client --configuration "$configuration"
