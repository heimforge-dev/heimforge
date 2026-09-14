---
type: reference
---

# Networking

## Authority

Clients are untrusted. A client sends intent; the server validates and performs authoritative gameplay mutations.

Validate client requests for:

- sender identity
- player state
- object existence
- range or proximity
- permissions or admin status
- resource availability
- stale state
- payload bounds
- rate limits where abuse is possible

## Module compatibility

### SERVER_ONLY

Jotunn compatibility must not force clients to install the module.

### SHARED_OPTIONAL

Vanilla clients may join. If both sides have the plugin, incompatible versions must not silently exchange incompatible payloads.

### SHARED_REQUIRED

Server presence requires a compatible client module. Prefer stricter enforcement for custom prefabs, items, assets, or symmetric RPC protocols.

### CLIENT_ONLY

No server requirement and no authoritative server RPC dependency.

## RPC naming

Use stable names derived from plugin GUID and module ID. Module operation names must remain stable and explicit.

Suggested logical convention:

`rpc/<module>/<operation>/<protocol-version>`

## Versioning

- suite semantic version: `MAJOR.MINOR.PATCH`
- shared modules additionally expose `ProtocolVersion`
- persistent modules additionally expose `DataSchemaVersion`

Patch releases should remain network-compatible where practical.

Protocol or compatibility changes must also follow `testing.md` for multiplayer and release verification.

## Records

For each RPC, update `docs/networking.md`; update `docs/module-catalog.md` when protocol or compatibility changes module classification.
