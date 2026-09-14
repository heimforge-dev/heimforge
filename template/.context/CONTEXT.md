---
type: catalog
---

# Project context

This directory is the task-routed context bundle for the generated mod suite. Read only the route needed for the current task; the repository remains the source of truth.

| Task | Read |
| --- | --- |
| Understand purpose, platform, metadata, dependencies, or project-wide policy | `references/project.md` |
| Check current progress, next work, or verification status | `state/current.md` |
| Update current progress or verification status | `state/CONTEXT.md`, then `state/current.md` |
| Implement a gameplay feature or change modules, compatibility, persistence, or ownership | `references/architecture.md`, then `state/current.md` |
| Change multiplayer behavior, RPCs, or protocol compatibility | `references/networking.md` |
| Add or revalidate Harmony or game-internal work | `references/patching.md`, then `findings/CONTEXT.md` |
| Test, build, deploy, package, or release | `references/testing.md` |
| Record facts about the installed game or current APIs | `findings/CONTEXT.md` |
| Maintain this context bundle or its stable references | `_meta/schema.md`, then the relevant folder's `CONTEXT.md` |

## Scoped authorities

| Kind of fact | Authority |
| --- | --- |
| Always-on repository safeguards | `../AGENTS.md` |
| Suite identity and configured project membership | `suite.identity.lock.json`, `suite.config.json`, and the canonical solution |
| Other editable suite, package, and dependency metadata | `suite.config.json` |
| Generated metadata | Its owning source plus a successful `scripts/suite_metadata.py sync`; generated output alone is not authoritative |
| Implemented behavior | The relevant code and scripts |
| Architectural intent | Applicable records under `docs/decisions/` and `docs/`, with concise constraints under `references/` |
| Verification status and game-version-sensitive claims | Actual command output or runtime evidence recorded under `state/` or `findings/` |

If this bundle disagrees with the applicable authority, correct the bundle instead of coding against stale context.
