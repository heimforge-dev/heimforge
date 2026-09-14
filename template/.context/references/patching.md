---
type: reference
---

# Patching

The root guardrail against guessed Valheim signatures applies to every patch.

## Preferred order

1. Jotunn API or event.
2. Stable Valheim method or event.
3. Harmony Prefix or Postfix.
4. Harmony Transpiler only when necessary.

## Before adding a patch

- inspect the currently installed game assembly
- verify the target type and method signature
- understand caller and callee flow when relevant
- determine network ownership and execution side
- determine persistence implications
- record the patch in `docs/patch-ledger.md`

## Related routes

- For module, ownership, or persistence boundaries, follow `architecture.md`.
- If the patched behavior is networked or authoritative, also follow `networking.md`.
- For runtime or release verification, follow `testing.md`.

## Transpiler requirements

A transpiler must document:

- why Prefix or Postfix cannot solve the problem
- IL assumptions
- pattern matching strategy
- behavior when the expected pattern is absent
- game version last verified

Every Valheim update invalidates game-internal and Harmony assumptions until they are revalidated. Add verified evidence under `../findings/` by copying `../_templates/finding.md` when the finding is independent of the runtime baseline.

Update `docs/patch-ledger.md` whenever a Harmony patch is added, changed, revalidated, or removed.
