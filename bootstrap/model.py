"""Generator data model: project parameters, derived module set, and
computed output artifacts (suite.config.json, the .sln, and template tokens).

suite.config.json and <RootNamespace>.sln are generated programmatically
here rather than templated, because their content structurally depends on
which optional modules are included.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from . import naming

DEPENDENCY_BASELINE = {
    "jotunn_version": "2.29.2",
    "bepinex_version": "5.4.2333",
    "netfx_reference_version": "1.0.3",
    "csharp_language_version": "10",
}


@dataclass(frozen=True)
class ProjectParams:
    suite_name: str
    root_namespace: str
    plugin_guid_root: str
    author: str
    thunderstore_namespace: str
    suite_version: str = "0.1.0"
    include_server_core: bool = True
    include_client: bool = True
    include_shared_diagnostics: bool = True


def validate_params(p: ProjectParams) -> None:
    naming.validate_path_component(p.suite_name, "suiteName")
    if len(p.suite_name) > naming.MAX_SUITE_NAME_LENGTH:
        raise naming.NamingError(
            f"suiteName must be at most {naming.MAX_SUITE_NAME_LENGTH} characters so the deployment "
            f"manifest filename stays within common filesystem limits (got {len(p.suite_name)})"
        )
    naming.validate_namespace(p.root_namespace, "rootNamespace")
    naming.validate_guid_root(p.plugin_guid_root)
    naming.validate_label(p.author, "author")
    naming.validate_thunderstore_namespace(p.thunderstore_namespace, "thunderstoreNamespace")
    naming.validate_semver(p.suite_version, "suiteVersion")
    build_model(p)


@dataclass(frozen=True)
class ModuleSpec:
    project_name: str
    scope: str  # "common" | "serverOnly" | "clientOnly" | "sharedOptional"
    target_framework: str  # "netstandard2.0" | "net48"
    guid_suffix: str  # "" for common, ".server", ".client", ".shared.diagnostics"


@dataclass(frozen=True)
class ProjectModel:
    params: ProjectParams
    common: ModuleSpec
    server_core: ModuleSpec | None
    client: ModuleSpec | None
    shared_diagnostics: ModuleSpec | None

    @property
    def modules(self) -> list[ModuleSpec]:
        result = [self.common]
        if self.server_core:
            result.append(self.server_core)
        if self.client:
            result.append(self.client)
        if self.shared_diagnostics:
            result.append(self.shared_diagnostics)
        return result

    @property
    def has_server_package(self) -> bool:
        """Whether `suite.config.json`'s `packages.serverModules` is
        non-empty for this model -- ServerCore contributes directly, and
        Shared.Diagnostics contributes because a `sharedOptional`/
        `sharedRequired` module always reaches the server side. Common
        alone never satisfies this."""
        return self.server_core is not None or self.shared_diagnostics is not None

    @property
    def has_client_package(self) -> bool:
        """Whether at least one client-side package group (`clientOnlyModules`,
        `requiredClientModules`, or `optionalClientModules`) is non-empty for
        this model -- Client contributes directly, and Shared.Diagnostics
        contributes because it always reaches the client side too."""
        return self.client is not None or self.shared_diagnostics is not None


def build_model(params: ProjectParams) -> ProjectModel:
    if not (params.include_server_core or params.include_client or params.include_shared_diagnostics):
        raise naming.NamingError(
            "at least one runtime module must be enabled: ServerCore, Client, or Shared.Diagnostics "
            "-- Common alone is a shared library, not a runtime BepInEx plugin, and produces no "
            "distributable mod suite"
        )
    ns = params.root_namespace
    common = ModuleSpec(f"{ns}.Common", "common", "netstandard2.0", "")
    server_core = (
        ModuleSpec(f"{ns}.ServerCore", "serverOnly", "net48", ".server") if params.include_server_core else None
    )
    client = ModuleSpec(f"{ns}.Client", "clientOnly", "net48", ".client") if params.include_client else None
    shared_diagnostics = (
        ModuleSpec(f"{ns}.Shared.Diagnostics", "sharedOptional", "net48", ".shared.diagnostics")
        if params.include_shared_diagnostics
        else None
    )
    model = ProjectModel(params, common, server_core, client, shared_diagnostics)
    for module in model.modules:
        naming.validate_path_component(module.project_name, "derived project name")
    return model


def suite_config_dict(model: ProjectModel) -> dict:
    p = model.params
    projects = {model.common.project_name: {"scope": "common", "targetFramework": "netstandard2.0"}}
    packages = {
        "commonModule": model.common.project_name,
        "serverModules": [],
        "requiredClientModules": [],
        "optionalClientModules": [],
        "clientOnlyModules": [],
    }
    if model.server_core:
        projects[model.server_core.project_name] = {"scope": "serverOnly", "targetFramework": "net48"}
        packages["serverModules"].append(model.server_core.project_name)
    if model.shared_diagnostics:
        projects[model.shared_diagnostics.project_name] = {"scope": "sharedOptional", "targetFramework": "net48"}
        packages["serverModules"].append(model.shared_diagnostics.project_name)
        packages["optionalClientModules"].append(model.shared_diagnostics.project_name)
    if model.client:
        projects[model.client.project_name] = {"scope": "clientOnly", "targetFramework": "net48"}
        packages["clientOnlyModules"].append(model.client.project_name)
    return {
        "schemaVersion": 1,
        "suiteName": p.suite_name,
        "rootNamespace": p.root_namespace,
        "pluginGuidRoot": p.plugin_guid_root,
        "author": p.author,
        "thunderstoreNamespace": p.thunderstore_namespace,
        "suiteVersion": p.suite_version,
        "csharpLanguageVersion": DEPENDENCY_BASELINE["csharp_language_version"],
        "jotunnVersion": DEPENDENCY_BASELINE["jotunn_version"],
        "bepInExPackVersion": DEPENDENCY_BASELINE["bepinex_version"],
        "netFrameworkReferenceAssembliesVersion": DEPENDENCY_BASELINE["netfx_reference_version"],
        "projects": projects,
        "packages": packages,
    }


def identity_lock_dict(model: ProjectModel) -> dict:
    """The generation-time identity/layout baseline `suite.identity.lock.json`
    records: exactly the `suite.config.json` fields that already determined
    physical repository structure -- or a persistent external identity --
    when generation ran, and nothing else, so this stays a minimal
    companion to `suite.config.json` rather than a second copy of it:

    - `rootNamespace`: the `.sln` filename and every handwritten/generated
      C# namespace were rendered from it.
    - `suiteName`: `template/scripts/deploy.py`'s deployment-manifest
      filename (`.<suiteName>.deploy-manifest.json`) is keyed on it, so an
      unauthorized change would start a second, unrelated ownership
      manifest for the same deployed DLLs instead of renaming the existing
      one.

    Derived from the same `suite_config_dict()` output written to disk, so
    the two can never disagree at generation time.
    `template/scripts/suite_metadata.py`'s `IMMUTABLE_IDENTITY_FIELDS` is
    the generated-project-side half of this contract; keep both in
    agreement.
    """
    cfg = suite_config_dict(model)
    return {"schemaVersion": cfg["schemaVersion"], "suiteName": cfg["suiteName"], "rootNamespace": cfg["rootNamespace"]}


PROJECT_TYPE_GUID = "{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}"


def _project_guid(suite_name: str, project_name: str) -> str:
    return "{" + str(uuid.uuid5(uuid.NAMESPACE_OID, f"{suite_name}:{project_name}")).upper() + "}"


def solution_text(model: ProjectModel) -> str:
    p = model.params
    entries = [
        (m.project_name, f"src\\{m.project_name}\\{m.project_name}.csproj", _project_guid(p.suite_name, m.project_name))
        for m in model.modules
    ]
    test_name = f"{p.root_namespace}.Common.Tests"
    entries.append((test_name, f"tests\\{test_name}\\{test_name}.csproj", _project_guid(p.suite_name, test_name)))

    lines = [
        "Microsoft Visual Studio Solution File, Format Version 12.00",
        "# Visual Studio Version 17",
        "VisualStudioVersion = 17.0.31903.59",
        "MinimumVisualStudioVersion = 10.0.40219.1",
    ]
    for name, path, guid in entries:
        lines += [f'Project("{PROJECT_TYPE_GUID}") = "{name}", "{path}", "{guid}"', "EndProject"]
    lines += [
        "Global",
        "\tGlobalSection(SolutionConfigurationPlatforms) = preSolution",
        "\t\tDebug|Any CPU = Debug|Any CPU",
        "\t\tRelease|Any CPU = Release|Any CPU",
        "\tEndGlobalSection",
        "\tGlobalSection(ProjectConfigurationPlatforms) = postSolution",
    ]
    for _name, _path, guid in entries:
        for cfg in ("Debug", "Release"):
            lines += [
                f"\t\t{guid}.{cfg}|Any CPU.ActiveCfg = {cfg}|Any CPU",
                f"\t\t{guid}.{cfg}|Any CPU.Build.0 = {cfg}|Any CPU",
            ]
    lines += ["\tEndGlobalSection", "EndGlobal"]
    return "\n".join(lines) + "\n"


def module_catalog_rows(model: ProjectModel) -> str:
    """The "Plugin" column identifies each module's BepInEx plugin by
    project/assembly name, not by its GUID: the GUID is
    `pluginGuidRoot + suffix`, and `pluginGuidRoot` is mutable
    post-generation (synchronized into `SuiteConstants.Generated.cs`), so
    baking its bootstrap-time value into this doc would go stale exactly
    like the original audited dependency-pin drift."""
    lines = [f"| Common primitives | {model.common.project_name} | Library | n/a | 1 | 1 | scaffold |"]
    if model.server_core:
        lines.append(
            f"| Server Core | {model.server_core.project_name} | SERVER_ONLY | server only | 1 | 1 | scaffold |"
        )
    if model.shared_diagnostics:
        lines.append(
            f"| Shared Diagnostics | {model.shared_diagnostics.project_name} | SHARED_OPTIONAL | no | 1 | 1 | scaffold |"
        )
    if model.client:
        lines.append(f"| Client | {model.client.project_name} | CLIENT_ONLY | no | 1 | 1 | scaffold |")
    return "\n".join(lines)


def included_modules_bullets(model: ProjectModel) -> str:
    lines: list[str] = []
    if model.server_core:
        lines.append(f"- `{model.server_core.project_name}`: server-only gameplay and administration features.")
    if model.shared_diagnostics:
        lines.append(
            f"- `{model.shared_diagnostics.project_name}`: independent two-sided module with its own compatibility requirements."
        )
    if model.client:
        lines.append(f"- `{model.client.project_name}`: client-only UI, visual, input, and convenience features.")
    lines.append(f"- `{model.common.project_name}`: shared pure code and protocol primitives.")
    return "\n".join(lines)


def compatibility_boundaries_bullets(model: ProjectModel) -> str:
    lines: list[str] = []
    if model.server_core:
        lines.append("- ServerCore: `NotEnforced / None`")
    if model.client:
        lines.append("- Client: `NotEnforced / None`")
    if model.shared_diagnostics:
        lines.append("- Shared.Diagnostics: `VersionCheckOnly / Minor`")
    return "\n".join(lines)


def runtime_module_constraints_bullets(model: ProjectModel) -> str:
    lines: list[str] = []
    if model.server_core:
        lines.append("ServerCore must not require clients to install it.")
    if model.client:
        lines.append("Client must not require servers to install it.")
    if model.shared_diagnostics:
        lines.append("Shared Diagnostics must be safe on both sides and must not alter persistent gameplay state.")
    return "\n".join(lines)


def bootstrap_diagnostics_milestone_section(model: ProjectModel) -> str:
    """The full "Milestone 2 diagnostics" section, sandwiched in blank-line
    markers so the surrounding template can place this token on its own
    line with no adjacent blank lines and still get correct spacing on
    both sides whether or not the section renders at all."""
    if not model.shared_diagnostics:
        return ""
    return (
        "\n"
        "## Milestone 2 diagnostics\n"
        "\n"
        "After Milestones 0 and 1 build/load cleanly, implement a minimal Jötunn CustomRPC diagnostic exchange "
        "proving:\n"
        "\n"
        "- client-to-server registration\n"
        "- server-side sender handling\n"
        "- server-to-client response\n"
        "- suite version reporting\n"
        "- module/protocol reporting\n"
        "- bounded useful logging\n"
        "- no persistent gameplay mutation\n"
        "\n"
        "Consult current Jötunn RPC documentation or Context7 and verify exact signatures before coding.\n"
    )


def bootstrap_milestones_proven_clause(model: ProjectModel) -> str:
    if model.shared_diagnostics:
        return (
            "Milestones 0-2 are proven (scaffold validated, plugins build/load correctly, "
            "Shared Diagnostics proves the CustomRPC/versioning plumbing)"
        )
    return "Milestones 0-1 are proven (scaffold validated, plugins build/load correctly)"


def server_package_family_bullets(model: ProjectModel) -> str:
    lines: list[str] = []
    if model.server_core:
        lines.append("- ServerCore")
    if model.has_server_package:
        lines.append("- ServerPack")
    return "\n".join(lines)


def client_package_family_bullets(model: ProjectModel) -> str:
    lines: list[str] = []
    if model.client:
        lines.append("- Client")
    if model.has_client_package:
        lines.append("- ClientPack")
    return "\n".join(lines)


def release_package_family_bullets(model: ProjectModel) -> str:
    """Mirrors `template/scripts/package.py`'s `package_definitions()`
    ordering and gating exactly, so this doc never lists a package family
    that generation cannot actually produce for this model."""
    lines: list[str] = []
    if model.server_core:
        lines.append("- ServerCore")
    if model.client:
        lines.append("- Client")
    if model.shared_diagnostics:
        lines.append("- one ZIP per Shared Module")
    if model.has_server_package:
        lines.append("- ServerPack")
    if model.has_client_package:
        lines.append("- ClientPack")
    return "\n".join(lines)


def pending_runtime_proof_bullets(model: ProjectModel) -> str:
    lines = [
        "- full Jötunn/Valheim plugin compilation",
        "- OMP extension load against the installed OMP package",
        "- dedicated-server plugin load",
        "- actual multiplayer compatibility behavior",
    ]
    if model.shared_diagnostics:
        lines.append("- Shared Diagnostics RPC implementation/runtime proof")
    lines.append("- any implemented feature's game-internal behavior, once a feature is chosen and built")
    return "\n".join(lines)


def hardening_pending_proof_bullets(model: ProjectModel) -> str:
    lines = [
        "- full plugin build against the user's actual Valheim/Jötunn installation",
        "- Jötunn publicized-reference generation on the user's WSL/Windows setup",
        "- OMP extension loading/type compatibility against the installed OMP package",
        "- Valheim dedicated-server plugin load",
        "- client/server connection matrix",
    ]
    if model.shared_diagnostics:
        lines.append("- Shared Diagnostics CustomRPC behavior")
    lines.append("- any implemented feature's game-internal behavior and assumptions")
    return "\n".join(lines)


def project_spec_milestone2_body(model: ProjectModel) -> str:
    if model.shared_diagnostics:
        return (
            "Shared Diagnostics proves CustomRPC request/response, module/version reporting, and multiplayer "
            "plumbing without changing gameplay state."
        )
    return "Not applicable: Shared.Diagnostics was not generated for this suite."


def initial_milestones_bullets(model: ProjectModel) -> str:
    lines = ["Repository/harness scaffold.", "Runtime plugin shells and side boundaries."]
    if model.shared_diagnostics:
        lines.append("Shared Diagnostics CustomRPC proof.")
    lines.append("First real feature (see `docs/features/TEMPLATE.md`).")
    lines.append("Packaging/profile generation.")
    return "\n".join(f"{i}. {line}" for i, line in enumerate(lines))


def current_state_build_status_lines(model: ProjectModel) -> str:
    lines: list[str] = []
    if model.has_server_package:
        lines.append("Server build: NOT RUN IN USER ENVIRONMENT")
    if model.has_client_package:
        lines.append("Client build: NOT RUN IN USER ENVIRONMENT")
    return "\n".join(lines)


def deploy_topology_lines(model: ProjectModel) -> str:
    lines: list[str] = []
    if model.has_client_package:
        lines.append("        +-- deploy client DLLs to Windows Valheim through /mnt/c/...")
    if model.has_server_package:
        lines.append("        +-- deploy server DLLs to the Linux/Docker dedicated server")
    return "\n".join(lines)


def deploy_commands_lines(model: ProjectModel) -> str:
    lines: list[str] = []
    if model.has_client_package:
        lines.append("./scripts/deploy-client.sh Debug")
    if model.has_server_package:
        lines.append("./scripts/deploy-server.sh Debug")
    return "\n".join(lines)


def _side_module_names(model: ProjectModel, side_module: ModuleSpec | None, side_module_name: str) -> str:
    """`Common` plus this side's own standard module (if present) plus
    `Shared.Diagnostics` (if present) -- the actual runtime modules this
    side receives, in the same short-name style used elsewhere in
    generated prose (e.g. `compatibility_boundaries_bullets()`). Never
    names a module this side doesn't actually have."""
    parts = ["Common"]
    if side_module:
        parts.append(side_module_name)
    if model.shared_diagnostics:
        parts.append("Shared.Diagnostics")
    return " + ".join(parts)


