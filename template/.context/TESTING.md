# Testing

## Canonical environment

Run builds, tests, packaging, assembly inspection, and server tooling from WSL/Linux.

Use the Windows Valheim client as the real client integration target through its WSL-mounted path under `/mnt/c/...`.

## Levels

0. Scaffold invariants without Valheim binaries.
1. Pure C# unit tests without Valheim binaries.
2. Local plugin compilation in WSL against the legitimate Windows Valheim installation exposed through `/mnt/c/...`.
3. Disposable Linux/Docker dedicated-server smoke test.
4. Multiplayer integration between the Windows client and the dedicated test server.

## Compatibility matrix

| Server | Client | Expected |
| --- | --- | --- |
| ServerCore only | Vanilla | Connect |
| ServerCore only | Modded client | Connect |
| Required Shared | Missing module | Reject |
| Required Shared | Compatible module | Connect |
| Optional Shared | Vanilla | Connect |
| Optional Shared | Compatible module | Connect with enhancement |
| Vanilla server | Client module | Connect if feature is truly client-only |

## Disposable-world policy

Never use the production world as the default integration target.

## Canonical commands

Preflight: `./scripts/preflight.sh`

Portable preflight: `./scripts/preflight.sh --portable`

Bootstrap: `./scripts/bootstrap.sh`

Scaffold tests: `python3 -m unittest discover -s tests/scaffold -p 'test_*.py' -v`

Portable + C# tests: `./scripts/test.sh`

Full build: `./scripts/build.sh Debug`

Client deployment: `./scripts/deploy-client.sh Debug`

Server deployment: `./scripts/deploy-server.sh Debug`

Release packaging: `./scripts/package.sh`

Full plugin compilation additionally requires the local Valheim/Jötunn development references. If publicized references are absent, deliberately enable Jötunn prebuild after verifying `VALHEIM_INSTALL`.
