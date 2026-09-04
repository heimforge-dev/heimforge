# Project

## Purpose

Build a modular Valheim mod suite for a dedicated private server while preserving clean client/server boundaries.

## Runtime packages

- `ValheimSuite.ServerCore`: server-only gameplay and administration features.
- `ValheimSuite.Shared.*`: independent two-sided modules with their own compatibility requirements.
- `ValheimSuite.Client`: client-only UI, visual, input, and convenience features.
- `ValheimSuite.Common`: shared pure code and protocol primitives.

## Development topology

Canonical development environment: **WSL/Linux**.

- repository, Git, OMP/Pi harness, dotnet, build/test/package scripts: WSL
- Windows Valheim client: accessed from WSL through `/mnt/c/...`
- dedicated test/server environment: Linux/Docker where possible
- Bash/WSL scripts define the only canonical project workflow
- `suite.config.json` is the authoritative suite/build/package metadata source

Keep the repository in the WSL filesystem, for example `~/src/valheim-mod-suite`, rather than under `/mnt/c`.

## Platform

- C#
- BepInExPack Valheim
- Jotunn
- Harmony when necessary
- dedicated server may run under Docker
- Windows PC clients are the primary client runtime

## Initial dependency pins

- Jotunn 2.29.2
- BepInExPack Valheim 5.4.2333
- plugin target: net48
- C# language version: 10
- Microsoft.NETFramework.ReferenceAssemblies 1.0.3 for cross-platform net48 targeting

## Initial milestones

0. Repository/harness scaffold.
1. Runtime plugin shells and side boundaries.
2. Shared Diagnostics CustomRPC proof.
3. Server-only AutoFeed feature.
4. Packaging/profile generation.
5. First real shared gameplay module.

## Non-goals initially

- custom launcher
- automatic updater/downloader
- web admin dashboard
- cloud service
- database server
- anti-cheat platform
- custom networking framework replacing Jotunn
- Unity asset project before custom assets are needed
