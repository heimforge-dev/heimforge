# HeimForge Instructions

This repository is a generator (bootstrapper), not a Valheim mod project. It produces standalone Valheim mod-suite repositories from `template/`.

## Structure

- `bootstrap/`: generator code (`model.py`, `naming.py`, `render.py`, `validate_generated.py`, `create_project.py`). Pure Python, stdlib only.
- `template/`: the complete standalone project template rendered into every generated project.
- `tests/bootstrap/`, `tests/template/`, `tests/fixtures/`: generator unit tests, template structural tests, generated-fixture tests.
- `scripts/create-project.sh`, `scripts/validate-template.sh`: bootstrapper entry points.
- `docs/GENERATOR_ARCHITECTURE.md`, `docs/TEMPLATE_MAINTENANCE.md`: bootstrapper documentation.

## Project rules

1. `template/` must remain a complete, standalone project tree. It must never depend on files outside itself and must never import `bootstrap/` Python modules.
2. Never repository-wide string-replace project identity. All identity substitution flows through the token vocabulary documented in `docs/TEMPLATE_MAINTENANCE.md`, applied by `bootstrap/render.py`.
3. `suite.config.json` and `<RootNamespace>.sln` are generated programmatically from the model (`bootstrap/model.py`), not templated static files; never add them under `template/`.
4. Adding a token requires updating `bootstrap/model.py`'s `token_map`, the template files that use it, `bootstrap/render.py`'s `KNOWN_TOKENS`, and `docs/TEMPLATE_MAINTENANCE.md`.
5. `bootstrap/naming.py`'s regex constants and `template/scripts/suite_metadata.py`'s own copies must stay in agreement; update both together (the generated project cannot import the bootstrapper).
6. Never commit a generated project's `Environment.props`, `.valheim/dev.json`, game assemblies, or credentials. Test fixtures must render under system temp directories, never under this repo tree.
7. Run `scripts/validate-template.sh` after any `template/` change.
8. Do not create generic planner/reviewer/scout/worker agents for this project; use native harness capabilities.
9. Keep changes minimal and scoped. Do not add a templating dependency (Jinja2 etc.) — the dependency-free token substitution in `render.py` is deliberate.
10. Do not implement Vibeheim (or any generated project's) gameplay features from this repository. `template/` must stay a generic framework; feature-specific work belongs inside the generated project.
11. Prefer targeted and adjacent tests during iteration. Run the full suite once before completing broad or cross-cutting changes when warranted. Do not repeatedly run the full suite for narrow changes.
