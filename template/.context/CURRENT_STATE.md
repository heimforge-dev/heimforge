Note: the module list below reflects the initial scaffold selection made when this repository was generated. `suite.config.json` plus the canonical `.sln` remain the machine-validated current structural authority; if a later structural edit adds or removes a project, update this document by hand.

## Working

- {{SUITE_NAME}} generated from ValheimSuite Bootstrap.
{{INCLUDED_MODULES_LIST}}
- `suite.config.json` is the editable source of truth for supported mutable suite/project/package metadata; generation-time suite identity is locked in `suite.identity.lock.json`.
- Generated MSBuild/C# package metadata is synchronized and validated.
- Cross-platform `net48` reference assemblies are explicitly declared.
- Metadata-driven deployment prevents client/server DLL cross-contamination.
- Deterministic local package generation and SHA-256 checksums are implemented.
- Portable scaffold tests cover repository invariants.

## In Progress

- Local WSL/Valheim environment verification.
- First successful full plugin build against installed Valheim/Jötunn.
- OMP extension load verification against the user's installed OMP version.

## Next

1. Configure `Environment.props` and `.valheim/dev.json`.
2. Run `./scripts/preflight.sh`.
3. Run `./scripts/bootstrap.sh`.
4. If publicized assemblies are absent, deliberately enable Jötunn prebuild for the development Valheim install.
5. Run `./scripts/build.sh Debug`.
6. Load OMP and verify the `valheim-dev` extension/tools.
7. Design and implement the first real feature using `docs/features/TEMPLATE.md`.

## Known Issues / Deliberate Incompleteness

- Installed Valheim version is not yet recorded.
- Runtime-side detection code must be verified against current APIs before feature activation.
- Public Thunderstore manifests/assets are not generated yet. Local deterministic ZIP packaging is implemented.

## Last Verified

Valheim: UNVERIFIED LOCALLY
BepInExPack / Jötunn / Microsoft.NETFramework.ReferenceAssemblies: pins tracked in `suite.config.json`, not duplicated here
Repository scaffold tests: PASS at generation time
{{CURRENT_STATE_BUILD_STATUS_LINES}}
