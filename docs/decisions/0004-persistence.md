# ADR 0004: Persistence

## Context

Suite metadata may need persistence without unnecessarily coupling it to Valheim world internals.

## Decision

Prefer sidecar state for suite metadata and namespaced ZDO data only for object-local state.

## Consequences

Removal and migration are easier, while object-specific data can still follow world objects when required.

## Alternatives considered

Store everything in ZDOs; external database.
