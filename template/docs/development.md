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
- Docker when using the optional Docker server lifecycle

`Microsoft.NETFramework.ReferenceAssemblies` is included as a development-only package for the `net48` plugin projects so WSL does not depend on a Windows-installed .NET Framework targeting pack.

## Local configuration

Copy `Environment.props.example` to `Environment.props` and edit the WSL-visible Valheim path.

Copy `.valheim/dev.json.example` to `.valheim/dev.json` and edit development paths.

Both files are ignored by Git.

The Valheim install path in both files must agree. `./scripts/preflight.sh` validates this to prevent accidentally inspecting/building against one installation while deploying to another.

## Runtime debug logging

Every generated runtime plugin binds its own BepInEx configuration entry:

```text
[Development]
DebugLogging = false
```

The setting is local to that plugin. Enabling Client diagnostics does not enable ServerCore or Shared.Diagnostics diagnostics, and the value is not synchronized or sent over the network.

Use the plugin's `RuntimeDiagnostics` instance for development-time, feature-local events. It writes through that plugin's existing BepInEx logger with the filterable format `[RuntimeDebug] <event>: <details>`.

```csharp
diagnostics.Debug("first-person.requested", "enabled=true");
diagnostics.Debug("first-person.suspended", "reason=DebugFly");

if (diagnostics.Enabled)
{
    diagnostics.Debug(
        "first-person.camera",
        $"distance={distance} fov={fov} renderedFov={renderedFov} nearClip={nearClip}");
}
```

Log meaningful transitions or changed values, not per-frame polling. In hot loops, check `Enabled` before interpolation so disabled diagnostics do not allocate payload strings. Feature implementations own event names, timing, payload values, and the choice of relevant transitions.

Never log credentials, authentication material, secrets, production configuration, world-save contents, or unnecessary player-identifying information.

This primitive is for local feature diagnostics. `Shared.Diagnostics` remains an independent plugin for shared/network diagnostic behavior; Client and ServerCore do not depend on it for logging.

## Server deployment

Server artifact planning, deployment transport, and lifecycle control are separate concerns:

```text
suite metadata -> server DeploymentPlan -> local or SSH deployment
                                      \-> none or Docker lifecycle
```

Changing transport never changes which modules enter the server plan. The local and SSH backends receive the same exact metadata-derived DLL list.

### Local transport

The generated schema-v2 example uses a local suite-specific destination:

```json
{
  "server": {
    "deployment": {
      "type": "local",
      "pluginDir": "/home/user/valheim-dev/BepInEx/plugins/SampleSuite"
    },
    "lifecycle": {
      "type": "none"
    }
  }
}
```

Local deployment retains the directory-FD locking, no-follow writes, atomic file replacement, ownership manifest, stale-owned-file cleanup, and durability checks implemented by `scripts/deploy.py`.

### SSH transport

Use an SSH config alias as `host`. User names, addresses, ports, keys, agents, and jump hosts belong in `~/.ssh/config`, not `.valheim/dev.json`. Password, private-key, and private-key-content fields are rejected.

```json
{
  "server": {
    "deployment": {
      "type": "ssh",
      "host": "gameserver",
      "remotePlatform": "posix",
      "pluginDir": "/srv/valheim/BepInEx/plugins/SampleSuite"
    },
    "lifecycle": {
      "type": "docker",
      "container": "valheim-server"
    }
  }
}
```

`remotePlatform` accepts `auto`, `posix`, or `windows` and defaults to `auto`. Set it explicitly when probing is unavailable or ambiguous. Windows drive paths use a form such as `D:/Servers/Valheim/BepInEx/plugins/SampleSuite`.

The transport normally invokes OpenSSH-compatible `ssh` and `scp` from `PATH`. Uploads force `scp`'s SFTP protocol so configured path characters never cross the legacy SCP remote-shell parsing boundary. Environments that intentionally use different clients can set `sshExecutable` and `scpExecutable` inside `server.deployment`; these are executable paths or names, not authentication settings, and an `scpExecutable` override must support OpenSSH's `-s` option.

SSH deployment creates a unique sibling staging directory, uploads the exact plan and ownership manifest, verifies names and SHA-256 hashes, then promotes only suite-owned entries. Upload or verification failure leaves the live directory untouched; promotion attempts rollback from a unique sibling backup. Unrelated live files are preserved and only manifest-owned stale files are removed.

