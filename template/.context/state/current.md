---
type: state
---

# Current state

The module list below is the initial scaffold snapshot. For current project membership and metadata update rules, follow `../references/project.md`.

## Generated baseline

{{INCLUDED_MODULES_LIST}}

## Working

- {{SUITE_NAME}} generated from HeimForge.
- Generated MSBuild and C# package metadata is synchronized and validated.
- Cross-platform `net48` reference assemblies are explicitly declared.
- Metadata-driven deployment prevents client/server DLL cross-contamination.
- Deterministic local package generation and SHA-256 checksums are implemented.
- Portable scaffold tests cover repository invariants.
- Portable agent instructions and project skills are available through `AGENTS.md` and `.agents/skills/`.

## In progress

- Local WSL/Valheim environment verification.
- First successful full plugin build against installed Valheim/Jotunn.

## Next

1. Configure `Environment.props` and `.valheim/dev.json`.
2. Run `./scripts/preflight.sh`.
3. Run `./scripts/bootstrap.sh`.
4. If publicized Valheim references are absent, run `python3 scripts/update-game-stack.py refresh` after verifying `VALHEIM_INSTALL`; this refreshes references, builds, and runs preflight.
5. Otherwise run `./scripts/build.sh Debug` for an ordinary parallel build.
6. Design and implement the first real feature using `docs/features/TEMPLATE.md`.

## Initial milestones

{{INITIAL_MILESTONES_LIST}}

## Unverified or pending

- Installed Valheim version is not yet recorded.
- Runtime gameplay behavior and multiplayer compatibility still require verification on the user's installation.
- Public Thunderstore manifests and assets are not generated yet. Local deterministic ZIP packaging is implemented.

## Last verified

- Valheim: UNVERIFIED LOCALLY
- Repository scaffold tests: PASS at generation time
{{CURRENT_STATE_BUILD_STATUS_LINES}}
