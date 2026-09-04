# WSL Bootstrap Hardening V3

This hardening pass intentionally preserves the established runtime architecture and compatibility policy while reducing scaffold-level failure modes.

## Preserved unchanged

- Common / ServerCore / independent Shared modules / Client topology
- server-authoritative networking principles
- Jötunn as the primary integration/network platform
- no ServerSync without a concrete need
- ServerCore `NotEnforced / None`
- Client `NotEnforced / None`
- Shared.Diagnostics `VersionCheckOnly / Minor`
- WSL-first development topology
- local assembly inspection before Harmony/game-internal assumptions
- disposable-world and no-production-auto-deploy policies

## Hardened

- `suite.config.json` is now the single authoritative metadata/project/package map.
- Generated MSBuild properties, C# suite constants, and package lock are synchronized and checked.
- Linux/WSL `net48` builds explicitly reference `Microsoft.NETFramework.ReferenceAssemblies` as a private build dependency.
- Preflight now validates local config, path agreement, Valheim assembly presence, BepInEx, recursively located Jötunn, tooling, and Jötunn prebuild/publicized-reference state.
- Client/server development deployment uses one Python implementation shared by Bash and OMP.
- Deployment uses exact configured projects/TFMs instead of broad DLL globs and removes stale suite DLLs from the dedicated suite destination.
- OMP assembly inspection is restricted to `valheim_Data/Managed`.
- OMP server logging no longer permits arbitrary configured commands.
- OMP subprocess execution is cancellable and uses argument arrays.
- Release packaging is implemented, deterministic, metadata-driven, and checksum-producing.
- Public-release metadata has a deliberate fail-closed validation mode.
- Standard-library scaffold tests protect high-confidence architectural invariants from accidental regressions.

## Still requires environment/runtime proof

- full plugin build against the user's actual Valheim/Jötunn installation
- Jötunn publicized-reference generation on the user's WSL/Windows setup
- OMP extension loading/type compatibility against the installed OMP package
- Valheim dedicated-server plugin load
- client/server connection matrix
- Shared Diagnostics CustomRPC behavior
- AutoFeed implementation and game-internal assumptions

No static scaffold can honestly guarantee those runtime facts before executing in the real environment.
