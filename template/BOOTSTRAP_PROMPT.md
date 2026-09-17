# Bootstrap {{SUITE_NAME}}

You are bootstrapping and validating this repository as a modular Valheim mod suite.

Read, in order:

1. `AGENTS.md`
2. `.context/CONTEXT.md`
3. `.context/references/project.md`
4. `.context/references/architecture.md`
5. `.context/references/networking.md`
6. `.context/references/patching.md`
7. `.context/references/testing.md`
8. `.context/findings/CONTEXT.md`
9. `.context/findings/valheim-runtime.md`
10. `.context/state/CONTEXT.md`
11. `.context/state/current.md`
12. `docs/PROJECT_SPEC.md`
13. `docs/dependencies.md`
14. `docs/module-catalog.md`

Use the project skills under `.omp/skills/` when their domain applies.

## Preserve these established decisions

Do not redesign the high-confidence foundation during bootstrap:

- WSL/Linux is canonical for repo/harness/build/test/package/server tooling.
- Windows Valheim is the actual client runtime and is accessed through `/mnt/c/...`.
- Runtime topology is Common + ServerCore + independent Shared modules + Client. Any of ServerCore, Client, or a Shared.* module may be absent in this repository; `suite.config.json`'s `projects` is authoritative for what was generated, and must always exactly match `<RootNamespace>.sln`'s real project membership.
{{COMPATIBILITY_BOUNDARIES_LIST}}
- Jötunn is the common modding/network platform; ServerSync is not added without a demonstrated need.
- `suite.config.json` is the editable source of truth for supported mutable suite/project/package metadata. Generation-time suite identity (`suiteName`, `rootNamespace`) is locked in `suite.identity.lock.json` and cannot be changed by editing `suite.config.json`.
- `scripts/deploy.py` is the single deployment implementation for both Bash and the OMP extension.
- Do not replace these choices merely to make the scaffold look different.

## First actions

1. Run `python3 scripts/suite_metadata.py check` and fix only real consistency defects.
2. Run `./scripts/preflight.sh`.
3. Confirm the repository is in the WSL filesystem rather than `/mnt/c/...` unless intentionally configured otherwise.
4. Verify `Environment.props` and `.valheim/dev.json` identify the same development Valheim installation.
5. Inspect the configured development client for its resolved gameplay assembly (`assembly_valheim.dll`, with `Assembly-CSharp.dll` fallback for older layouts), BepInEx, and Jötunn.
6. Verify the pinned Jötunn and BepInExPack versions against current stable releases. Do not silently upgrade. Report newer versions if any and preserve pins unless there is a compatibility reason to change.
7. Run `./scripts/bootstrap.sh`.
8. Verify OMP actually discovers `.omp/skills/`, `.omp/prompts/`, and `.omp/extensions/valheim-dev` using the installed OMP version.
9. Record the inspected game version and configured runtime environment in `.context/findings/valheim-runtime.md`; create separate evidence-backed findings for any implementation-dependent claims.
10. Update `.context/state/current.md` with the resulting verification status.

## Jötunn reference refresh

`DoPrebuild.props` defaults to `ExecutePrebuild=false` deliberately; ordinary `./scripts/build.sh` stays parallel and never regenerates publicized references on its own.

Before refreshing references:

1. Confirm `VALHEIM_INSTALL` points at the intended development Valheim installation (`Environment.props` and `.valheim/dev.json` must agree).
2. Check whether `valheim_Data/Managed/publicized_assemblies` already exists and is current.
3. If references are missing or stale, run `python3 scripts/update-game-stack.py refresh` (the normal pinless workflow after a Valheim binary/reference update) or the lower-level `./scripts/refresh-references.sh [Debug|Release]`, which performs Jötunn prebuild in serialized mode (`-m:1`) because the publicized-assembly output is shared.
4. Do not hand-edit `ExecutePrebuild` in `DoPrebuild.props`; use the refresh commands above instead.
5. Do not commit generated/publicized game assemblies.

Do not guess around a failed plugin build. Read the Jötunn build output and inspect the local generated-reference state.

## Milestone 0 acceptance

Confirm that:

- metadata check passes
- scaffold tests pass
- local secrets/machine config are ignored
- the solution references all configured projects
- net48 runtime projects have cross-platform reference-assembly support
- deterministic packaging code is present rather than a placeholder
- deployment classification is metadata-driven and excludes wrong-side DLLs
- OMP extension loads under the user's installed OMP

## Milestone 1 acceptance

Complete and validate every module generated in this repository (per `suite.config.json`), for example:

{{INCLUDED_MODULES_LIST}}

Each plugin must build and load in its intended environment.

Implement robust runtime-side detection only after confirming current Valheim/Jötunn APIs from local assemblies or current docs. Do not guess signatures.

{{RUNTIME_MODULE_CONSTRAINTS_LIST}}
{{BOOTSTRAP_DIAGNOSTICS_MILESTONE}}
## First real feature

After {{BOOTSTRAP_MILESTONES_PROVEN_CLAUSE}}, do not invent further built-in gameplay features in this generic scaffold.

Define the project's first real feature using `docs/features/TEMPLATE.md`:

- classify it as SERVER_ONLY, SHARED_OPTIONAL, SHARED_REQUIRED, or CLIENT_ONLY
- use the `valheim-modding`, `valheim-networking`, and `harmony-reverse-engineering` skills as appropriate
- consult current Jötunn documentation or Context7 before coding
- if game internals are required, reverse engineer only what is needed and record every Harmony patch in `docs/patch-ledger.md`
- prefer a disposable world for any destructive testing

## Harness discipline

Use native harness planning, review, subagents, worktrees, and model routing. Do not create project-specific generic agents duplicating those capabilities.

Prefer small coherent changes. Avoid speculative frameworks, custom launchers, auto-updaters, web dashboards, cloud services, databases, generic event buses, and custom networking layers.

Do not stop at a TODO if the answer can be obtained from repository files, local assemblies, current Jötunn documentation, build output, Docker configuration, or logs.

At the end of each substantial milestone:

- run available scaffold/unit/build/runtime checks
- update relevant docs
- update `.context/state/current.md`
- state separately what is proven, what remains unverified, and what is game-version-sensitive
