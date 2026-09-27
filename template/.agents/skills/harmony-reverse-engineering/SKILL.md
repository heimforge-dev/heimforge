---
name: harmony-reverse-engineering
description: Inspect current Valheim assemblies and implement or repair Harmony patches. Use when a feature depends on game internals, private behavior, uncertain signatures, ownership paths, or a Valheim update may have broken a patch.
---

# Harmony and Reverse Engineering

1. Inspect the actual installed assembly with `ilspycmd` or another inspection tool available in the active environment.
2. Search current Jotunn APIs/events first.
3. Locate the target type and exact method signature.
4. Trace callers/callees where behavior or ownership is unclear.
5. Determine client/server execution and ZNet/ZDO ownership.
6. Prefer Prefix/Postfix.
7. Use a Transpiler only when necessary.
8. Record the patch in `docs/patch-ledger.md` before considering the work complete.
9. Record the verified game version.
10. Add runtime diagnostics for fragile assumptions.
11. Re-test and revalidate after Valheim updates.

## Transpiler requirements

Document the expected IL pattern and fail clearly if it cannot be located. Never depend on fixed instruction indexes when pattern matching can be used.

Never manufacture method signatures from memory.
