# Bootstrap {{SUITE_NAME}}

You are bootstrapping and validating this repository as a modular Valheim mod suite.

Read, in order:

1. `AGENTS.md`
2. `.context/PROJECT.md`
3. `.context/ARCHITECTURE.md`
4. `.context/NETWORKING.md`
5. `.context/PATCHING.md`
6. `.context/TESTING.md`
7. `.context/CURRENT_STATE.md`
8. `docs/PROJECT_SPEC.md`
9. `docs/dependencies.md`
10. `docs/module-catalog.md`

Use the project skills under `.omp/skills/` when their domain applies.

## Preserve these established decisions

Do not redesign the high-confidence foundation during bootstrap:

- WSL/Linux is canonical for repo/harness/build/test/package/server tooling.
- Windows Valheim is the actual client runtime and is accessed through `/mnt/c/...`.
- Runtime topology is Common + ServerCore + independent Shared modules + Client. Any of ServerCore, Client, or a Shared.* module may be absent in this repository; `suite.config.json` is authoritative for what was generated.
- ServerCore remains `NotEnforced / None`.
- Client remains `NotEnforced / None`.
- Shared.Diagnostics remains `VersionCheckOnly / Minor` until a concrete reason changes it.
- Jötunn is the common modding/network platform; ServerSync is not added without a demonstrated need.
- `suite.config.json` is the authoritative metadata/project/package map.
- `scripts/deploy.py` is the single deployment implementation for both Bash and the OMP extension.
- Do not replace these choices merely to make the scaffold look different.

## First actions

1. Run `python3 scripts/suite_metadata.py check` and fix only real consistency defects.
2. Run `./scripts/preflight.sh`.
3. Confirm the repository is in the WSL filesystem rather than `/mnt/c/...` unless intentionally configured otherwise.
4. Verify `Environment.props` and `.valheim/dev.json` identify the same development Valheim installation.
5. Inspect the configured development client for `Assembly-CSharp.dll`, BepInEx, and Jötunn.
6. Verify the pinned Jötunn and BepInExPack versions against current stable releases. Do not silently upgrade. Report newer versions if any and preserve pins unless there is a compatibility reason to change.
7. Run `./scripts/bootstrap.sh`.
8. Verify OMP actually discovers `.omp/skills/`, `.omp/prompts/`, and `.omp/extensions/valheim-dev` using the installed OMP version.
9. Update `.context/CURRENT_STATE.md` with facts proven on this machine.

## Jötunn first-build handling

`DoPrebuild.props` defaults to `ExecutePrebuild=false` deliberately.

Before enabling it:

1. Confirm `VALHEIM_INSTALL` points at the intended development Valheim installation.
2. Check whether `valheim_Data/Managed/publicized_assemblies` already exists and is current.
3. If references are missing, enable Jötunn prebuild deliberately and perform the first full plugin build.
4. Do not commit generated/publicized game assemblies.

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

- `{{ROOT_NAMESPACE}}.Common`
- `{{ROOT_NAMESPACE}}.ServerCore`
- `{{ROOT_NAMESPACE}}.Client`
- `{{ROOT_NAMESPACE}}.Shared.Diagnostics`

Each plugin must build and load in its intended environment.

Implement robust runtime-side detection only after confirming current Valheim/Jötunn APIs from local assemblies or current docs. Do not guess signatures.

ServerCore must not require clients to install it.
Client must not require servers to install it.
Shared Diagnostics must be safe on both sides and must not alter persistent gameplay state.

## Milestone 2 diagnostics

After Milestones 0 and 1 build/load cleanly, implement a minimal Jötunn CustomRPC diagnostic exchange proving:

- client-to-server registration
- server-side sender handling
- server-to-client response
- suite version reporting
- module/protocol reporting
- bounded useful logging
- no persistent gameplay mutation

Consult current Jötunn RPC documentation or Context7 and verify exact signatures before coding.

## First real feature

After Milestones 0-2 are proven (scaffold validated, plugins build/load correctly, Shared Diagnostics proves the CustomRPC/versioning plumbing), do not invent further built-in gameplay features in this generic scaffold.

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
- update `.context/CURRENT_STATE.md`
- state separately what is proven, what remains unverified, and what is game-version-sensitive
