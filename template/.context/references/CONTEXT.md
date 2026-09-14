---
type: catalog
---

# Reference context

One job: provide stable project constraints without duplicating mutable repository state.

## Inputs

- Metadata authority and update rules: `project.md`.
- Detailed decisions and records: `../../docs/`.

## Process

1. Open only the reference selected by `../CONTEXT.md` for the current task.
2. Check mutable claims against the machine authority before relying on them.
3. Keep detailed ledgers and designs in their owning `docs/` files; link rather than copy.

## Outputs

- Updated reference note in this folder when a stable project constraint changes.

## Human check

Confirm the edited reference still points to the authoritative repository file and does not create a second source of truth.
