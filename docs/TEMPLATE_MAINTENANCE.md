# Template Maintenance

## The template manifest

`bootstrap/template_manifest.py` is the template definition: `REQUIRED_TEMPLATE_FILES` (rendered unconditionally) and `OPTIONAL_TEMPLATE_FILES` (rendered per included optional module). `template/`'s filesystem contents are not themselves the template — `render_tree()` renders exactly the manifest's approved paths, and `validate_template()` (backing `scripts/validate-template.sh`) fails if a manifest file is missing, or if `template/` contains a filesystem entry — file *or* directory, empty or not — that isn't in (or a required ancestor of) the manifest. Adding a file under `template/` without adding it here has no effect on generated output and fails validation instead of being silently ignored.

Every manifest entry must be a normalized, relative, POSIX-style path: no leading `/`, no backslashes, no `.`/`..` component, and no double slashes. `validate_manifest_structure()` enforces this on the manifest itself (not just on what happens to exist in `template/`), and also rejects a path listed in more than one group (`REQUIRED_TEMPLATE_FILES` and an `OPTIONAL_TEMPLATE_FILES` set, or two different `OPTIONAL_TEMPLATE_FILES` sets). A literal path repeated *within* one `{...}` set is not separately checked for — Python's `frozenset` already collapses that to one element before any validation runs, so there is nothing to observe.

A manifest-approved path is also re-verified at the moment of reading: `render_tree()`/`validate_template()` open every source through `_open_source_file()`, which refuses to follow a symlink at any path component (including the final one) and refuses anything that isn't a plain regular file. Substituting a symlink for an approved file, or for one of its parent directories, fails validation instead of silently rendering whatever the symlink points at.

## Adding a new template file

1. Add the file under `template/` at the path it should render to (using `__ROOT_NAMESPACE__` for module-specific `src/`/`tests/` directories).
2. Add its `template/`-relative path to `bootstrap/template_manifest.py`'s `REQUIRED_TEMPLATE_FILES` (or the relevant `OPTIONAL_TEMPLATE_FILES[module]` set if it belongs to an optional module).
3. Run `scripts/validate-template.sh`.

## Licensing boundary

Original HeimForge-authored files under `template/` are distributed under
MIT-0 because they are copied into generated repositories. Keep
`template/LICENSES/MIT-0.txt` in the required template manifest and do not add
a root `template/LICENSE`: a generated project's root license is deliberately
left for that project's author to choose.

Generated repositories therefore retain `LICENSE.todo` until a project license
is selected. New template material must preserve this boundary. Do not copy
third-party material into the template without preserving and documenting its
own applicable license terms.

`scripts/update-game-stack.py` and `scripts/refresh-references.sh` are required generated workflow entry points. Keep their ownership narrow: the Python command may reuse generated `preflight.py` and `suite_metadata.py` helpers for local inspection and mutable pins, while the shell command is the sole serialized Jötunn reference-refresh path. `suite_metadata.py sync` owns the complete generated-output set and promotes it transactionally. Register both in the manifest and preserve the ordinary parallel `scripts/build.sh` behavior.

## Updating the default dependency baseline

Use the root maintenance command when HeimForge's defaults should move to newer Jötunn and/or BepInExPack Valheim versions:

```bash
./scripts/update-dependency-baseline.sh --jotunn <version> --bepinex <version>
```

Either version flag may be omitted when only one default changes. The command validates SemVer syntax, refuses to mutate an already-inconsistent baseline, and keeps `bootstrap/model.py` and `BOOTSTRAP_MANIFEST.json` synchronized. Those two files are the only checked-in authorities for the current default Jötunn/BepInEx baseline; tests and generated fixtures must derive current defaults rather than copy their literal versions.

This command changes bootstrap defaults only. It does not modify an existing generated project, install runtime packages, refresh publicized assemblies, build, deploy, restart Valheim, or alter any separate project such as Vibeheim. Generated projects continue to use their own `scripts/update-game-stack.py` workflow.

