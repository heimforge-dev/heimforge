#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
bootstrap_validation="${SUITE_BOOTSTRAP_VALIDATION:-}"
unset SUITE_BOOTSTRAP_VALIDATION
if [[ "$bootstrap_validation" != "1" ]]; then
  python3 scripts/suite_metadata.py check
  python3 -m unittest discover -s tests/scaffold -p 'test_*.py' -v
fi
command -v dotnet >/dev/null || { echo "dotnet SDK is required for C# unit tests." >&2; exit 1; }
common_tests_csproj="$(python3 -c 'import json,pathlib; ns=json.loads(pathlib.Path("suite.identity.lock.json").read_text())["rootNamespace"]; print(f"tests/{ns}.Common.Tests/{ns}.Common.Tests.csproj")')"
dotnet test "$common_tests_csproj"
