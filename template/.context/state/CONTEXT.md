---
type: catalog
---

# Current-state contract

One job: record what is working, in progress, next, and verified in this generated repository.

## Inputs

- Structural authority and update rules: `../references/project.md`.
- Verification evidence: actual command output and runtime observations from the configured development environment.
- Stable constraints: `../references/`.

## Process

1. Update `current.md` after a meaningful milestone or verification run.
2. Record only observed results as verified; keep unavailable runtime proof explicitly unverified.
3. When project membership changes, update the generated baseline after the metadata and solution agree.

## Outputs

- `current.md`

## Human check

Compare every changed status claim with the command output or runtime observation that established it before continuing.
