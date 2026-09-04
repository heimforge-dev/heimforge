# Persistence

## Default strategy

Prefer suite sidecar files for suite metadata and module-owned non-object state.

Suggested logical path:

`BepInEx/config/{{ROOT_NAMESPACE}}/state/<world-id>/`

Every persistent file should contain a schema version, suite version, and world identifier.

Use atomic replace semantics for writes.

## ZDO data

Use namespaced keys only when state naturally belongs to a world object.

Suggested key pattern:

`{{ROOT_NAMESPACE_LOWER}}:<module>:<key>`

Schema migrations require a backup, explicit migration function, test, and release note.
