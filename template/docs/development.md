# Development

## Canonical environment

Develop from WSL/Linux. Recommended repository location: `~/src/{{ROOT_NAMESPACE_LOWER}}`.

Avoid putting the repository under `/mnt/c/...`. Windows remains the actual Valheim client runtime and is accessed through its WSL mount path.

## Local requirements

- WSL2 with a current Linux distribution
- Python 3
- .NET SDK
- local Windows Valheim installation for full plugin builds
- pinned BepInExPack installed in the development Valheim installation
- pinned Jötunn runtime installed in that development installation
- optional `ilspycmd` in WSL for assembly inspection
- Docker / Docker Compose when using the dedicated-server workflow

`Microsoft.NETFramework.ReferenceAssemblies` is included as a development-only package for the `net48` plugin projects so WSL does not depend on a Windows-installed .NET Framework targeting pack.

## Local configuration

Copy `Environment.props.example` to `Environment.props` and edit the WSL-visible Valheim path.

Copy `.valheim/dev.json.example` to `.valheim/dev.json` and edit development paths.

Both files are ignored by Git.

The Valheim install path in both files must agree. `./scripts/preflight.sh` validates this to prevent accidentally inspecting/building against one installation while deploying to another.

## Metadata workflow

Edit `suite.config.json`, then run:

```text
python3 scripts/suite_metadata.py sync
python3 scripts/suite_metadata.py check
```

Generated files must not be edited manually.

## Preflight

```text
./scripts/preflight.sh
```

Checks include WSL/tooling, metadata consistency, local config syntax, Valheim managed assembly presence, BepInEx, recursive Jötunn discovery, and configured development paths.

Portable repository-only mode:

```text
./scripts/preflight.sh --portable
```

## Jötunn publicized assemblies

`DoPrebuild.props` defaults to false. This prevents an incidental bootstrap/test command from generating files inside the configured Valheim install.

For the first full plugin build, if `valheim_Data/Managed/publicized_assemblies` is absent, enable `ExecutePrebuild=true` deliberately after confirming the correct development `VALHEIM_INSTALL` path. Jötunn can then generate and reference the required publicized dependencies.

## Canonical scripts

```text
./scripts/preflight.sh
./scripts/bootstrap.sh
./scripts/build.sh
./scripts/test.sh
./scripts/deploy-client.sh
./scripts/deploy-server.sh
./scripts/check-game-update.sh
./scripts/package.sh
```

Deployment is implemented once in `scripts/deploy.py` and uses module membership from `suite.config.json`.
