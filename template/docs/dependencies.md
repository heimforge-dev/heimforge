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
