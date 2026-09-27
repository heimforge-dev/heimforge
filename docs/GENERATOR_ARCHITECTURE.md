# Generator Architecture

## Modules

- `bootstrap/naming.py`: regex validators for identity inputs (`NamingError` on failure). Deliberately duplicates the shape of `template/scripts/suite_metadata.py`'s own `SEMVER`/`GUID_ROOT` regexes — see `docs/TEMPLATE_MAINTENANCE.md`.
- `bootstrap/model.py`: `ProjectParams` (raw generator inputs), `build_model()` (derives the included `ModuleSpec` set), `suite_config_dict()` and `solution_text()` (programmatically build `suite.config.json` and the `.sln`), and `token_map()` (the substitution dictionary for `template/`).
- `bootstrap/update_dependency_baseline.py`: root maintenance command for explicit Jötunn/BepInExPack default-baseline updates. It validates versions with `bootstrap/naming.py`, refuses pre-existing disagreement between `bootstrap/model.py` and `BOOTSTRAP_MANIFEST.json`, updates only those two authorities, and rolls back attempted writes on failure. It does not operate on generated projects or runtime installations; see `docs/TEMPLATE_MAINTENANCE.md`.
- `bootstrap/template_manifest.py`: the explicit, reviewed list of every file `template/` is allowed to contain (`REQUIRED_TEMPLATE_FILES` plus model-gated `OPTIONAL_TEMPLATE_FILES` groups for modules, package-side docs, portable agent tooling, and harness adapters). This — not `template/`'s filesystem contents — is the template definition; see "Why rendering never walks `template/`" below. `validate_manifest_structure()` checks the manifest itself (every entry a normalized, relative, POSIX path with no `.`/`..`/absolute forms, no path listed in more than one group) so production validation never merely trusts the checked-in manifest to be well-formed.
- `bootstrap/render.py`: `render_tree()` renders exactly the manifest-approved files for a given `ProjectModel` (required files plus each optional group whose model predicate is true), substituting `{{TOKEN}}` placeholders and `__ROOT_NAMESPACE__` path segments, and preserving the executable bit on `.sh` files. Every source is opened through `_open_source_file()`, which refuses to follow a symlink at any path component — including the final one — and refuses anything that isn't a plain regular file, so a symlink substituted for an approved path (or one of its parent directories) can never redirect rendering outside `template_dir`. `_render_plan()` containment- and collision-checks every rendered destination before anything is written: it must stay beneath the output root, must not collide with another source's destination, and must not collide with a path `generate()` writes programmatically (`suite.config.json`, `<RootNamespace>.sln`, `build/Suite.Generated.props`, the generated constants file, `packaging/profile-lock.json`). `validate_template()` is the template's own self-check (backs `scripts/validate-template.sh`): every manifest file must exist as a safe, physically-contained regular file, and every filesystem entry under `template/` — file or directory — must be in (or a required ancestor of) the manifest.
- `bootstrap/validate_generated.py`: post-generation checks on a rendered output directory. Every relative path (directory, file, binary or not) is scanned first: it has no legitimate brace syntax at all, so any raw `{{`/`}}` fails outright, alongside an unresolved `__ROOT_NAMESPACE__` path sentinel and leaked bootstrapper implementation identity (`IDENTITY_LEAK_PATTERNS`/`GUID_LEAK_PATTERN`) -- a binary `ValheimSuite.Common.dll` or a `ValheimSuite.ServerCore/` directory fails on its *path* alone, independent of content. Decodable UTF-8 text files are additionally scanned for the same path sentinel/identity categories in their *content*, plus a marker-*shaped* `{{...}}` leftover -- `UNRESOLVED_MARKER_RE` (ordinary balanced marker) or `MALFORMED_MARKER_RE` (one mangled by a single stray interior brace) rather than every doubled brace, since generated text can legitimately contain one (see `docs/TEMPLATE_MAINTENANCE.md`); binary content is never decoded or scanned -- its path was already fully validated, and treating arbitrary bytes as text would be false confidence, not a stronger check.
- `bootstrap/create_project.py`: CLI orchestration — interactive prompts or flags, safety checks on the output directory, source-template validation, and the summary printed to the user. `generate()` runs `validate_generated()` against a disposable copy of the rendered staging directory (not staging itself) so build/test commands like `dotnet test` — which create `bin/`/`obj/` wherever they run — can never leave artifacts in the tree that gets promoted; only the pristine, never-executed-against `staging_dir` is promoted.

