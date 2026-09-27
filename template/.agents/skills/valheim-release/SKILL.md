---
name: valheim-release
description: Validate, package, deploy, or release the Valheim mod suite. Use for build verification, disposable-server smoke tests, multiplayer compatibility checks, manifests, local packages, Thunderstore preparation, or Valheim update validation.
---

# Valheim Release

Preserve the established module/compatibility architecture unless a concrete runtime requirement forces a documented change.

Before packaging or deployment:

1. Run `python3 scripts/suite_metadata.py check`.
2. Run scaffold and C# unit tests.
3. Build the intended configuration against the verified local Valheim/Jötunn environment.
4. Use `scripts/deploy.py` through the canonical Bash wrapper. Optional agent adapters must delegate to the same implementation rather than recreate side-classification logic.
5. For release candidates, perform a local plugin load test and disposable dedicated-server smoke test.
6. Run multiplayer compatibility tests for changed Shared Modules.
7. Review config generation, patch ledger, persistence/migrations, changelog, and `.context/state/current.md`.
8. Generate deterministic packages with `./scripts/package.sh` and retain `SHA256SUMS`.

For public publication additionally require:

```text
python3 scripts/suite_metadata.py check --release
```

Never package:

- Valheim assemblies
- publicized/generated game assemblies
- `Environment.props`
- `.valheim/dev.json`
- production server configuration
- credentials/passwords
- world saves

Never use the production world for release verification.
