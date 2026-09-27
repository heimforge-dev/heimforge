# Changelog

## [0.8.0](https://github.com/heimforge-dev/heimforge/compare/v0.7.1...v0.8.0) (2026-09-27)


### Features

* make agent tooling portable and optional ([181327f](https://github.com/heimforge-dev/heimforge/commit/181327f1df2073978a8361c9e34d67a09d88a425))
* make generated agent tooling portable and optional ([42bbc2e](https://github.com/heimforge-dev/heimforge/commit/42bbc2e54dd329346e2b2908b41d5c99009a8c33))


### Documentation

* make generated agent guidance provider-neutral ([1de2e8b](https://github.com/heimforge-dev/heimforge/commit/1de2e8b16e0095aa5319c48fcc6503dcdb8fd1fd))
* simplify project readmes ([262e5b9](https://github.com/heimforge-dev/heimforge/commit/262e5b999f1d7c28c1863887a326b7527b49e7c2))
* simplify project readmes ([2867f86](https://github.com/heimforge-dev/heimforge/commit/2867f862a1d086cc00f69cacdc9637ca332d9954))

## [0.7.1](https://github.com/heimforge-dev/heimforge/compare/v0.7.0...v0.7.1) (2026-09-27)


### Documentation

* add contributor and security guidance ([3c41042](https://github.com/heimforge-dev/heimforge/commit/3c4104209cb2de8944889dee9f77c8f5458f2ad1))
* add contributor and security guidance ([5717ab7](https://github.com/heimforge-dev/heimforge/commit/5717ab763201c721f82e86fac6cd25435ea746d0))
* add unofficial project disclaimer ([a1a57de](https://github.com/heimforge-dev/heimforge/commit/a1a57de47cce185efca28b14542785703aed3590))
* add unofficial project disclaimer ([5215c16](https://github.com/heimforge-dev/heimforge/commit/5215c16f96a9eb5d60ee15069321b413da07f5d0))
* link generated example project ([401ab4c](https://github.com/heimforge-dev/heimforge/commit/401ab4c5fa2ad22125ec7c9395b4123df98f1f6a))
* link generated example project ([8934b36](https://github.com/heimforge-dev/heimforge/commit/8934b36bacbb228528841dbd5bf7fec14fba0149))

## [0.7.0](https://github.com/heimforge-dev/heimforge/compare/v0.6.0...v0.7.0) (2026-09-26)


### Features

* establish open-source licensing boundary ([#9](https://github.com/heimforge-dev/heimforge/issues/9)) ([df5b26f](https://github.com/heimforge-dev/heimforge/commit/df5b26f98eb9c6ab57e7de83b1d78dfaff6e0304))

## [0.6.0](https://github.com/heimforge-dev/heimforge/compare/v0.5.0...v0.6.0) (2026-09-26)


### Features

* add dependency baseline updater ([1335b48](https://github.com/heimforge-dev/heimforge/commit/1335b48df625ec9ccaa5114156ca2e7951aaf049))


### Documentation

* align HeimForge guidance with current workflows ([#7](https://github.com/heimforge-dev/heimforge/issues/7)) ([ae53d41](https://github.com/heimforge-dev/heimforge/commit/ae53d411a2a66a2b1b669aa01347e1c4e02e9417))

## [0.5.0](https://github.com/heimforge-dev/heimforge/compare/v0.4.2...v0.5.0) (2026-09-16)


### Features

* add opt-in runtime debug logging ([#5](https://github.com/heimforge-dev/heimforge/issues/5)) ([c6b60dd](https://github.com/heimforge-dev/heimforge/commit/c6b60dd1b704feda871a380ee6ec8faef74cd2e2))

## [0.4.2](https://github.com/heimforge-dev/heimforge/compare/v0.4.1...v0.4.2) (2026-09-15)


### Bug Fixes

* allow ignored local developer config ([2fb6b6d](https://github.com/heimforge-dev/heimforge/commit/2fb6b6d53dc14eed30434c5b84d28c24caf6f0c3))
* allow ignored local developer config ([b6ab490](https://github.com/heimforge-dev/heimforge/commit/b6ab490bb233f58e4104fc630af9f18dc32ad4ee))

## [0.4.1](https://github.com/heimforge-dev/heimforge/compare/v0.4.0...v0.4.1) (2026-09-15)


### Bug Fixes

* bootstrap release please manifest ([5ffe7ab](https://github.com/heimforge-dev/heimforge/commit/5ffe7abc57090384018d508c3ad62e8d28311e30))

## 0.4.0 - 2026-09-15

### Context architecture

- Replaced the generated flat `.context/*.md` bundle with a routed context architecture separating stable references, mutable project state, and version-sensitive findings.
- Added explicit context routing, scoped authority, finding ownership/backlinks, schema rules, and reusable finding templates.
- Tightened generated repository guardrails and task-specific context loading to reduce authority ambiguity and stale-context edits.

### Harness and maintenance

- Added ICM Architect as a pinned HeimForge submodule for context architecture auditing.
- Added GitHub Actions CI for the canonical test suite, template validation, and repository-cleanliness checks.
- Hardened CI portability across WSL and hosted Linux runners, including environment-derived filesystem fixtures, hosted-runner concurrency timing, and .NET 8 SDK selection.
- Updated generated OMP skills, bootstrap guidance, networking/testing documentation, and Valheim inspection workflows for the routed context model.
- Clarified that `check-game-update.sh` fingerprints the current gameplay assembly and lists Harmony targets requiring manual semantic revalidation; it does not validate patch semantics.

### Validation

- Expanded bootstrap and template regression coverage for the routed context structure, identity constraints, game-stack maintenance, environment paths, and game-internal inspection.
- Dogfooded the generated context migration in Vibeheim and completed controlled implementation/planning comparisons before the release gate.

## 0.3.0 - 2026-09-14

### Project metadata

- Added `pyproject.toml` with standard HeimForge project metadata and release versioning.

### Project identity

- Renamed ValheimSuite Bootstrap to HeimForge across the generator, template, documentation, tests, and project metadata.
- Updated checkout-leakage coverage for the HeimForge identity.

### Valheim tooling

- Resolved and fingerprinted `assembly_valheim.dll` as the current gameplay assembly, with `Assembly-CSharp.dll` fallback for older layouts and durable OMP game-info fields.

### Test performance

- Added certified generated-fixture reuse for tests that are semantically downstream of generation while preserving real generation at generator, security, and output-boundary tests.
- Removed redundant nested generated-project validation while preserving standalone validation behavior, failure semantics, and .NET availability handling.
- Reduced the certified warm full-suite runtime from 3097.32 seconds to 807.99 seconds, a 73.9% reduction and approximately 3.83x speedup.
- Expanded the suite to 560 tests with zero failures, errors, or skips at the certified baseline.
- Documented the performance audit, retained safety boundaries, and rejected unsafe MSBuild aggregation approaches.
- Added `./scripts/test.sh` as the canonical root test entry point.

## 0.2.0 - 2026-09-11

### Development environment

- Honored configured development dependency paths consistently.
- Prevented duplicate Jötunn environment imports.
- Preserved the executable preflight entry point.
- Added server runtime configuration and validation coverage.

### Deployment

- Added staged SSH server deployment with isolated upload, verification, promotion, rollback, and optional Docker restart behavior.
- Added transport-independent deployment planning and remote server runtime operations.
- Expanded deployment, path-safety, and remote-runtime regression coverage.

### Metadata and maintenance

- Made generated metadata synchronization transactional.
- Added an offline game-stack reference refresh workflow.
- Added generated-project maintenance tooling for updating game-stack references without embedding default dependency versions.

### Diagnostics

- Added the generated Jötunn RPC handshake for Shared Diagnostics.

### Documentation and tests

- Clarified test execution guidance.
- Expanded bootstrap, template, environment-path, metadata, remote deployment, and game-stack maintenance coverage.

## 0.1.0 - 2026-09-11

### Architecture

- Initial modular suite scaffold.
- Server Core, Client, Common, and Shared Diagnostics project shells.
- Preserved per-module Jötunn compatibility boundaries.

### Harness

- OMP project context, domain skills, extension, and bootstrap prompt.
- WSL-first canonical workflow.

### Hardening

- Added `suite.config.json` as authoritative build/package metadata with generated consistency-checked outputs.
- Added WSL/local-environment preflight validation.
- Added private `Microsoft.NETFramework.ReferenceAssemblies` dependency for cross-platform `net48` builds.
- Centralized client/server deployment classification in metadata-driven `scripts/deploy.py`.
- Added stale suite-DLL cleanup during development deployment.
- Hardened OMP assembly inspection and server log handling.
- Replaced placeholder packaging with deterministic local ZIPs and SHA-256 checksums.
- Added repository scaffold regression tests.
- Added explicit public-release metadata gate.
- Certified generated-project `TargetFramework` and `AssemblyName` through structured, evaluation-only MSBuild property queries in the canonical Debug/Release solution context.
- Preserved explicitly non-certifying structural bootstrap operations for environments without .NET.

### Bootstrapper

- Converted the fixed ValheimSuite v3 scaffold into a generic generator with `bootstrap/`, `template/`, tests, and project-creation tooling.
- Generated the standalone Vibeheim project as the first dogfood output.
