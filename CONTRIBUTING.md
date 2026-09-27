# Contributing to HeimForge

HeimForge is a generator for standalone Valheim mod-suite repositories. Changes
to HeimForge should preserve the boundary between the generator itself and the
independent repositories produced from `template/`.

## Development environment

HeimForge is developed and tested primarily under WSL2/Linux.

Requirements:

- Git with submodule support
- Python 3.10 or newer
- .NET 8 SDK for the full generated-project test suite

Clone with submodules:

```bash
git clone --recurse-submodules https://github.com/heimforge-dev/heimforge.git
cd heimforge
```

If the repository was cloned without submodules:

```bash
git submodule update --init --recursive
```

## Repository structure

- `bootstrap/` contains the Python generator.
- `template/` is the complete standalone project scaffold copied into generated repositories.
- `tests/bootstrap/` contains generator tests.
- `tests/template/` contains template and generated-project tests.
- `docs/` contains HeimForge architecture and maintenance documentation.

For detailed repository constraints, also read `AGENTS.md` and
`docs/TEMPLATE_MAINTENANCE.md`.

## Making changes

Keep changes focused and preserve these boundaries:

- Generated repositories must remain standalone and must not depend on a
  HeimForge checkout.
- `template/` must remain generic. Project-specific gameplay such as Vibeheim
  features does not belong in HeimForge.
- Do not perform repository-wide identity replacement. Generator identity
  substitution is controlled by the documented template token system.
- Do not commit generated-project developer configuration, game assemblies,
  credentials, world data, or other machine-local files.
- Files under `template/` are MIT-0 licensed scaffold material. HeimForge code
  outside `template/` is Apache-2.0 licensed. Preserve that licensing boundary.

## Testing

During development, prefer targeted tests for the area being changed.

For changes under `template/`, always run:

```bash
./scripts/validate-template.sh
```

The canonical full HeimForge test suite is:

```bash
./scripts/test.sh
```

Broad, cross-cutting, generator, template, release, or security-sensitive
changes should pass the full suite before completion.

GitHub Actions also provides a manually dispatched full test suite for hosted
validation with Python and .NET.

## Pull requests

Before opening a pull request:

```bash
git diff --check
```

Make sure relevant tests pass and the working tree contains no generated or
machine-local files.

Use a concise Conventional Commit style title where practical, for example:

- `feat: add ...`
- `fix: correct ...`
- `docs: clarify ...`
- `test: cover ...`
- `chore: update ...`

HeimForge uses Release Please, so clear conventional commit history helps
produce meaningful automated releases.

Pull requests should explain:

- what changed
- why it changed
- what validation was performed
- whether generated-project behavior or template output changed

## Reporting bugs and proposing features

Use the repository issue forms for normal bug reports and feature requests.

Security vulnerabilities must not be reported through a public issue. Follow
the instructions in `SECURITY.md`.
