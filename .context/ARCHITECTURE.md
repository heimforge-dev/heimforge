# Architecture

## Dependency graph

```text
ValheimSuite.Common
      ^
      |
 +----+-----------------------+
 |            |               |
ServerCore   Client     Shared.<Module>
```

`ServerCore`, `Client`, and every `Shared.*` plugin are independent BepInEx plugins.

## Compatibility categories

- `SERVER_ONLY`
- `SHARED_OPTIONAL`
- `SHARED_REQUIRED`
- `CLIENT_ONLY`

Each shared plugin owns its compatibility policy rather than inheriting a suite-wide rule.

## Boundaries

### ServerCore

May mutate authoritative world/gameplay state. Must not require a client plugin.

### Shared modules

Used for mechanics that need code on both sides, RPCs, client-visible custom networked state, custom content, or synchronized interaction semantics.

### Client

May alter presentation, UI, input, camera, and local convenience. It may not authoritatively mutate shared gameplay state.

## Feature reclassification

When a client-only feature begins requiring server authority, extract the shared mechanics into a dedicated `Shared.*` plugin. Do not grow cross-boundary exceptions inside `Client`.

## Persistence

Prefer sidecar state for suite metadata. Use namespaced ZDO data only when state naturally belongs to a world object.

## Dependency policy

BepInEx + Jotunn are the platform. Do not add ServerSync initially. Add new runtime dependencies only for a demonstrated requirement.
