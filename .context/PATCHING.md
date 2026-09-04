# Patching

## Preferred order

1. Jotunn API/event.
2. Stable Valheim method/event.
3. Harmony Prefix/Postfix.
4. Harmony Transpiler only when necessary.

## Before adding a patch

- inspect the currently installed game assembly
- verify target type and method signature
- understand caller/callee flow when relevant
- determine network ownership/execution side
- determine persistence implications
- record the patch in `docs/patch-ledger.md`

## Transpiler requirements

A transpiler must document:

- why Prefix/Postfix cannot solve the problem
- IL assumptions
- pattern matching strategy
- behavior when the expected pattern is absent
- game version last verified

Every Valheim update requires revalidation of game-internal assumptions.
