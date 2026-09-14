---
type: reference
---

# Architecture

## Dependency graph

```text
{{ROOT_NAMESPACE}}.Common
      ^
      |
 +----+-----------------------+
 |            |               |
ServerCore   Client     Shared.<Module>
```

`ServerCore`, `Client`, and every `Shared.*` plugin are independent BepInEx plugins. ServerCore, Client, and Shared.* modules may be individually absent. Follow `project.md` for current membership authority and structural update rules.

## Target frameworks

- `Common` targets `netstandard2.0`.
- Every generated runtime plugin project targets `net48`.
- `csharpLanguageVersion` remains authoritative in `suite.config.json`.

The project files under `src/` are authoritative if a later structural edit changes this framework split.

## Compatibility categories

- `SERVER_ONLY`
- `SHARED_OPTIONAL`
- `SHARED_REQUIRED`
- `CLIENT_ONLY`

Each shared plugin owns its compatibility policy rather than inheriting a suite-wide rule.

## Boundaries

### Common

Own shared contracts and pure logic needed by runtime plugins. It is not a BepInEx runtime plugin.

### ServerCore

May mutate authoritative world and gameplay state. It must not require a client plugin.

### Shared modules

Own mechanics that need code on both sides, RPCs, client-visible custom networked state, custom content, or synchronized interaction semantics.

### Client

May alter presentation, UI, input, camera, and local convenience. It may not authoritatively mutate shared gameplay state.

## Feature reclassification

When a client-only feature begins requiring server authority, extract the shared mechanics into a dedicated `Shared.*` plugin. Do not grow cross-boundary exceptions inside `Client`.

Update `docs/module-catalog.md` whenever module scope or compatibility changes.

## Persistence

Prefer sidecar state for suite metadata. Use namespaced ZDO data only when state naturally belongs to a world object. Back up persistent state before migration testing and keep detailed formats in `docs/persistence.md`.

## Runtime implementation

- Extract pure gameplay algorithms from Unity-facing code where practical so they can be unit tested.
- Do not use Unity or Valheim APIs from background threads unless the relevant API is explicitly verified thread-safe.
- BepInEx and Jotunn are the platform. Do not add ServerSync without a demonstrated requirement.
