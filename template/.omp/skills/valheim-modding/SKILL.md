---
name: valheim-modding
description: Implement or modify Valheim gameplay features in this repository. Use for BepInEx/Jotunn integration, game lifecycle hooks, config, gameplay systems, or feature scaffolding. Classify runtime scope before coding and verify current APIs rather than relying on remembered Valheim internals.
---

# Valheim Modding

Use this workflow for Valheim feature implementation.

## Before coding

1. Read `.context/CONTEXT.md`, `.context/references/project.md`, `.context/references/architecture.md`, and `.context/state/current.md`.
2. Classify the feature as `SERVER_ONLY`, `SHARED_OPTIONAL`, `SHARED_REQUIRED`, or `CLIENT_ONLY`.
3. Record or update the feature document from `docs/features/TEMPLATE.md`.
4. Consult current Jotunn docs/Context7 first.
5. Prefer Jotunn APIs/events over Harmony.
6. If Valheim internals are required, use the `harmony-reverse-engineering` skill.
7. Determine which machine owns and executes the behavior.
8. Separate pure logic from Unity-facing integration where practical.
9. Add tests for pure logic.
10. Update the module catalog and current state when behavior or scope changes.

## Constraints

- Never guess old Valheim signatures.
- Never commit game assemblies.
- Do not add a Unity asset project until custom assets are needed.
- Keep dependencies minimal.
- Avoid hot-loop allocations and full-world scans.
