# ADR 0003: Network Compatibility

## Context

Vanilla-compatible server features and required client/server features must coexist.

## Decision

Assign compatibility at plugin/module level: server-only, shared optional, shared required, client-only.

## Consequences

A server can remain vanilla-client-compatible until an enabled required shared plugin intentionally changes that.

## Alternatives considered

One suite-wide compatibility rule.