## Why `suite.config.json` and the `.sln` are generated, not templated

Their content structurally depends on which optional modules (`ServerCore`, `Client`, `Shared.Diagnostics`) are included — project lists, package membership, and solution GUIDs all vary per generation. A static template file cannot express that conditionality without a second templating mechanism, so `bootstrap/model.py` builds both programmatically from the `ProjectModel` instead.

## Why rendering never walks `template/`

`render_tree()` takes its file list from `bootstrap/template_manifest.py`, never from `template.rglob("*")`. A file placed anywhere under `template/` without being added to the manifest is never rendered, and fails `validate_template()` instead of being silently ignored — this is what keeps ignored/untracked local state (`.env`, `__pycache__`, build output, credentials, game assemblies, editor/OS cruft) from ever reaching a generated project, regardless of whether it's accidentally left in a working tree. A manifest-approved *path string* is also not enough on its own: `_open_source_file()` re-validates, at the moment of reading, that the physical object at that path is a plain regular file with no symlinked component anywhere in its chain — so replacing an approved file (or one of its parent directories) with a symlink cannot redirect rendering to content outside `template_dir`. `validate_template()` rejects any filesystem entry under `template/` — file or directory, empty or not — that isn't required by the manifest, rather than silently ignoring it: an unexpected entry may be accidental local state or template drift and is never merely skipped. See `docs/TEMPLATE_MAINTENANCE.md` for how to add a manifest entry.

## Generation-time identity/layout baseline (`suite.identity.lock.json`)

`rootNamespace` and `suiteName` are the only `suite.config.json` fields that already determined something outside `suite.config.json` itself before `sync` ever runs: `rootNamespace` determined the `.sln` filename, every project directory under `src/`, and every handwritten/generated C# namespace, rendered in step 6/7 below; `suiteName` determined `template/scripts/deploy.py`'s deployment-manifest identity (`.<suiteName>.deploy-manifest.json`), which tracks DLL ownership at a deployment destination across repeated deploys. Nothing in `template/scripts/suite_metadata.py`'s `validate()` re-derives either from reality at check time (project existence is checked against the *configured project names*, which don't change if `rootNamespace` does; nothing reads the deployment destination during `check`), so an edited value was previously accepted by `sync`/`check`/`deploy.py` while the actual `.sln`/namespaces/deployment ownership silently stayed on the old value.

`bootstrap/model.py`'s `identity_lock_dict()` writes `suite.identity.lock.json` alongside `suite.config.json` at generation time, containing only `suiteName` and `rootNamespace` (`pluginGuidRoot`, `author`, `thunderstoreNamespace`, `suiteVersion`, dependency pins, and `csharpLanguageVersion` are all read dynamically at runtime or synchronized into a generated derivative, so they stay ordinary mutable metadata — see `docs/TEMPLATE_MAINTENANCE.md`). The lock is a closed schema (exactly `schemaVersion`/`suiteName`/`rootNamespace`, `schemaVersion` the JSON integer `1`, both names re-validated under their normal grammar) so a corrupted or hand-edited lock fails as a malformed lock, not as a misleading `suite.config.json` mismatch. The generated project's own `suite_metadata.py`'s `IMMUTABLE_IDENTITY_FIELDS`/`load_identity_lock()`/`validate_identity()` is the read-only counterpart: `sync`, `check`, `package.py`, and `deploy.py` all call `validate_identity()` after `validate()` and before touching any generated output or deployment destination, so a `suiteName`/`rootNamespace` edit is rejected with a controlled `MetadataError` naming the expected and attempted values, never silently accepted or silently rewritten into the lock file. `scripts/build.sh`/`scripts/test.sh` read the `.sln`/test-project path from this lock file rather than from `suite.config.json`, so they never trust a hand-edited, unvalidated `rootNamespace`.

