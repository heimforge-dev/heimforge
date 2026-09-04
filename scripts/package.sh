#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python3 scripts/suite_metadata.py check
./scripts/build.sh Release
exec python3 scripts/package.py --clean
