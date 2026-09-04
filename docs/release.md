# Release

## Local/test release packages

`./scripts/package.sh` performs a Release build and generates deterministic local ZIPs plus `SHA256SUMS` under `artifacts/packages/`.

Package membership comes from `suite.config.json`, not filename globs.

Current generated package families:

- ServerCore
- Client
- one ZIP per Shared Module
- ServerPack
- ClientPack

The ZIP layout installs DLLs under `BepInEx/plugins/<SuiteName>/` and includes `package-info.json`, README, and changelog.

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