### `projects` versus the canonical solution

`projects`/`packages` stay ordinary mutable structural metadata -- the architecture deliberately supports adding a new, physically-created project after generation -- but `suite_metadata.py`'s `validate_solution_membership()` (called alongside `validate_identity()`, after it, from the same four entry points) additionally requires `cfg['projects']`'s key set to exactly equal the C# projects `<rootNamespace>.sln` actually declares under `src/` (parsed narrowly from the bootstrapper's own `Project(...)`/`EndProject` line shape, ignoring the generated `tests/` project and any non-C#-project entry by path/type rather than by accident). Adding or removing a project is therefore a three-step, explicit workflow -- add/remove the `.csproj`, add/remove the matching `.sln` entry, then update `suite.config.json` and run `sync`/`check` -- never an automatic `.sln` rewrite. A mismatch in either direction (configured but unbuilt, or built but unconfigured) fails before any generated file or deployment/package output is touched.

### Evaluated artifact identity and bootstrap portability

Generated `suite_metadata.validate()` evaluates each canonical project with
MSBuild's structured `-getProperty` API for Debug and Release. It supplies the
complete global-property set empirically observed on projects under
`dotnet build <solution> -c <configuration>`:
`Configuration`, `Platform`, `BuildingSolutionFile`,
`CurrentSolutionConfigurationContents`, and the five standard `Solution*`
properties. The solution-configuration XML is derived from the already
validated canonical project entries and exact Debug/Release Any CPU mappings.
Metadata compares all returned globals plus project path, framework, and
assembly name, requiring `Platform=AnyCPU`, the canonical assembly name, and
the scope's framework (`netstandard2.0` for Common, `net48` for runtime
projects).

This is an external, evaluation-only observation channel: MSBuild emits the
structured JSON, no project target runs, and no report destination is exposed.
The metadata script, suite metadata, and validated solution are trusted;
project bodies, imported props/targets, project-defined targets, and
project-written reports are not. Package/deploy keep using their existing
metadata gate; neither owns a second evaluator.

Initial staging sync uses `--structural-only` because its generated props do not
exist yet. The scaffold suite also checks structural synchronization only.
Post-generation validation performs full certification when dotnet is present;
without it, validation explicitly reports that the MSBuild artifact contract
was not certified. Default metadata commands and all artifact-consuming
workflows fail closed without successful MSBuild evaluation. Generated portable
preflight still requires dotnet; "portable" skips machine-specific game checks,
not semantic project validation.

## Portable agent tooling and harness adapters

Portable agent tooling is an optional template group enabled by default. It contains `AGENTS.md`, `BOOTSTRAP_PROMPT.md`, `.context/**`, and standard project skills under `.agents/skills/**`. `--no-agent-tooling` omits that complete layer without changing the generated build, metadata, deployment, package, source, or test surface.

Harness-specific integrations are separate additive adapter groups. `--agent-adapter omp` currently adds only `.omp/extensions/valheim-dev/**` and `.omp/prompts/bootstrap-valheim.md`. Adapters require the portable agent layer, may delegate to the canonical repository scripts, and must not duplicate the portable skills/context or alter provider-neutral core files.

## Generated game-stack maintenance

Every suite renders `scripts/update-game-stack.py` and `scripts/refresh-references.sh`. The Python command owns offline runtime inspection, explicit Jötunn/BepInExPack pin updates, and the pinless `refresh` workflow; it reuses `suite_metadata.py` as the mutable metadata authority and `preflight.py` path parsing rather than duplicating configuration formats. Generated metadata synchronization is transactional across its complete output set. The shell entry point owns only the serialized Jötunn reference refresh: it validates metadata, derives the solution from `suite.identity.lock.json`, and runs prebuild with `-m:1` because Jötunn writes a shared publicized-assembly directory. `scripts/build.sh` remains the normal parallel build path; neither maintenance script owns deployment or lifecycle operations.

