# Release

## Local/test release packages

`./scripts/package.sh` performs a Release build and generates deterministic local ZIPs plus `SHA256SUMS` under `artifacts/packages/`.

Package membership comes from `suite.config.json`, not filename globs.

Current generated package families:

{{RELEASE_PACKAGE_FAMILIES_LIST}}

The ZIP layout installs DLLs under `BepInEx/plugins/<SuiteName>/` and includes `package-info.json`, README, and changelog.

## Evaluated artifact contract

Metadata `check` and `sync`, packaging, deployment, and preflight (including
`--portable`) require a .NET SDK. For Debug and Release, the trusted metadata
script evaluates each canonical project with MSBuild's structured property API:

```text
dotnet msbuild src/<Project>/<Project>.csproj -nologo -getProperty:<contract-properties> -property:<solution-global>=<value> ...
```

The supplied globals are the complete set empirically observed on child
projects during the canonical solution build: `Configuration`, `Platform`,
`BuildingSolutionFile`, `SolutionDir`, `SolutionPath`, `SolutionName`,
`SolutionFileName`, `SolutionExt`, and
`CurrentSolutionConfigurationContents`. The latter is derived from the already
validated canonical solution entries and Debug/Release Any CPU mappings.
Validation also compares every returned global against that expected context.

MSBuild—not project code—produces the structured JSON. Certification executes
no project target and exposes no report destination or secret to evaluated
projects. Project bodies, imported props/targets, project target definitions,
and project-written report files are untrusted; they cannot replace the
external `-getProperty` producer. The trusted inputs are the metadata script,
suite metadata, and canonical solution structure after their existing
validation.

Every configured project must evaluate with its canonical path,
`Platform=AnyCPU`, `BuildingSolutionFile=true`, `AssemblyName` equal to its
project name, and `TargetFramework` equal to `netstandard2.0` for Common or
`net48` for every runtime scope. Evaluation does not restore, compile, resolve
references, or require Valheim/BepInEx/Jötunn assemblies. A missing SDK,
evaluation failure/timeout, malformed structured output, missing/unexpected
property, or mismatch fails closed before package cleanup or deployment
transactions.

`suite_metadata.py check --structural-only` and `sync --structural-only` are
bootstrap/scaffold operations, **not artifact certification**. They preserve
no-dotnet generation and allow the initial generated props to be written before
MSBuild can import them. Package/deploy never use this option. Do not substitute
it for the full check when preparing artifacts.

## Public release gate

Before preparing a public Thunderstore release:

```text
python3 scripts/suite_metadata.py check --release
```

This must fail while placeholder branding remains.

Public publication additionally requires final:

- suite name
- plugin GUID root
- author
- Thunderstore namespace
- license
- package descriptions/icons
- public manifests/profile metadata

Do not treat local ZIP generation as proof of runtime compatibility.

## Runtime release checklist

1. Update `suite.config.json` suite version.
2. Run `python3 scripts/suite_metadata.py sync`.
3. Update protocol/schema versions where required.
4. Run scaffold and C# unit tests.
5. Build against the current installed Valheim version.
6. Run disposable-server smoke test.
7. Run multiplayer checks for changed shared modules.
8. Verify config generation.
9. Review patch ledger.
10. Review persistent-state migrations.
11. Update changelog and current state.
12. Generate packages and checksums.
13. Test generated artifacts in clean development profiles.
14. Tag only after the clean-profile test passes.

Never package game assemblies, `Environment.props`, `.valheim/dev.json`, production configs, credentials, or world saves.
