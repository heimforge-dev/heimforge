# Generator Architecture

## Modules

- `bootstrap/naming.py`: regex validators for identity inputs (`NamingError` on failure). Deliberately duplicates the shape of `template/scripts/suite_metadata.py`'s own `SEMVER`/`GUID_ROOT` regexes — see `docs/TEMPLATE_MAINTENANCE.md`.
- `bootstrap/model.py`: `ProjectParams` (raw generator inputs), `build_model()` (derives the included `ModuleSpec` set), `suite_config_dict()` and `solution_text()` (programmatically build `suite.config.json` and the `.sln`), and `token_map()` (the substitution dictionary for `template/`).
- `bootstrap/render.py`: `render_tree()` walks `template/`, skips optional module directories per `OPTIONAL_DIR_FLAGS`, substitutes `{{TOKEN}}` placeholders and `__ROOT_NAMESPACE__` path segments, and preserves the executable bit on `.sh` files. `validate_template()` is the template's own self-check (backs `scripts/validate-template.sh`).
- `bootstrap/validate_generated.py`: post-generation checks on a rendered output directory — unresolved tokens/paths, leaked bootstrapper implementation identity, valid JSON/MSBuild XML/Bash, correct client/server package isolation, and (when available) the generated project's own `suite_metadata.py check`, scaffold tests, portable preflight, and `dotnet test`.
- `bootstrap/create_project.py`: CLI orchestration — interactive prompts or flags, safety checks on the output directory, and the summary printed to the user.

## Why `suite.config.json` and the `.sln` are generated, not templated

Their content structurally depends on which optional modules (`ServerCore`, `Client`, `Shared.Diagnostics`) are included — project lists, package membership, and solution GUIDs all vary per generation. A static template file cannot express that conditionality without a second templating mechanism, so `bootstrap/model.py` builds both programmatically from the `ProjectModel` instead.

## Generation pipeline

1. `validate_params()` — reject malformed suite name, namespace, GUID root, author, Thunderstore namespace, or version.
2. `build_model()` — derive the concrete `ModuleSpec` set (`Common` always; `ServerCore`/`Client`/`Shared.Diagnostics` per include flags).
3. Refuse an unsafe or non-empty output directory without `--force` (see `_safe_output_dir` in `create_project.py`: rejects `/`, `$HOME`, the bootstrapper's own repository, and any ancestor of it).
4. `render_tree()` — copy `template/` into the output directory, substituting tokens and skipping excluded optional module directories.
5. Write the generated `suite.config.json` and `<RootNamespace>.sln`.
6. Run `python3 scripts/suite_metadata.py sync` inside the output directory to produce `build/Suite.Generated.props`, `src/<RootNamespace>.Common/SuiteConstants.Generated.cs`, and `packaging/profile-lock.json` — reusing the generated project's own logic rather than duplicating it here.
7. `validate_generated()` — structural and (when possible) executable proof that the output is sound.
8. Print the summary: solution path, generated projects, validation result, and next steps.

## No templating dependency

The token vocabulary is small, closed, and enumerated in `docs/TEMPLATE_MAINTENANCE.md`. A flat `re.sub` substitution (`bootstrap/render.py`) is sufficient; Jinja2 or any other templating engine would be an unjustified dependency for this scope and would also risk leaking into the generated project's own tooling, which must stay fully independent of the bootstrapper.
