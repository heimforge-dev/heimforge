"""Explicit manifest of every file `template/` is allowed to contain.

The filesystem contents of `template/` are not themselves the template
definition — this manifest is. `render_tree()` renders exactly these
files and nothing else; `validate_template()` fails if any of them is
missing or if `template/` contains anything not listed here. Adding a
file anywhere beneath `template/` without registering it below has no
effect on generated output, and fails template validation instead of
being silently ignored (see `docs/TEMPLATE_MAINTENANCE.md`).

Paths are relative to `template/`, forward-slash separated, using the
literal `__ROOT_NAMESPACE__` path segment for module-specific source
directories (substituted with the real root namespace at render time).
"""

from __future__ import annotations

import posixpath

# Rendered into every generated project, regardless of which optional
# modules are included.
REQUIRED_TEMPLATE_FILES: frozenset[str] = frozenset(
    {
        ".context/CONTEXT.md",
        ".context/_meta/schema.md",
        ".context/_templates/finding.md",
        ".context/findings/CONTEXT.md",
        ".context/findings/valheim-runtime.md",
        ".context/references/CONTEXT.md",
        ".context/references/architecture.md",
        ".context/references/networking.md",
        ".context/references/patching.md",
        ".context/references/project.md",
        ".context/references/testing.md",
        ".context/state/CONTEXT.md",
        ".context/state/current.md",
        ".editorconfig",
        ".env.example",
        ".gitignore",
        ".omp/extensions/valheim-dev/README.md",
        ".omp/extensions/valheim-dev/index.ts",
        ".omp/prompts/bootstrap-valheim.md",
        ".omp/skills/harmony-reverse-engineering/SKILL.md",
        ".omp/skills/valheim-modding/SKILL.md",
        ".omp/skills/valheim-networking/SKILL.md",
        ".omp/skills/valheim-release/SKILL.md",
        ".valheim/dev.json.example",
        "AGENTS.md",
        "BOOTSTRAP_PROMPT.md",
        "CHANGELOG.md",
        "Directory.Build.props",
        "Directory.Packages.props",
        "DoPrebuild.props",
        "Environment.props.example",
        "LICENSE.todo",
        "LICENSES/MIT-0.txt",
        "README.md",
        "docs/HARDENING_V3.md",
        "docs/PROJECT_SPEC.md",
        "docs/compatibility.md",
        "docs/decisions/0001-bepinex-jotunn.md",
        "docs/decisions/0002-module-topology.md",
        "docs/decisions/0003-network-compatibility.md",
        "docs/decisions/0004-persistence.md",
        "docs/dependencies.md",
        "docs/development.md",
        "docs/features/TEMPLATE.md",
        "docs/module-catalog.md",
        "docs/networking.md",
        "docs/patch-ledger.md",
        "docs/persistence.md",
        "docs/release.md",
        "docs/testing.md",
        "packaging/profiles/README.md",
        "packaging/shared/README.md",
        "scripts/bootstrap.sh",
        "scripts/build.sh",
        "scripts/check-game-update.sh",
        "scripts/dev_config.py",
        "scripts/deploy-client.sh",
        "scripts/deploy-server.sh",
        "scripts/deploy.py",
        "scripts/remote_deploy.py",
        "scripts/server_runtime.py",
        "scripts/package.py",
        "scripts/package.sh",
        "scripts/preflight.py",
        "scripts/preflight.sh",
        "scripts/refresh-references.sh",
        "scripts/suite_metadata.py",
        "scripts/update-game-stack.py",
        "scripts/test.sh",
        "src/__ROOT_NAMESPACE__.Common/Diagnostics/RuntimeDiagnostics.cs",
        "src/__ROOT_NAMESPACE__.Common/Modules/ModuleDescriptor.cs",
        "src/__ROOT_NAMESPACE__.Common/Modules/ModuleIds.cs",
        "src/__ROOT_NAMESPACE__.Common/Modules/ModuleScope.cs",
        "src/__ROOT_NAMESPACE__.Common/__ROOT_NAMESPACE__.Common.csproj",
        "tests/__ROOT_NAMESPACE__.Common.Tests/ModuleDescriptorTests.cs",
        "tests/__ROOT_NAMESPACE__.Common.Tests/RuntimeDiagnosticsTests.cs",
        "tests/__ROOT_NAMESPACE__.Common.Tests/__ROOT_NAMESPACE__.Common.Tests.csproj",
        "tests/scaffold/test_scaffold.py",
        "tools/README.md",
    }
)

