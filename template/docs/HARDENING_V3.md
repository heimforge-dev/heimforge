# WSL Bootstrap Hardening V3

This hardening pass intentionally preserves the established runtime architecture and compatibility policy while reducing scaffold-level failure modes.

## Preserved unchanged

- Common / ServerCore / independent Shared modules / Client topology
- server-authoritative networking principles
- Jötunn as the primary integration/network platform
- no ServerSync without a concrete need
{{COMPATIBILITY_BOUNDARIES_LIST}}
- WSL-first development topology
- local assembly inspection before Harmony/game-internal assumptions
- disposable-world and no-production-auto-deploy policies

## Hardened

- `suite.config.json` is now the editable source of truth for supported mutable suite/project/package metadata; generation-time suite identity (`suiteName`, `rootNamespace`) is locked in `suite.identity.lock.json` and rejected if edited.
- Generated MSBuild properties, C# suite constants, and package lock are synchronized and checked.
- Linux/WSL `net48` builds explicitly reference `Microsoft.NETFramework.ReferenceAssemblies` as a private build dependency.
- Preflight now validates local config, path agreement, Valheim assembly presence, BepInEx, recursively located Jötunn, tooling, and Jötunn prebuild/publicized-reference state.
- Client/server development deployment uses one canonical Python implementation behind the Bash wrappers; optional agent adapters delegate to it.
- Deployment uses exact configured projects/TFMs instead of broad DLL globs and removes stale suite DLLs from the dedicated suite destination.
- Canonical assembly-inspection and server-runtime scripts retain their confinement and fixed-operation boundaries independently of any optional agent adapter.
- Release packaging is implemented, deterministic, metadata-driven, and checksum-producing.
- Public-release metadata has a deliberate fail-closed validation mode.
- Standard-library scaffold tests protect high-confidence architectural invariants from accidental regressions.

## Still requires environment/runtime proof

{{HARDENING_PENDING_PROOF_LIST}}

No static scaffold can honestly guarantee those runtime facts before executing in the real environment.
