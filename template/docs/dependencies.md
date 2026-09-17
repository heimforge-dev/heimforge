# Dependencies

## BepInExPack Valheim

- Pin: `suite.config.json`'s `bepInExPackVersion` (synchronized into `build/Suite.Generated.props`)
- Runtime side: server and any modded client
- Purpose: Valheim BepInEx runtime pack

## Jötunn

- NuGet package: `JotunnLib`
- Pin: `suite.config.json`'s `jotunnVersion` (synchronized into `build/Suite.Generated.props`)
- Runtime side: any side loading a suite plugin
- Purpose: compatibility enforcement, synchronization, CustomRPCs, commands, events, prefab/game integration, development prebuild support
- Why needed: establishes the common Valheim modding platform and avoids duplicating networking/synchronization infrastructure

## Game-stack maintenance

Run `python3 scripts/update-game-stack.py check` to compare the authoritative pins with locally discoverable development-profile versions without mutating files or using the network.

`apply --jotunn <SemVer>` and/or `--bepinex <SemVer>` changes only the explicitly supplied pin(s) in `suite.config.json` and synchronizes generated metadata; an explicit Jötunn pin change also refreshes Jötunn's publicized references, then `apply` runs the normal build and preflight. If metadata synchronization itself fails, `suite.config.json` is restored; if a later step (reference refresh, build, or preflight) fails after synchronization succeeded, the synchronized pin and metadata changes remain applied. `apply` never installs packages into a Thunderstore profile, client, or server, and never deploys or restarts anything.

Use `python3 scripts/update-game-stack.py refresh` after a Valheim binary or reference update when pins remain unchanged; it refreshes references, builds, and runs preflight without touching pins. Follow it with `./scripts/check-game-update.sh` for the separate assembly fingerprint and Harmony-target revalidation.

A pin is project metadata, not an installer: changing it does not update an existing Thunderstore profile, a client, or a remote server runtime. Match installed runtime versions separately, deploy explicitly, and complete the multiplayer smoke test after a compatibility update.

## Microsoft.NETFramework.ReferenceAssemblies

- Pin: `suite.config.json`'s `netFrameworkReferenceAssembliesVersion` (synchronized into `build/Suite.Generated.props`)
- Development/build only, `PrivateAssets=all`
- Applies to `net48` runtime plugin projects
- Purpose: provide .NET Framework reference assemblies to SDK-style builds on WSL/Linux without requiring a Windows targeting pack
- Must never be packaged as a runtime Valheim dependency

## ServerSync

- Status: intentionally not included
- Add only if a concrete requirement cannot be handled cleanly through Jötunn.

## Test dependencies

- Microsoft.NET.Test.Sdk
- xUnit
- xUnit Visual Studio runner

These are development-only and may be adjusted independently from runtime dependencies.

## Dependency rule

Any new runtime dependency must document version, purpose, runtime side, license, why built-in/Jötunn functionality is insufficient, and removal cost.
