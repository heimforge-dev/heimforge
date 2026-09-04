# ValheimSuite Project Instructions

This file contains repository-specific rules only. Reusable coding-harness behavior belongs in the user's global OMP rules.

## Required context

Before significant work read:

- `.context/PROJECT.md`
- `.context/CURRENT_STATE.md`

For architecture or multiplayer work also read:

- `.context/ARCHITECTURE.md`
- `.context/NETWORKING.md`

For Harmony or game-internal work also read:

- `.context/PATCHING.md`
- `docs/patch-ledger.md`

For release/deployment work also read:

- `.context/TESTING.md`
- `docs/release.md`

## Project rules

1. Never guess Valheim API signatures when local assemblies or current Jötunn documentation can be inspected.
2. Prefer Jötunn APIs/events over Harmony patches.
3. Prefer Harmony Prefix/Postfix over Transpilers.
4. Treat clients as untrusted. The server validates authoritative gameplay actions.
5. Never commit Valheim assemblies, publicized assemblies, generated game DLLs, credentials, passwords, world saves, or production configuration.
6. Never deploy automatically to a production world.
7. Use a disposable integration-test world by default.
8. Back up persistent state before migration testing.
9. Server-only features must not introduce required client behavior.
10. Client-only features must not mutate authoritative shared gameplay.
11. If a feature crosses those boundaries, reclassify it as an independent Shared Module.
12. Update `docs/module-catalog.md` whenever module scope or compatibility changes.
13. Update `docs/patch-ledger.md` whenever a Harmony patch is added, changed, revalidated, or removed.
14. Update `.context/CURRENT_STATE.md` after meaningful milestones.
15. Keep changes minimal and scoped. YAGNI applies.
16. Do not add a dependency without recording why in `docs/dependencies.md`.
17. Do not introduce an abstraction until a concrete consumer needs it.
18. Extract pure gameplay algorithms from Unity-facing code where practical so they can be unit tested.
19. Treat a Valheim update as invalidating Harmony assumptions until revalidated.
20. Compilation alone is not proof of multiplayer correctness.
21. Do not use Unity/Valheim APIs from background threads unless explicitly verified thread-safe.
22. Do not create generic planner, reviewer, scout, or worker agents for this project. Use the harness capabilities already installed.
23. Do not duplicate globally configured Context Mode or Context7 configuration inside this repository unless a project-specific override is genuinely required.
24. Treat WSL/Linux as the canonical development and build environment. Keep the repo in the WSL filesystem, not under `/mnt/c`, unless there is a specific reason otherwise.
25. Use WSL paths such as `/mnt/c/...` when accessing the Windows Valheim client installation.
26. Bash/WSL scripts are the only canonical project workflow. Do not create a second independent PowerShell implementation of build/deploy/package behavior.
27. `suite.config.json` is the authoritative suite/build/package metadata source. After editing it, run `python3 scripts/suite_metadata.py sync` and commit the generated changes together.
28. Never manually edit `build/Suite.Generated.props`, `SuiteConstants.Generated.cs`, or `packaging/profile-lock.json`.
29. Do not duplicate client/server deployment classification. `scripts/deploy.py` and `suite.config.json` define it.
30. Before release/deployment changes run the scaffold tests in addition to C# tests.
31. Public release preparation must pass `python3 scripts/suite_metadata.py check --release`.
32. Jötunn prebuild may modify/generated files under the configured Valheim development installation. Enable it only after confirming `VALHEIM_INSTALL` points at the intended development install.
