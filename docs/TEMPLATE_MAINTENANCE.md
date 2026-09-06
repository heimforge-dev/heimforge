# Template Maintenance

## The template manifest

`bootstrap/template_manifest.py` is the template definition: `REQUIRED_TEMPLATE_FILES` (rendered unconditionally) and `OPTIONAL_TEMPLATE_FILES` (rendered per included optional module). `template/`'s filesystem contents are not themselves the template — `render_tree()` renders exactly the manifest's approved paths, and `validate_template()` (backing `scripts/validate-template.sh`) fails if a manifest file is missing, or if `template/` contains a filesystem entry — file *or* directory, empty or not — that isn't in (or a required ancestor of) the manifest. Adding a file under `template/` without adding it here has no effect on generated output and fails validation instead of being silently ignored.

Every manifest entry must be a normalized, relative, POSIX-style path: no leading `/`, no backslashes, no `.`/`..` component, and no double slashes. `validate_manifest_structure()` enforces this on the manifest itself (not just on what happens to exist in `template/`), and also rejects a path listed in more than one group (`REQUIRED_TEMPLATE_FILES` and an `OPTIONAL_TEMPLATE_FILES` set, or two different `OPTIONAL_TEMPLATE_FILES` sets). A literal path repeated *within* one `{...}` set is not separately checked for — Python's `frozenset` already collapses that to one element before any validation runs, so there is nothing to observe.

A manifest-approved path is also re-verified at the moment of reading: `render_tree()`/`validate_template()` open every source through `_open_source_file()`, which refuses to follow a symlink at any path component (including the final one) and refuses anything that isn't a plain regular file. Substituting a symlink for an approved file, or for one of its parent directories, fails validation instead of silently rendering whatever the symlink points at.

## Adding a new template file

1. Add the file under `template/` at the path it should render to (using `__ROOT_NAMESPACE__` for module-specific `src/`/`tests/` directories).
2. Add its `template/`-relative path to `bootstrap/template_manifest.py`'s `REQUIRED_TEMPLATE_FILES` (or the relevant `OPTIONAL_TEMPLATE_FILES[module]` set if it belongs to an optional module).
3. Run `scripts/validate-template.sh`.

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
3. Add the module's template directory under `template/src/__ROOT_NAMESPACE__.<Module>/`, register its files under a new key in `bootstrap/template_manifest.py`'s `OPTIONAL_TEMPLATE_FILES`, and add that key to `bootstrap/render.py`'s `OPTIONAL_MODULE_PRESENT`.
4. Add a CLI flag (`--no-<module>`) and interactive prompt in `bootstrap/create_project.py`.
5. Add fixture test coverage for both the included and omitted case (`tests/fixtures/`), including that `scripts/package.py`'s `package_definitions()` does not emit an empty package for the omitted module.

## Adding a new scalar generator input

1. Extend `ProjectParams` and `naming.py` with a validator if the input has format constraints.
2. Add it to `token_map()` if templates need it.
3. Add the CLI flag and interactive prompt in `create_project.py`.

## Deliberate duplication: `bootstrap/naming.py` vs `template/scripts/suite_metadata.py`

`bootstrap/naming.py`'s `validate_semver()`/`GUID_ROOT_RE`/`NAMESPACE_SEGMENT`, C# keyword set, `THUNDERSTORE_NAMESPACE_RE`, and portable path-component rules intentionally mirror the generated scripts' `validate_semver()`/`GUID_ROOT`/`NAMESPACE_SEGMENT`, C# keyword set, `THUNDERSTORE_NAMESPACE`, and `NAME_COMPONENT`. `validate_semver()` implements SemVer 2.0.0 syntax (https://semver.org) directly rather than as one regex — see `tests/bootstrap/test_naming.py` and `tests/template/test_naming_grammar.py`'s `BootstrapGeneratedGrammarAlignmentTests` for the shared case list that keeps both copies from drifting apart. A generated project must never import bootstrapper code — its own `suite_metadata.py check`/`sync` is the only thing that validates its `suite.config.json` at runtime, and it must do so independently even after a maintainer hand-edits the file — so the copies are kept in sync by convention, not by a shared dependency. Update both together when either changes.

`suite_metadata.py` additionally enforces path-containment and archive-safety rules (`contain`, `package.py`'s `validate_arcname`) that have no bootstrapper-side counterpart, because the bootstrapper never re-derives filesystem paths from arbitrary post-generation edits the way the generated project's own `sync`/`package.py` must.

## `.ts` token rendering never trusts input grammar alone

`render_tree()` renders every `.ts` destination through `_ts_string_escape()` (JSON-string escaping of the substituted value, without its outer quotes) instead of raw substitution, because every current `{{TOKEN}}` use in a `.ts` file sits inside an existing double-quoted string literal (e.g. `label: "Build {{SUITE_NAME}}"` in `template/.omp/extensions/valheim-dev/index.ts`). This is defense-in-depth on top of, not a replacement for, each token's own grammar (`naming.validate_path_component()` for `SUITE_NAME`, etc.) — see `tests/bootstrap/test_render_ts_escaping.py`.

## Keeping `template/` generic

`template/` must stay a generic modular framework: no concrete gameplay features, no project-specific milestones. `docs/module-catalog.md`, `docs/PROJECT_SPEC.md`'s milestones, and `BOOTSTRAP_PROMPT.md` intentionally stop at "prove the scaffold and Shared Diagnostics architecture, then define the first real feature using `docs/features/TEMPLATE.md`" rather than naming any specific feature.
