# Changelog

## 0.1.0 - Unreleased

### Architecture

- Initial modular suite scaffold.
- Server Core, Client, Common, and Shared Diagnostics project shells.
- Preserved per-module Jötunn compatibility boundaries.

### Harness

- OMP project context, domain skills, extension, and bootstrap prompt.
- WSL-first canonical workflow.

### Hardening

- Added `suite.config.json` as authoritative build/package metadata with generated consistency-checked outputs.
- Added WSL/local-environment preflight validation.
- Added private `Microsoft.NETFramework.ReferenceAssemblies` dependency for cross-platform `net48` builds.
- Centralized client/server deployment classification in metadata-driven `scripts/deploy.py`.
- Added stale suite-DLL cleanup during development deployment.
- Hardened OMP assembly inspection and server log handling.
- Replaced placeholder packaging with deterministic local ZIPs and SHA-256 checksums.
- Added repository scaffold regression tests.
- Added explicit public-release metadata gate.
- Certify generated project TargetFramework/AssemblyName through structured, evaluation-only MSBuild property queries in the canonical Debug/Release solution context. The trusted metadata script derives and verifies every solution global; project targets/imports cannot forge an artifact report or ship stale canonical-path artifacts. Preserve explicitly non-certifying structural bootstrap operations without dotnet.

### Bootstrapper

- Converted the fixed ValheimSuite v3 scaffold into a generic ValheimSuite Bootstrap generator (`bootstrap/` + `template/` + `tests/{bootstrap,template,fixtures}` + `scripts/create-project.sh`/`validate-template.sh`).
- Generated the standalone Vibeheim project as the first dogfood output.