## Generated deployment architecture

The generated project parses development-local schema v1/v2 configuration in `scripts/dev_config.py`. `scripts/deploy.py` owns metadata validation, the transport-independent `DeploymentPlan`, the existing hardened retained-directory-FD deployment, and explicit restart orchestration. `scripts/remote_deploy.py` owns SSH/SCP invocation plus isolated POSIX-shell and Windows-PowerShell staging/promotion implementations. `scripts/server_runtime.py` owns the fixed status/log operations and dispatches them beside the configured local or remote Docker lifecycle without exposing transport logic to optional agent adapters.

Both local and SSH transports receive the same plan. SSH transport uploads into a unique sibling stage, verifies the exact filenames and SHA-256 hashes, compares the live ownership manifest against the pre-upload observation, and promotes only owned entries with a rollback backup. Lifecycle remains independent: `--restart` invokes `docker restart` only after deployment succeeds and reports lifecycle failures separately.

Remote safety is intentionally fail-safe rather than described as equivalent to the local retained-directory-FD guarantees. Separate SSH/SCP processes cannot retain one directory inode or `flock` across the full operation, so remote deployment rejects non-canonical/symlinked parents or Windows reparse points and documents that concurrent deployment to one suite directory is unsupported. Staged hash verification is point-in-time, rollback is best-effort if the remote process or host fails, and remote promotion does not claim local-equivalent `fsync` durability.

## Generation pipeline

1. `validate_params()` — reject malformed suite name, namespace, GUID root, author, Thunderstore namespace, or version; `validate_params()` also calls `build_model()`, which rejects a selection with every optional module (`ServerCore`, `Client`, `Shared.Diagnostics`) disabled -- Common alone builds no runtime BepInEx plugin, so this fails before the approved destination is ever touched (see `docs/TEMPLATE_MAINTENANCE.md`'s "The empty-runtime invariant").
2. Refuse an unsafe or non-empty output directory without `--force` (see `_safe_output_dir`/`_approve_destination` in `create_project.py`: rejects `/`, `$HOME`, the bootstrapper's own repository, and any ancestor of it).
3. `validate_template()` — the source template must pass its own manifest/forbidden-content check before anything is rendered; a failure raises `GenerationError` before the approved destination is ever touched.
4. `build_model()` — derive the concrete `ModuleSpec` set plus portable-agent and adapter selection (`Common` always; `ServerCore`/`Client`/`Shared.Diagnostics` per include flags; portable agent tooling on by default; adapters explicit).
5. `render_tree()` — render the manifest-approved files whose model predicates are enabled into a disposable staging directory, substituting tokens, after `_render_plan()` has containment- and collision-checked every destination.
6. Write the generated `suite.config.json`, `<RootNamespace>.sln`, and `suite.identity.lock.json`.
7. Run `python3 scripts/suite_metadata.py sync --structural-only` inside the staging directory to produce `build/Suite.Generated.props`, `src/<RootNamespace>.Common/SuiteConstants.Generated.cs`, and `packaging/profile-lock.json` — reusing the generated project's own logic rather than duplicating it here.
8. Copy the fully-rendered staging directory to a disposable validation directory and run `validate_generated()` against *that copy* — structural and (when possible) executable proof that the staged output is sound — then discard the copy regardless of outcome.
9. Promote the original, never-executed-against staging directory into the approved destination transactionally (see the transaction-safety guarantees documented at the top of `create_project.py`).
10. Print the summary: solution path, generated projects, validation result, and next steps.

## No templating dependency

The token vocabulary is small, closed, and enumerated in `docs/TEMPLATE_MAINTENANCE.md`. A flat `re.sub` substitution (`bootstrap/render.py`) is sufficient; Jinja2 or any other templating engine would be an unjustified dependency for this scope and would also risk leaking into the generated project's own tooling, which must stay fully independent of the bootstrapper.
