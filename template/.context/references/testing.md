---
type: reference
---

# Testing and release verification

## Canonical environment

Run builds, tests, packaging, assembly inspection, and server tooling from WSL/Linux. Use the Windows Valheim client as the real client integration target through its WSL-mounted path under `/mnt/c/...`.

## Verification levels

0. Scaffold invariants without Valheim binaries.
1. Pure C# unit tests without Valheim binaries.
2. Local plugin compilation in WSL against the legitimate Windows Valheim installation.
3. Disposable Linux/Docker dedicated-server smoke test.
4. Multiplayer integration between the Windows client and the dedicated test server.

Compilation and package generation are not proof of multiplayer correctness.

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

## Safety

- Never use the production world as the default integration or release-verification target.
- Back up persistent state before migration testing.
- Reference refresh (`./scripts/refresh-references.sh` or `python3 scripts/update-game-stack.py refresh`) writes generated/publicized references into the configured development Valheim installation. Run it only after confirming `VALHEIM_INSTALL` points at the intended development install.

## Canonical commands

- Preflight: `./scripts/preflight.sh`
- Portable preflight: `./scripts/preflight.sh --portable`
- Bootstrap: `./scripts/bootstrap.sh`
- Scaffold tests: `python3 -m unittest discover -s tests/scaffold -p 'test_*.py' -v`
- Portable plus C# tests: `./scripts/test.sh`
- Full build: `./scripts/build.sh Debug`
- Reference refresh: `./scripts/refresh-references.sh Debug`
- Game-stack pinless refresh: `python3 scripts/update-game-stack.py refresh`
- Client deployment: `./scripts/deploy-client.sh Debug`
- Server deployment: `./scripts/deploy-server.sh Debug`
- Release packaging: `./scripts/package.sh`
- Public release metadata gate: `python3 scripts/suite_metadata.py check --release`

Before release or deployment changes, run the scaffold tests in addition to C# tests. Full plugin compilation requires local Valheim/Jotunn development references; if publicized references are absent or stale, run `python3 scripts/update-game-stack.py refresh` (or the lower-level `./scripts/refresh-references.sh`) after verifying `VALHEIM_INSTALL`.

Detailed test and release procedures live in `docs/testing.md` and `docs/release.md`.
