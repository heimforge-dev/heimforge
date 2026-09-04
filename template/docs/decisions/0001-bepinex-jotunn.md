# ADR 0001: Bepinex Jotunn

## Context

The suite needs a stable Valheim modding runtime, networking compatibility, synchronization, RPC, commands, and development tooling.

## Decision

Use BepInExPack for Valheim plus Jotunn as the platform. Do not add ServerSync initially.

## Consequences

A broad community dependency is accepted in exchange for less custom infrastructure and better interoperability.

## Alternatives considered

Raw BepInEx/Harmony only; BepInEx + ServerSync; custom synchronization/RPC stack.
