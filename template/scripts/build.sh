#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
configuration="${1:-Debug}"
case "$configuration" in Debug|Release) ;; *) echo "Configuration must be Debug or Release" >&2; exit 2;; esac
python3 scripts/suite_metadata.py check
solution="$(python3 -c 'import json,pathlib; print(json.loads(pathlib.Path("suite.identity.lock.json").read_text())["rootNamespace"] + ".sln")')"
dotnet build "$solution" -c "$configuration"
