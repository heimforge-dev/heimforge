# Template Maintenance

## Token vocabulary

Every text file under `template/` may use only the tokens below. `bootstrap/render.py`'s `validate_template()` (backing `scripts/validate-template.sh`) fails the build if an unknown `{{TOKEN}}` appears anywhere in `template/`.

| Token | Computed in | Notes |
|---|---|---|
| `{{SUITE_NAME}}` | `token_map()` from `ProjectParams.suite_name` | |
| `{{ROOT_NAMESPACE}}` | `token_map()` from `ProjectParams.root_namespace` | dot-separated C# namespace, e.g. `ExampleCompany.Vibeheim` |
| `{{ROOT_NAMESPACE_LOWER}}` | `token_map()`, `root_namespace.lower()` | |
| `{{PLUGIN_GUID_ROOT}}` | `token_map()` from `ProjectParams.plugin_guid_root` | |
| `{{AUTHOR}}` | `token_map()` from `ProjectParams.author` | |
| `{{THUNDERSTORE_NAMESPACE}}` | `token_map()` from `ProjectParams.thunderstore_namespace` | |
| `{{SUITE_VERSION}}` | `token_map()` from `ProjectParams.suite_version` | |
| `{{JOTUNN_VERSION}}` | `token_map()`, `DEPENDENCY_BASELINE` | |
| `{{BEPINEX_VERSION}}` | `token_map()`, `DEPENDENCY_BASELINE` | |
| `{{NETFX_REF_VERSION}}` | `token_map()`, `DEPENDENCY_BASELINE` | |
| `{{CSHARP_LANG_VERSION}}` | `token_map()`, `DEPENDENCY_BASELINE` | |
| `{{MODULE_CATALOG_ROWS}}` | `module_catalog_rows()` | one Markdown table row per included module; no feature-specific rows |
| `{{INCLUDED_MODULES_LIST}}` | `included_modules_bullets()` | bullet list of included runtime packages |
| `{{COMPATIBILITY_BOUNDARIES_LIST}}` | `compatibility_boundaries_bullets()` | bullet list of included modules' compatibility levels |

Path token: `__ROOT_NAMESPACE__` — substring-replaced in path segments only (e.g. `src/__ROOT_NAMESPACE__.Common/` → `src/Vibeheim.Common/`), never inside file content.

## Adding a token

1. Add the value/derivation to `bootstrap/model.py`'s `token_map()` (or a new `DEPENDENCY_BASELINE` entry for a shared constant).
2. Add the token name to `bootstrap/render.py`'s `KNOWN_TOKENS`.
3. Use it in the relevant `template/` file(s).
4. Add a row to the table above.
5. Run `scripts/validate-template.sh`.

## Adding a new optional module

1. Extend `ProjectParams` (new `include_<module>: bool = True` field) and `ProjectModel`/`build_model()` in `bootstrap/model.py`.
2. Add the module to `ProjectModel.modules`, `suite_config_dict()`, and `solution_text()`.
3. Add the module's template directory under `template/src/__ROOT_NAMESPACE__.<Module>/` and register it in `bootstrap/render.py`'s `OPTIONAL_DIR_FLAGS`.
4. Add a CLI flag (`--no-<module>`) and interactive prompt in `bootstrap/create_project.py`.
5. Add fixture test coverage for both the included and omitted case (`tests/fixtures/`), including that `scripts/package.py`'s `package_definitions()` does not emit an empty package for the omitted module.

## Adding a new scalar generator input

1. Extend `ProjectParams` and `naming.py` with a validator if the input has format constraints.
2. Add it to `token_map()` if templates need it.
3. Add the CLI flag and interactive prompt in `create_project.py`.

## Deliberate duplication: `bootstrap/naming.py` vs `template/scripts/suite_metadata.py`

`bootstrap/naming.py`'s `SEMVER_RE`/`GUID_ROOT_RE` intentionally mirror the shape of `suite_metadata.py`'s own `SEMVER`/`GUID_ROOT` regexes. A generated project must never import bootstrapper code — its own `suite_metadata.py check` is the only thing that validates its `suite.config.json` at runtime — so the two copies are kept in sync by convention, not by a shared dependency. Update both together when either changes.

`bootstrap/naming.py`'s `NAMESPACE_RE` (dot-separated C# identifier segments) has no counterpart in `suite_metadata.py`, which only requires `rootNamespace` to be a non-empty string; the stricter generation-time check is a UX guard, not a runtime invariant of the generated project.

## Keeping `template/` generic

`template/` must stay a generic modular framework: no concrete gameplay features, no project-specific milestones. `docs/module-catalog.md`, `docs/PROJECT_SPEC.md`'s milestones, and `BOOTSTRAP_PROMPT.md` intentionally stop at "prove the scaffold and Shared Diagnostics architecture, then define the first real feature using `docs/features/TEMPLATE.md`" rather than naming any specific feature.
