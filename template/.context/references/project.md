---
type: reference
---

# Project

## Purpose

Build a modular Valheim mod suite for a dedicated private server while preserving clean client/server boundaries.

## Development topology

Canonical development environment: **WSL/Linux**.

- repository, Git, OMP/Pi harness, dotnet, build/test/package scripts: WSL
- Windows Valheim client: accessed from WSL through `/mnt/c/...`
- dedicated test/server environment: Linux/Docker where possible
- Bash/WSL scripts define the only canonical project workflow
- `scripts/deploy.py` is the single deployment implementation used by the Bash wrappers and OMP extension

Keep the repository in the WSL filesystem, for example `~/src/{{ROOT_NAMESPACE_LOWER}}`, rather than under `/mnt/c`.

## Metadata authority

- `suite.config.json` is the editable source of truth for supported mutable suite, project, package, and dependency metadata.
- `suite.identity.lock.json` locks generation-time `suiteName` and `rootNamespace`; changing either requires regeneration.
- The `projects` map and canonical solution membership must change together.
- After editing supported metadata, run `python3 scripts/suite_metadata.py sync` and commit its generated outputs with the source edit.
- Never manually edit `build/Suite.Generated.props`, `SuiteConstants.Generated.cs`, `packaging/profile-lock.json`, or `suite.identity.lock.json`.
- Deployment side classification belongs to `scripts/deploy.py` and `suite.config.json`; do not duplicate it.

## Platform and dependencies

- C#
- BepInExPack Valheim
- Jotunn
- Harmony only when necessary
- dedicated server under Docker where practical
- Windows PC clients as the primary client runtime

Exact dependency versions and C# language version are authoritative in `suite.config.json` and synchronized into `build/Suite.Generated.props`. Do not copy their values into prose. Record the reason for every new dependency in `docs/dependencies.md`.

## Working discipline

- Keep changes minimal and scoped. YAGNI applies.
- Introduce an abstraction only when a concrete consumer needs it.
- Do not duplicate globally configured Context Mode or Context7 configuration in this repository without a project-specific requirement.
- Use native harness capabilities; do not create generic planner, reviewer, scout, or worker agents for this project.

## Initial non-goals

- custom launcher
- automatic updater/downloader
- web admin dashboard
- cloud service
- database server
- anti-cheat platform
- custom networking framework replacing Jotunn
- Unity asset project before custom assets are needed