Generic SSH cannot reproduce the local backend's retained-directory-FD lock and inode binding across separate SSH/SCP processes. Remote scripts therefore reject non-canonical POSIX parents, symlinked destinations, Windows reparse points, unsafe roots, raw `BepInEx/plugins`, changed live manifests, and unexpected file types. POSIX bind mounts and other mount aliases are not comprehensively detectable, so a canonical-looking remote parent can still resolve elsewhere. Hash verification is point-in-time rather than inode-bound against another writer. Rollback is best-effort: a remote process or host failure that prevents rollback can leave partial live state, and remote promotion has no local-equivalent `fsync` durability guarantee. No subprocess timeout is imposed on remote operations; bound them with `~/.ssh/config` options such as `ConnectTimeout` and `ServerAliveInterval`. Restrict remote write access and do not run concurrent remote deployments to the same suite directory.

### Lifecycle

Deployment never restarts a server implicitly:

```bash
./scripts/deploy-server.sh Debug
./scripts/deploy-server.sh Debug --restart
```

`--restart` runs the configured lifecycle only after deployment succeeds. `type: "docker"` executes `docker restart` locally for local transport and through the configured SSH host for SSH transport. `type: "none"` has no restart operation. A lifecycle failure is reported separately after the successful deployment remains in place. Docker Compose is not assumed.

The OMP status and log tools delegate to `scripts/server_runtime.py`; the extension never constructs SSH or Docker commands. Schema-v2 Docker status/log operations run beside the configured container, locally or through SSH. `serverLogFile` remains a local bounded-tail source, and schema-v1 Docker Compose status/log behavior remains compatible.

### Schema-v1 compatibility

Existing schema-v1 files remain valid. `serverPluginDir` keeps its legacy local-deployment meaning; legacy Docker Compose/log fields remain available to legacy extension tools. To migrate, set `schemaVersion` to `2`, move `serverPluginDir` to `server.deployment.pluginDir`, select `server.deployment.type`, and add an independent `server.lifecycle` object.

## Metadata workflow

`suite.config.json` is the authoritative source for dependency pins. Use the game-stack workflow for Valheim, Jötunn, or BepInExPack maintenance instead of editing generated metadata:

```bash
python3 scripts/update-game-stack.py check
python3 scripts/update-game-stack.py apply \
  --jotunn <version> \
  --bepinex <version>
```

`check` is offline and non-destructive: it reports pins, locally discoverable development-profile versions, drift, and publicized-assembly state. `apply` accepts only explicitly supplied SemVer pins, synchronizes generated metadata, refreshes references for an explicit Jötunn update, runs the normal build and preflight, but never deploys or restarts a server. For a Valheim binary update without changing pins, run `python3 scripts/update-game-stack.py refresh`, then `./scripts/check-game-update.sh`; the former refreshes/builds references, while the latter fingerprints the resolved gameplay assembly (`assembly_valheim.dll`, with `Assembly-CSharp.dll` fallback for older layouts) and lists Harmony targets that require manual semantic revalidation. The checker does not validate patch semantics; inspect the current assembly before treating any Harmony target as revalidated. A successful build or checker run does not prove Harmony patches remain valid. Remote/server runtime is not inspected. Run `scripts/suite_metadata.py sync` directly only for other supported metadata edits.

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

`./scripts/refresh-references.sh` is the deliberate reference-refresh operation. It validates metadata and performs Jötunn prebuild with one MSBuild worker because Jötunn writes a shared `publicized_assemblies` output. This serialization applies only to the refresh; ordinary `./scripts/build.sh` builds remain parallel.

Run `python3 scripts/update-game-stack.py apply --jotunn <version>` after an explicit Jötunn pin update. After a Valheim update, run `python3 scripts/update-game-stack.py refresh` and then `./scripts/check-game-update.sh`; the refresh does not change dependency pins, and the checker separately fingerprints the resolved game binary and lists Harmony targets that still require semantic revalidation against the current assembly.

## Canonical scripts

```text
./scripts/preflight.sh
./scripts/bootstrap.sh
./scripts/build.sh
./scripts/refresh-references.sh
python3 scripts/update-game-stack.py check
python3 scripts/update-game-stack.py refresh
python3 scripts/update-game-stack.py apply --jotunn <version> [--bepinex <version>]
./scripts/test.sh
./scripts/deploy-client.sh
./scripts/deploy-server.sh
./scripts/check-game-update.sh
./scripts/package.sh
```

Deployment is implemented once in `scripts/deploy.py` and uses module membership from `suite.config.json`.
