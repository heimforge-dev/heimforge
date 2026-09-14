# Changelog

## 0.3.0 - 2026-09-14

### Project metadata

- Added `pyproject.toml` with standard HeimForge project metadata and release versioning.

### Project identity

- Renamed ValheimSuite Bootstrap to HeimForge across the generator, template, documentation, tests, and project metadata.
- Updated checkout-leakage coverage for the HeimForge identity.

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
