# Project

## Purpose

Build a modular Valheim mod suite for a dedicated private server while preserving clean client/server boundaries.

## Runtime packages

{{INCLUDED_MODULES_LIST}}

## Development topology

Canonical development environment: **WSL/Linux**.

- repository, Git, OMP/Pi harness, dotnet, build/test/package scripts: WSL
- Windows Valheim client: accessed from WSL through `/mnt/c/...`
- dedicated test/server environment: Linux/Docker where possible
- Bash/WSL scripts define the only canonical project workflow
- `suite.config.json` is the editable source of truth for supported mutable suite/project/package metadata; generation-time suite identity (`suiteName`, `rootNamespace`) is locked in `suite.identity.lock.json`

Keep the repository in the WSL filesystem, for example `~/src/valheim-mod-suite`, rather than under `/mnt/c`.

## Platform

- C#
- BepInExPack Valheim
- Jotunn
- Harmony when necessary
- dedicated server may run under Docker
- Windows PC clients are the primary client runtime

## Dependency pins

Exact current versions are authoritative in `suite.config.json` (synchronized into `build/Suite.Generated.props` by `scripts/suite_metadata.py sync`), not duplicated here:

- Jotunn: `jotunnVersion`
- BepInExPack Valheim: `bepInExPackVersion`
- plugin target: net48
- C# language version: `csharpLanguageVersion`
- Microsoft.NETFramework.ReferenceAssemblies: `netFrameworkReferenceAssembliesVersion`, for cross-platform net48 targeting

## Initial milestones

0. Repository/harness scaffold.
1. Runtime plugin shells and side boundaries.
2. Shared Diagnostics CustomRPC proof.
3. First real feature (see `docs/features/TEMPLATE.md`).
4. Packaging/profile generation.

## Non-goals initially

- custom launcher
- automatic updater/downloader
- web admin dashboard
- cloud service
- database server
- anti-cheat platform
- custom networking framework replacing Jotunn
- Unity asset project before custom assets are needed
