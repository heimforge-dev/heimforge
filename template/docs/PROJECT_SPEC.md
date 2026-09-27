# Modular Valheim Mod Suite Specification

## Objective

Build one coherent mod ecosystem with three runtime tiers:

1. Server-only core features.
2. Independent client+server shared modules.
3. Client-only presentation and convenience features.

The suite must support vanilla clients when the enabled feature set permits it and must reject clients cleanly when a required shared module is absent or incompatible.

ServerCore, Client, and Shared.* modules may be individually omitted at generation time; `suite.config.json`'s `projects` is authoritative for which modules exist in this repository, and must always exactly match `<RootNamespace>.sln`'s real project membership.

## Principles

- server authority
- per-feature compatibility classification
- Jotunn APIs before Harmony
- no guessing Valheim internals
- minimal persistent world modifications
- safe feature removal where technically possible
- no Unity API use from background threads unless verified thread-safe
- minimal dependencies

## Runtime assemblies

### {{ROOT_NAMESPACE}}.Common

Pure/shared primitives with minimal Unity coupling.

### {{ROOT_NAMESPACE}}.ServerCore

One BepInEx plugin containing internally modular server-only features.

### {{ROOT_NAMESPACE}}.Shared.*

Every client+server gameplay feature is an independent BepInEx plugin so compatibility can be enforced per module.

### {{ROOT_NAMESPACE}}.Client

One BepInEx plugin containing internally modular client-only features. Move any feature requiring authority or server cooperation into a `Shared.*` plugin.

## Compatibility model

Every module declares one of:

- SERVER_ONLY
- SHARED_OPTIONAL
- SHARED_REQUIRED
- CLIENT_ONLY

For Jotunn, expected mappings include:

- client/server-independent plugins: `CompatibilityLevel.NotEnforced` with `VersionStrictness.None`
- optional shared modules: evaluate `VersionCheckOnly` after verifying exact desired behavior
- required shared modules: `ClientMustHaveMod` or `EveryoneMustHaveMod`

Do not choose compatibility attributes mechanically. Consider custom assets, RPC symmetry, persistence, and what happens when the client plugin is present on another server.

## Versioning

Use one suite release version initially. Shared modules additionally expose a protocol version. Persistent modules expose a data schema version.

## Configuration

ServerCore config is server-local. Shared gameplay settings may use Jotunn synchronization. Client personal preferences remain local and are not synchronized merely because synchronization exists.

## Networking

Jotunn CustomRPC is preferred for suite-level or complex two-sided messaging. ZNetView RPCs may be preferable for small object-local communication.

Client-to-server requests follow:

```text
intent -> deserialize -> validate -> authorize -> mutate authoritative state -> respond
```

## Harmony

Maintain `docs/patch-ledger.md`. Prefer Prefix/Postfix. Transpilers require explicit IL assumptions and failure behavior.

## Persistent state

Prefer sidecar storage for suite metadata. Namespaced ZDO data is appropriate when state belongs to an individual world object.

## Initial milestones

### Milestone 0

Repository scaffold, build scripts, dependency docs, metadata validation, deterministic local packaging foundation, and optional portable agent tooling.

### Milestone 1

Every module generated in this repository compiles and loads with correct side behavior.

### Milestone 2

{{PROJECT_SPEC_MILESTONE2_BODY}}

### Milestone 3

Choose and implement the project's first real feature using `docs/features/TEMPLATE.md`, classified by scope and validated against current Jötunn/Valheim behavior before implementation.

### Milestone 4

Complete runtime-validated server/client pack workflow, clean-profile validation, and public package/profile manifests when final branding is available.

## Non-goals initially

No custom launcher, auto-updater, web admin panel, database service, telemetry backend, custom networking framework, generic event bus, or Unity asset project without a concrete need.
