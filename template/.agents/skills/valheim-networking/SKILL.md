---
name: valheim-networking
description: Design, review, or implement Valheim multiplayer behavior, RPCs, config sync, ZDO/ZNet ownership, inventories, authoritative state, or module compatibility. Use whenever a feature crosses client/server boundaries.
---

# Valheim Networking

## Classify first

Choose exactly one:

- `SERVER_ONLY`
- `SHARED_OPTIONAL`
- `SHARED_REQUIRED`
- `CLIENT_ONLY`

## Determine

- authoritative side
- network owner
- persistence location
- compatibility level
- version strictness
- RPC needs
- synchronized config
- vanilla-client behavior

## Trust model

Treat client gameplay claims as untrusted.

For client-to-server actions validate:

- sender
- player/session state
- referenced object
- range/proximity where relevant
- resources
- permissions
- stale state
- payload bounds
- rate limits when useful

## Jotunn

Use Jotunn compatibility, synchronization, and CustomRPC facilities unless a documented requirement proves insufficient.

For small object-local messages, consider native ZNetView RPCs after verifying ownership semantics.

## Documentation

- Update `docs/networking.md` for concrete RPC or protocol changes.
- Update `docs/module-catalog.md` for compatibility or module-classification changes.
- Update `.context/references/networking.md` only when the stable networking constraints or policy change.
