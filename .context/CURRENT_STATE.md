# Current State

## Working

- WSL-first bootstrap package generated and hardened.
- ServerCore / Shared / Client architecture preserved.
- Jötunn/BepInEx compatibility model preserved.
- `suite.config.json` is the authoritative metadata/package map.
- Generated MSBuild/C# package metadata is synchronized and validated.
- Cross-platform `net48` reference assemblies are explicitly declared.
- Metadata-driven deployment prevents client/server DLL cross-contamination.
- Deterministic local package generation and SHA-256 checksums are implemented.
- OMP extension no longer accepts an arbitrary configured log command.
- Portable scaffold tests cover repository invariants.

## In Progress

- Local WSL/Valheim environment verification.
- First successful full plugin build against installed Valheim/Jötunn.
- OMP extension load verification against the user's installed OMP version.
- Shared Diagnostics RPC.

## Next

1. Configure `Environment.props` and `.valheim/dev.json`.
2. Run `./scripts/preflight.sh`.
3. Run `./scripts/bootstrap.sh`.
4. If publicized assemblies are absent, deliberately enable Jötunn prebuild for the development Valheim install.
5. Run `./scripts/build.sh Debug`.
6. Load OMP and verify the `valheim-dev` extension/tools.
7. Implement and smoke-test Shared Diagnostics.
8. Begin AutoFeed reverse engineering only after the architecture is proven at runtime.

## Known Issues / Deliberate Incompleteness

- Working codename and plugin GUID root are placeholders.
- Installed Valheim version is not yet recorded.
- Runtime-side detection code must be verified against current APIs before feature activation.
- Shared Diagnostics CustomRPC is intentionally not implemented before exact runtime/API verification.
- Public Thunderstore manifests/assets are not generated yet. Local deterministic ZIP packaging is implemented.

## Last Verified

Valheim: UNVERIFIED LOCALLY
BepInExPack: 5.4.2333 pin
Jötunn: 2.29.2 pin
Microsoft.NETFramework.ReferenceAssemblies: 1.0.3 pin
Repository scaffold tests: PASS at package generation
Server build: NOT RUN IN USER ENVIRONMENT
Client build: NOT RUN IN USER ENVIRONMENT