def deploy_side_notes_lines(model: ProjectModel) -> str:
    lines: list[str] = []
    if model.has_client_package:
        lines.append(f"Client receives {_side_module_names(model, model.client, 'Client')}.")
    if model.has_server_package:
        lines.append(f"Server receives {_side_module_names(model, model.server_core, 'ServerCore')}.")
    return "\n".join(lines)


def token_map(model: ProjectModel) -> dict[str, str]:
    p = model.params
    return {
        "SUITE_NAME": p.suite_name,
        "ROOT_NAMESPACE": p.root_namespace,
        "ROOT_NAMESPACE_LOWER": p.root_namespace.lower(),
        "PLUGIN_GUID_ROOT": p.plugin_guid_root,
        "AUTHOR": p.author,
        "THUNDERSTORE_NAMESPACE": p.thunderstore_namespace,
        "MODULE_CATALOG_ROWS": module_catalog_rows(model),
        "INCLUDED_MODULES_LIST": included_modules_bullets(model),
        "COMPATIBILITY_BOUNDARIES_LIST": compatibility_boundaries_bullets(model),
        "RUNTIME_MODULE_CONSTRAINTS_LIST": runtime_module_constraints_bullets(model),
        "BOOTSTRAP_DIAGNOSTICS_MILESTONE": bootstrap_diagnostics_milestone_section(model),
        "BOOTSTRAP_MILESTONES_PROVEN_CLAUSE": bootstrap_milestones_proven_clause(model),
        "RELEASE_PACKAGE_FAMILIES_LIST": release_package_family_bullets(model),
        "SERVER_PACKAGE_FAMILY_LIST": server_package_family_bullets(model),
        "CLIENT_PACKAGE_FAMILY_LIST": client_package_family_bullets(model),
        "PENDING_RUNTIME_PROOF_LIST": pending_runtime_proof_bullets(model),
        "HARDENING_PENDING_PROOF_LIST": hardening_pending_proof_bullets(model),
        "PROJECT_SPEC_MILESTONE2_BODY": project_spec_milestone2_body(model),
        "INITIAL_MILESTONES_LIST": initial_milestones_bullets(model),
        "CURRENT_STATE_BUILD_STATUS_LINES": current_state_build_status_lines(model),
        "DEPLOY_TOPOLOGY_LINES": deploy_topology_lines(model),
        "DEPLOY_COMMANDS_LIST": deploy_commands_lines(model),
        "DEPLOY_SIDE_NOTES_LIST": deploy_side_notes_lines(model),
    }