# Rendered only when the matching `ProjectModel`/manifest predicate in
# `bootstrap/render.py`'s `OPTIONAL_GROUP_PRESENT` is satisfied: the three
# module-source groups (`server_core`, `client`, `shared_diagnostics`) gate on
# the matching optional module being present, and the two package-side doc
# groups (`server_package_docs`, `client_package_docs`) gate on
# `ProjectModel.has_server_package`/`has_client_package` -- whether that side
# actually has at least one package family to document. See
# `docs/TEMPLATE_MAINTENANCE.md` for how to add a new optional module or
# optional documentation group.
OPTIONAL_TEMPLATE_FILES: dict[str, frozenset[str]] = {
    "server_core": frozenset(
        {
            "src/__ROOT_NAMESPACE__.ServerCore/Core/FeatureRegistry.cs",
            "src/__ROOT_NAMESPACE__.ServerCore/Core/IServerFeature.cs",
            "src/__ROOT_NAMESPACE__.ServerCore/Plugin.cs",
            "src/__ROOT_NAMESPACE__.ServerCore/__ROOT_NAMESPACE__.ServerCore.csproj",
        }
    ),
    "client": frozenset(
        {
            "src/__ROOT_NAMESPACE__.Client/Plugin.cs",
            "src/__ROOT_NAMESPACE__.Client/__ROOT_NAMESPACE__.Client.csproj",
        }
    ),
    "shared_diagnostics": frozenset(
        {
            "src/__ROOT_NAMESPACE__.Shared.Diagnostics/DiagnosticRpc.cs",
            "src/__ROOT_NAMESPACE__.Shared.Diagnostics/Plugin.cs",
            "src/__ROOT_NAMESPACE__.Shared.Diagnostics/__ROOT_NAMESPACE__.Shared.Diagnostics.csproj",
        }
    ),
    "server_package_docs": frozenset({"packaging/server/README.md"}),
    "client_package_docs": frozenset({"packaging/client/README.md"}),
}


def all_template_files() -> frozenset[str]:
    """Every manifest-approved path, across all optional modules.

    This is the full approved surface `validate_template()` checks
    `template/` against — it is not parameterized by which modules a
    particular generation run includes.
    """
    result = set(REQUIRED_TEMPLATE_FILES)
    for paths in OPTIONAL_TEMPLATE_FILES.values():
        result |= paths
    return frozenset(result)


def invalid_manifest_path_reason(path: str) -> str | None:
    """Why `path` is not acceptable as a manifest entry, or `None` if it
    is: non-empty, POSIX-relative, normalized, and free of `.`/`..`
    components, absolute forms, and backslashes. This is what keeps
    production validation from merely trusting that the checked-in
    manifest happens to be well-formed.
    """
    if not path:
        return "is empty"
    if "\\" in path:
        return "contains a backslash"
    if path.startswith("/"):
        return "is an absolute path"
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "contains an empty, '.', or '..' path component"
    if posixpath.normpath(path) != path:
        return "is not a normalized POSIX-relative path"
    return None


def validate_manifest_structure() -> list[str]:
    """Structural validation of the manifest itself, independent of the
    filesystem: every entry must be a normalized, relative, POSIX-style
    path with no traversal or absolute forms, and no path may be listed
    in more than one group (required/optional overlap, or overlap between
    two optional modules).

    Exact duplicate literals within a single `frozenset` group are not
    checked for: Python's set representation already makes that state
    unobservable (a literal repeated within one `{...}` collapses to one
    element before this function ever runs). The collisions checked here
    are the ones a `frozenset` cannot eliminate by construction: the same
    path appearing in two different groups.
    """
    errors: list[str] = []
    owners: dict[str, list[str]] = {}

    def _check(path: str, group: str) -> None:
        reason = invalid_manifest_path_reason(path)
        if reason:
            errors.append(f"manifest entry {path!r} in {group!r} is invalid: {reason}")
            return
        owners.setdefault(path, []).append(group)

    for path in REQUIRED_TEMPLATE_FILES:
        _check(path, "required")
    for module, paths in OPTIONAL_TEMPLATE_FILES.items():
        for path in paths:
            _check(path, f"optional:{module}")

    for path, groups in owners.items():
        if len(groups) > 1:
            errors.append(f"manifest path {path!r} is listed in more than one group: {', '.join(groups)}")

    return errors