After changing the baseline, run the focused bootstrap/update tests and template validation before committing:

```bash
python3 -m unittest tests.bootstrap.test_model tests.bootstrap.test_update_dependency_baseline
./scripts/validate-template.sh
```

## Token vocabulary

Every text file under `template/` may use only the tokens below. A token name matches `bootstrap/render.py`'s `TOKEN_RE` (`[A-Z_][A-Z0-9_]*`: first character alphabetic/underscore, remaining characters may also be digits, e.g. `PROJECT_SPEC_MILESTONE2_BODY`) -- the renderer's own token *grammar*, backing discovery, substitution, and `validate_template()`'s known-token check against a template *source* file. `bootstrap/render.py`'s `validate_template()` (backing `scripts/validate-template.sh`) fails the build if an unknown `{{TOKEN}}` appears anywhere in `template/`. `validate_generated.py`'s final-output check is a different concern entirely, with a policy split between paths and content: a generated *path* has no legitimate brace syntax at all, so any raw `{{`/`}}` in a relative path fails outright; generated *text* can legitimately contain a doubled brace (`template/scripts/suite_metadata.py`'s f-string escape for literal C# braces is the one such case in the whole generated tree), so content is checked for a marker-*shaped* `{{...}}` instead -- `UNRESOLVED_MARKER_RE` for an ordinary balanced marker, `MALFORMED_MARKER_RE` for one mangled by a single stray interior brace (e.g. `{{BAD}1}}`, `{{BAD{1}}}`) -- either broader than `TOKEN_RE` on purpose, since a generated project has no legitimate reason to retain template delimiters in any marker-like shape, not merely ones that happen to be legal token syntax.

