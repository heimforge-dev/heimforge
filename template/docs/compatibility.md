# Compatibility

## Server-only

Server-only plugins must not make the client install the mod. Use non-enforced Jotunn compatibility where appropriate.

## Shared optional

Vanilla clients may connect. Enhanced behavior is enabled only when both sides support the feature. The module must fail closed when the peer lacks the expected protocol.

## Shared required

The server requires compatible clients. Choose `ClientMustHaveMod` or `EveryoneMustHaveMod` based on whether symmetry, assets, prefabs, RPC registration, or persistence demands it.

## Client-only

The server does not care about the plugin. The plugin must not perform authoritative gameplay mutation.

## Release compatibility

Patch releases should be network-compatible where practical. Protocol-breaking changes increment a module's `ProtocolVersion` and normally the suite minor version.
