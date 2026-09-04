# Modular Valheim Mod Suite Specification

## Objective

Build one coherent mod ecosystem with three runtime tiers:

1. Server-only core features.
2. Independent client+server shared modules.
3. Client-only presentation and convenience features.

The suite must support vanilla clients when the enabled feature set permits it and must reject clients cleanly when a required shared module is absent or incompatible.

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

### ValheimSuite.Common

Pure/shared primitives with minimal Unity coupling.

### ValheimSuite.ServerCore

One BepInEx plugin containing internally modular server-only features. AutoFeed is the first planned gameplay feature.

### ValheimSuite.Shared.*

Every client+server gameplay feature is an independent BepInEx plugin so compatibility can be enforced per module.

### ValheimSuite.Client

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

Repository/harness scaffold, context, skills, extension, build scripts, dependency docs, metadata validation, and deterministic local packaging foundation.

### Milestone 1

Common, ServerCore, Client, Shared.Diagnostics compile and load with correct side behavior.

### Milestone 2

Shared Diagnostics proves CustomRPC request/response, module/version reporting, and multiplayer plumbing without changing gameplay state.

### Milestone 3

AutoFeed as the first ServerCore feature. Reverse engineer hunger, food validation, containers, ownership, and server simulation before implementation.

### Milestone 4

Complete runtime-validated server/client pack workflow, clean-profile validation, and public package/profile manifests when final branding is available.

### Milestone 5

First real shared gameplay module chosen from an actual requirement.

## Non-goals initially

No custom launcher, auto-updater, web admin panel, database service, telemetry backend, custom networking framework, generic event bus, or Unity asset project without a concrete need.