| Token | Computed in | Notes |
|---|---|---|
| `{{SUITE_NAME}}` | `token_map()` from `ProjectParams.suite_name` | legitimate bootstrap-time literal: `suiteName` is generation-time identity (see below), not mutable metadata that could go stale |
| `{{ROOT_NAMESPACE}}` | `token_map()` from `ProjectParams.root_namespace` | dot-separated C# namespace, e.g. `ExampleCompany.Vibeheim`; same generation-time identity guarantee |
| `{{ROOT_NAMESPACE_LOWER}}` | `token_map()`, `root_namespace.lower()` | |
| `{{PLUGIN_GUID_ROOT}}` | `token_map()` from `ProjectParams.plugin_guid_root` | currently unused in `template/`; kept because `pluginGuidRoot` is mutable metadata, so a future use must not embed it as a bootstrap-time literal the way the module catalog used to |
| `{{AUTHOR}}` | `token_map()` from `ProjectParams.author` | |
| `{{THUNDERSTORE_NAMESPACE}}` | `token_map()` from `ProjectParams.thunderstore_namespace` | |
| `{{MODULE_CATALOG_ROWS}}` | `module_catalog_rows()` | one Markdown table row per included module; no feature-specific rows, no literal `pluginGuidRoot`-derived GUIDs |
| `{{INCLUDED_MODULES_LIST}}` | `included_modules_bullets()` | bullet list of included runtime packages |
| `{{COMPATIBILITY_BOUNDARIES_LIST}}` | `compatibility_boundaries_bullets()` | bullet list of included modules' compatibility levels |
| `{{RUNTIME_MODULE_CONSTRAINTS_LIST}}` | `runtime_module_constraints_bullets()` | per-module side-boundary statements, one line per included optional module |
| `{{BOOTSTRAP_DIAGNOSTICS_MILESTONE}}` | `bootstrap_diagnostics_milestone_section()` | the full "Milestone 2 diagnostics" section, or `""` when Shared.Diagnostics is omitted; sits on its own template line with no adjacent blank lines (see the function's own docstring for why) |
| `{{BOOTSTRAP_MILESTONES_PROVEN_CLAUSE}}` | `bootstrap_milestones_proven_clause()` | inline clause naming which milestones must be proven before the first real feature |
| `{{RELEASE_PACKAGE_FAMILIES_LIST}}` | `release_package_family_bullets()` | bullet list mirroring `template/scripts/suite_metadata.py`'s `package_definitions()`, consumed by `template/scripts/package.py` |
| `{{SERVER_PACKAGE_FAMILY_LIST}}` | `server_package_family_bullets()` | bullet list of this generation's server-side package families; empty iff `has_server_package` is false |
| `{{CLIENT_PACKAGE_FAMILY_LIST}}` | `client_package_family_bullets()` | bullet list of this generation's client-side package families; empty iff `has_client_package` is false |
| `{{PENDING_RUNTIME_PROOF_LIST}}` | `pending_runtime_proof_bullets()` | root `README.md`'s "still requires the user's machine" bullets, Shared Diagnostics line conditional |
| `{{HARDENING_PENDING_PROOF_LIST}}` | `hardening_pending_proof_bullets()` | `docs/HARDENING_V3.md`'s analogous pending-proof bullets |
| `{{PROJECT_SPEC_MILESTONE2_BODY}}` | `project_spec_milestone2_body()` | `docs/PROJECT_SPEC.md`'s Milestone 2 body; a "not applicable" sentence when Shared.Diagnostics is omitted, so the heading/numbering never dangles |
| `{{INITIAL_MILESTONES_LIST}}` | `initial_milestones_bullets()` | `.context/state/current.md`'s numbered initial-milestones list, renumbered when Shared.Diagnostics is omitted |
| `{{CURRENT_STATE_BUILD_STATUS_LINES}}` | `current_state_build_status_lines()` | `.context/state/current.md`'s per-side build-status lines, one per side that actually has a package |
| `{{DEPLOY_TOPOLOGY_LINES}}` | `deploy_topology_lines()` | root `README.md`'s "Canonical development environment" diagram lines for each side that has a package; empty per side otherwise |
| `{{DEPLOY_COMMANDS_LIST}}` | `deploy_commands_lines()` | root `README.md`'s Deployment section commands, one per side that has a package |
| `{{DEPLOY_SIDE_NOTES_LIST}}` | `deploy_side_notes_lines()` | root `README.md`'s Deployment section side-membership prose, one line per side that has a package |

`suiteVersion`, `pluginGuidRoot`, `author`, `thunderstoreNamespace`, dependency pins (`jotunnVersion`, `bepInExPackVersion`, `netFrameworkReferenceAssembliesVersion`), and `csharpLanguageVersion` are mutable `suite.config.json` metadata and deliberately **not** tokens (beyond `{{PLUGIN_GUID_ROOT}}`'s unused, deliberately-non-prose reservation above): they can be edited and re-synchronized after generation (`scripts/suite_metadata.py sync`), so no `template/` prose file may embed their value as a bootstrap-time literal that `sync` cannot update -- `suite.config.json`/`build/Suite.Generated.props`/`SuiteConstants.Generated.cs` are the authoritative source by name instead. `suiteName` and `rootNamespace` are the opposite case: generation-time identity fixed in `suite.identity.lock.json`, so their bootstrap-time token substitution is permanent and correct by construction. See `docs/GENERATOR_ARCHITECTURE.md`'s "Generation-time identity/layout baseline".

Path token: `__ROOT_NAMESPACE__` — substring-replaced in path segments only (e.g. `src/__ROOT_NAMESPACE__.Common/` → `src/Vibeheim.Common/`), never inside file content.

## Adding a token

1. Add the value/derivation to `bootstrap/model.py`'s `token_map()` (or a new `DEPENDENCY_BASELINE` entry for a shared constant).
2. Add the token name to `bootstrap/render.py`'s `KNOWN_TOKENS`.
3. Use it in the relevant `template/` file(s).
4. Add a row to the table above.
5. Run `scripts/validate-template.sh`.

## Adding a new optional module

1. Extend `ProjectParams` (new `include_<module>: bool = True` field) and `ProjectModel`/`build_model()` in `bootstrap/model.py`. If the new field would let every optional module be disabled at once, keep `build_model()`'s "at least one runtime module must be enabled" check in sync -- a suite with no runtime module builds no BepInEx plugin at all (see "The empty-runtime invariant" below).
2. Add the module to `ProjectModel.modules`, `suite_config_dict()`, and `solution_text()`. If the module can affect `has_server_package`/`has_client_package` (i.e. its scope reaches `serverModules` and/or one of the client groups), update those two `ProjectModel` properties too.
3. Add the module's template directory under `template/src/__ROOT_NAMESPACE__.<Module>/`, register its files under a new key in `bootstrap/template_manifest.py`'s `OPTIONAL_TEMPLATE_FILES`, and add that key to `bootstrap/render.py`'s `OPTIONAL_GROUP_PRESENT`.
4. Add a CLI flag (`--no-<module>`) and interactive prompt in `bootstrap/create_project.py`.
5. Update every module-dependent rendering helper in `bootstrap/model.py` that enumerates modules by name (`module_catalog_rows()`, `included_modules_bullets()`, `compatibility_boundaries_bullets()`, `runtime_module_constraints_bullets()`, `release_package_family_bullets()`, etc.) so the new module appears there too -- see "Adding an optional documentation group" below for the general pattern.
6. Add fixture test coverage for both the included and omitted case (`tests/fixtures/`), including that `template/scripts/suite_metadata.py`'s `package_definitions()`, as consumed by `template/scripts/package.py`, does not emit an empty package for the omitted module.

## The empty-runtime invariant

Common is a shared library other plugins reference, not itself a BepInEx plugin. `bootstrap/model.py`'s `build_model()` rejects a `ProjectParams` selection with every optional module disabled, before any output directory is touched, and `template/scripts/suite_metadata.py`'s `validate()` independently rejects a `projects` map whose every entry has `scope: "common"` -- because `projects` can legitimately gain/lose entries after generation, a suite could otherwise be edited down to no runtime module post-generation and still pass `sync`/`check`. Keep both checks if a future module addition changes what "runtime" means; see `tests/bootstrap/test_model.py`'s `test_build_model_rejects_all_optional_modules_omitted` and `tests/template/test_solution_membership.py`'s `CommonOnlyRuntimeInvariantTests`.

A weaker, per-side form of the same invariant applies to `template/scripts/deploy.py`: `side_has_runtime_module()` rejects `--target server`/`--target client` when the current validated `packages` groups put no non-`common` project on that side (e.g. a ServerCore-only suite's `--target client`), before any destination is created, flocked, or written to -- otherwise deploying only `Common.dll` would create a deployment-ownership manifest for a side with no plugin to load it. This reads `packages` directly (not bootstrap-time module flags), so it stays correct after a supported post-generation structural edit. See `tests/template/test_deploy_side_availability.py`.

## Adding an optional documentation group

Not every module-dependent template file should be gated on a single module's presence -- `packaging/server/README.md` and `packaging/client/README.md` are gated on `ProjectModel.has_server_package`/`has_client_package` instead, because Shared.Diagnostics (a `sharedOptional` module) reaches *both* package sides even when ServerCore/Client are absent. `bootstrap/template_manifest.py`'s `OPTIONAL_TEMPLATE_FILES` supports this: `server_package_docs`/`client_package_docs` are ordinary optional groups, just keyed by a package-side predicate instead of a module-presence predicate, registered in `bootstrap/render.py`'s `OPTIONAL_GROUP_PRESENT` exactly like a module group. To add another optional documentation group:

1. Add the file(s) under `template/` and a new key + `frozenset` of paths to `OPTIONAL_TEMPLATE_FILES`.
2. Add the matching predicate (a `lambda m: ...` over `ProjectModel`) to `OPTIONAL_GROUP_PRESENT`. Prefer an existing `ProjectModel` property/method over a one-off inline condition so source-inclusion and prose-rendering can never independently drift, which is exactly how the original audited issue happened (source filtering existed; prose rendering didn't follow it).
3. For small conditional passages *within* an otherwise-always-rendered file (as opposed to the whole file being conditional), add a `bootstrap/model.py` function that renders the complete passage -- or `""` -- and wire it through `token_map()`/`KNOWN_TOKENS` like any other token; see "Adding a token" above. Do not build a generic Markdown conditional parser for this.
4. Add fixture coverage asserting the file exists/is absent for the right combinations, and that its rendered content never names a module/package family this generation doesn't have.
5. Update the token table and this file.

## Adding a new scalar generator input

1. Extend `ProjectParams` and `naming.py` with a validator if the input has format constraints.
2. Add it to `token_map()` if templates need it.
3. Add the CLI flag and interactive prompt in `create_project.py`.

## Deliberate duplication: `bootstrap/naming.py` vs `template/scripts/suite_metadata.py`

`bootstrap/naming.py`'s `validate_semver()`/`GUID_ROOT_RE`/`NAMESPACE_SEGMENT`, C# keyword set, `THUNDERSTORE_NAMESPACE_RE`, and portable path-component rules intentionally mirror the generated scripts' `validate_semver()`/`GUID_ROOT`/`NAMESPACE_SEGMENT`, C# keyword set, `THUNDERSTORE_NAMESPACE`, and `NAME_COMPONENT`. `validate_semver()` implements SemVer 2.0.0 syntax (https://semver.org) directly rather than as one regex — see `tests/bootstrap/test_naming.py` and `tests/template/test_naming_grammar.py`'s `BootstrapGeneratedGrammarAlignmentTests` for the shared case list that keeps both copies from drifting apart. A generated project must never import bootstrapper code — its own `suite_metadata.py check`/`sync` is the only thing that validates its `suite.config.json` at runtime, and it must do so independently even after a maintainer hand-edits the file — so the copies are kept in sync by convention, not by a shared dependency. Update both together when either changes.

`suite_metadata.py` additionally enforces path-containment and archive-safety rules (`contain`, `package.py`'s `validate_arcname`) that have no bootstrapper-side counterpart, because the bootstrapper never re-derives filesystem paths from arbitrary post-generation edits the way the generated project's own `sync`/`package.py` must.

`bootstrap/model.py`'s `identity_lock_dict()` (what generation writes into `suite.identity.lock.json`) and `template/scripts/suite_metadata.py`'s `IMMUTABLE_IDENTITY_FIELDS`/`validate_identity()` (what a generated project checks `suite.config.json` against) are a second deliberately-duplicated pair: both must agree on exactly which fields are generation-time identity/layout — currently `suiteName` and `rootNamespace` — or a generated project could accept an edit the bootstrapper's own baseline format doesn't expect, or vice versa. See `docs/GENERATOR_ARCHITECTURE.md`'s "Generation-time identity/layout baseline".

## `.ts` token rendering never trusts input grammar alone

`render_tree()` renders every `.ts` destination through `_ts_string_escape()` (JSON-string escaping of the substituted value, without its outer quotes) instead of raw substitution, because every current `{{TOKEN}}` use in a `.ts` file sits inside an existing double-quoted string literal (e.g. `label: "Build {{SUITE_NAME}}"` in `template/.omp/extensions/valheim-dev/index.ts`). This is defense-in-depth on top of, not a replacement for, each token's own grammar (`naming.validate_path_component()` for `SUITE_NAME`, etc.) — see `tests/bootstrap/test_render_ts_escaping.py`.

## Keeping `template/` generic

`template/` must stay a generic modular framework: no concrete gameplay features, no project-specific milestones. `docs/module-catalog.md`, `docs/PROJECT_SPEC.md`'s milestones, and `BOOTSTRAP_PROMPT.md` intentionally stop at "prove the scaffold and Shared Diagnostics architecture, then define the first real feature using `docs/features/TEMPLATE.md`" rather than naming any specific feature.
