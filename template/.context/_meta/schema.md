---
type: schema
---

# Context schema

This schema defines the closed note types and naming rules for `.context/`.

## Note types

| `type` | Location | Purpose |
| --- | --- | --- |
| `catalog` | `CONTEXT.md` files | Route to content without carrying its payload. |
| `schema` | `_meta/schema.md` | Define the bundle's note types and conventions. |
| `template` | `_templates/*.md` | Provide a copyable starting shape; never represents a real record. |
| `reference` | `references/*.md` | Hold stable constraints and project decisions used across tasks. |
| `state` | `state/*.md` | Hold mutable progress and verification status. |
| `finding` | `findings/*.md` | Hold evidence-backed, version-sensitive runtime or API knowledge. |

## Frontmatter

- Every note declares `type`.
- Template notes declare the type they produce in `produces`.
- Finding notes declare `status: unverified`, `verified`, or `stale`.
- Verified findings declare `verified_on` and identify the relevant game version or documentation source in the note body.
- Do not mark remembered or inferred Valheim behavior as verified.

## Naming and paths

- Use lowercase kebab-case filenames, except the structural `CONTEXT.md` contracts.
- Keep each fact in one owning note and link to it from other notes.
- Markdown links between context notes are relative to the containing note.
- Repository source paths and commands are relative to the repository root unless explicitly stated otherwise.
- Add a finding by copying `_templates/finding.md`, changing its frontmatter to `type: finding` and `status: unverified`, and linking its owning code, document, patch, or protocol surface.
