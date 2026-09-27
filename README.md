# HeimForge

HeimForge generates standalone Valheim mod-suite repositories built around
BepInEx and Jötunn.

It provides a structured starting point for projects that need separate
client/server modules, repeatable builds, metadata-driven deployment, testing,
and deterministic packaging.

HeimForge is an unofficial community project and is not affiliated with or
endorsed by Iron Gate or Coffee Stain.

## What it generates

A generated project can include:

- `Common` shared code
- `ServerCore` server-only functionality
- `Client` client-only functionality
- `Shared.Diagnostics` shared optional diagnostics
- BepInEx + Jötunn project scaffolding
- build, test, deploy, and package scripts
- metadata-driven client/server deployment
- deterministic release packages with SHA-256 checksums
- development and architecture documentation

Generated repositories are standalone and do not depend on HeimForge after
generation.

## Requirements

To run HeimForge:

- WSL2 or native Linux
- Bash and Git
- Python 3.10 or newer

A .NET SDK is required to build and test generated projects, but not merely to
run the generator.

A Valheim installation is not required to generate a project.

## Quick start

Generate a project interactively:

```bash
./scripts/create-project.sh
```

Or non-interactively:

```bash
./scripts/create-project.sh \
  --name MyMod \
  --namespace MyMod \
  --guid com.example.mymod \
  --author "Your Name" \
  --thunderstore-namespace YourName \
  --version 0.1.0 \
  --output ~/src/mymod
```

`ServerCore`, `Client`, and `Shared.Diagnostics` can each be omitted when they
are not needed.

Portable coding-agent support is included by default using `AGENTS.md`,
`.context/`, and standard project skills under `.agents/skills/`. It is not
tied to a specific agent provider or harness.

Use `--no-agent-tooling` to generate a project without that layer. Optional
provider-specific integrations are additive adapters; for example,
`--agent-adapter omp` adds the OMP extension and prompt without replacing the
portable project instructions or skills.

After generation:

```bash
cd ~/src/mymod
cp Environment.props.example Environment.props
cp .valheim/dev.json.example .valheim/dev.json
./scripts/preflight.sh --portable
```

## Example

[heimforge-example](https://github.com/heimforge-dev/heimforge-example) is a
clean reference project generated with all supported module tiers enabled and
no added gameplay code.

## Licensing

HeimForge source and documentation outside `template/` are licensed under
Apache-2.0.

Reusable scaffold material under `template/` is licensed under MIT-0 because
it is copied into independently owned generated repositories.

Generated projects choose their own project-level license before public
distribution.

See `LICENSE`, `template/LICENSES/MIT-0.txt`, and
`docs/TEMPLATE_MAINTENANCE.md` for details.

## Documentation

- `docs/GENERATOR_ARCHITECTURE.md` — generator architecture
- `docs/TEMPLATE_MAINTENANCE.md` — maintaining the generated template
- `CONTRIBUTING.md` — development and contribution workflow
- `SECURITY.md` — reporting security issues
