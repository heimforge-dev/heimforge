---
type: catalog
---

# Verified findings contract

One job: store evidence-backed, game-version-sensitive runtime and API knowledge.

## Inputs

- Installed game and publicized assemblies from the configured development installation.
- Current authoritative Jotunn documentation.
- Patch, runtime, server, and multiplayer observations.

## Process

1. Update `valheim-runtime.md` only with the tested game version and configured runtime environment.
2. For each independent runtime or API claim, copy `../_templates/finding.md` to a kebab-case filename in this folder and change its frontmatter as instructed.
3. Record the exact evidence and add a relative Markdown link to the owning code, document, patch-ledger entry, or protocol record. An unlinked finding is invalid.
4. Mark a finding stale when a game or dependency update invalidates its evidence.

## Outputs

- `valheim-runtime.md`
- Additional finding files copied from `../_templates/finding.md`

## Human check

Reproduce the evidence on the configured development installation before marking a finding verified or using it for a Harmony target.
