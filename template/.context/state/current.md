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

## In progress

- Local WSL/Valheim environment verification.
- First successful full plugin build against installed Valheim/Jotunn.
- OMP extension load verification against the user's installed OMP version.

## Next

1. Configure `Environment.props` and `.valheim/dev.json`.
2. Run `./scripts/preflight.sh`.
3. Run `./scripts/bootstrap.sh`.
4. If publicized assemblies are absent, deliberately enable Jotunn prebuild for the development Valheim install.
5. Run `./scripts/build.sh Debug`.
6. Load OMP and verify the `valheim-dev` extension and tools.
7. Design and implement the first real feature using `docs/features/TEMPLATE.md`.

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
