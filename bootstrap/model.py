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


def build_model(params: ProjectParams) -> ProjectModel:
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
    lines = [f"| Common primitives | {model.common.project_name} | Library | n/a | 1 | 1 | scaffold |"]
    if model.server_core:
        lines.append(
            f"| Server Core | {model.params.plugin_guid_root}.server | SERVER_ONLY | server only | 1 | 1 | scaffold |"
        )
    if model.shared_diagnostics:
        lines.append(
            f"| Shared Diagnostics | {model.params.plugin_guid_root}.shared.diagnostics | SHARED_OPTIONAL | no | 1 | 1 | scaffold |"
        )
    if model.client:
        lines.append(f"| Client | {model.params.plugin_guid_root}.client | CLIENT_ONLY | no | 1 | 1 | scaffold |")
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


def token_map(model: ProjectModel) -> dict[str, str]:
    p = model.params
    return {
        "SUITE_NAME": p.suite_name,
        "ROOT_NAMESPACE": p.root_namespace,
        "ROOT_NAMESPACE_LOWER": p.root_namespace.lower(),
        "PLUGIN_GUID_ROOT": p.plugin_guid_root,
        "AUTHOR": p.author,
        "THUNDERSTORE_NAMESPACE": p.thunderstore_namespace,
        "SUITE_VERSION": p.suite_version,
        "JOTUNN_VERSION": DEPENDENCY_BASELINE["jotunn_version"],
        "BEPINEX_VERSION": DEPENDENCY_BASELINE["bepinex_version"],
        "NETFX_REF_VERSION": DEPENDENCY_BASELINE["netfx_reference_version"],
        "CSHARP_LANG_VERSION": DEPENDENCY_BASELINE["csharp_language_version"],
        "MODULE_CATALOG_ROWS": module_catalog_rows(model),
        "INCLUDED_MODULES_LIST": included_modules_bullets(model),
        "COMPATIBILITY_BOUNDARIES_LIST": compatibility_boundaries_bullets(model),
    }
