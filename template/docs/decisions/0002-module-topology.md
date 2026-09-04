# ADR 0002: Module Topology

## Context

Different features have different client/server requirements.

## Decision

Use one ServerCore plugin, one Client plugin, and independent Shared plugins per two-sided feature.

## Consequences

Compatibility policy can vary per shared feature and unrelated modules stay decoupled.

## Alternatives considered

One monolithic plugin; one server DLL plus one all-features client DLL.
