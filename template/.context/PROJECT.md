# Project

## Purpose

Build a modular Valheim mod suite for a dedicated private server while preserving clean client/server boundaries.

## Runtime packages

Initial generated module selection (bootstrap-time snapshot); `suite.config.json` plus the canonical `.sln` remain the machine-validated current structural authority. Update this list by hand after a later structural edit.

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

{{INITIAL_MILESTONES_LIST}}

## Non-goals initially

- custom launcher
- automatic updater/downloader
- web admin dashboard
- cloud service
- database server
- anti-cheat platform
- custom networking framework replacing Jotunn
- Unity asset project before custom assets are needed
