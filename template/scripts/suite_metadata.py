#!/usr/bin/env python3
"""Validate and synchronize generated project metadata from suite.config.json."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import subprocess
import sys
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "suite.config.json"
IDENTITY_LOCK_PATH = ROOT / "suite.identity.lock.json"
GENERATED_PROPS = ROOT / "build" / "Suite.Generated.props"
PROFILE_LOCK = ROOT / "packaging" / "profile-lock.json"
_ROOT_ID = (ROOT.stat().st_dev, ROOT.stat().st_ino)
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

_UNSET = object()

GUID_ROOT = re.compile(r"^[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)+\Z")
VALID_SCOPES = {"common", "serverOnly", "clientOnly", "sharedOptional", "sharedRequired"}

# bootstrap/model.py's solution_text() -- the only writer of
# <rootNamespace>.sln -- emits exactly one MSBuild project-entry line per
# project, followed by a bare "EndProject" line:
#   Project("{TYPE-GUID}") = "Name", "path\to\Name.csproj", "{PROJECT-GUID}"
#   EndProject
# This backs a narrow state-machine parser for that specific block
# shape, not a general .sln grammar -- solution folders, nested
# projects, and other section types are out of scope because the
# bootstrapper never emits them, but a *malformed* one (missing
# EndProject, a Project(...) opened before a prior one closed) is still
# actively rejected rather than silently misparsed.
SOLUTION_PROJECT_LINE = re.compile(
    r'^Project\("(?P<type_guid>\{[0-9A-Fa-f-]+\})"\)\s*=\s*'
    r'"(?P<name>[^"]*)",\s*"(?P<path>[^"]*)",\s*"(?P<project_guid>\{[0-9A-Fa-f-]+\})"\s*\Z'
)
# The standard MSBuild "C# project" project-type GUID -- see
# bootstrap/model.py's PROJECT_TYPE_GUID, which every generated project
# entry uses. Compared case-insensitively: Visual Studio/dotnet accept
# either case, so a lowercase GUID is still a real C# project entry, not
# an "unrelated" one. A solution folder (a different, well-known type
# GUID) or any other project type is deliberately not one of "our"
# projects regardless of case.
CSHARP_PROJECT_TYPE_GUID = "{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}"

# The four package/deployment membership groups from suite.config.json's
# "packages" object. Deployment and package definitions read these same
# arrays; SCOPE_PACKAGE_GROUPS defines their exact membership.
PACKAGE_GROUPS = ("serverModules", "requiredClientModules", "optionalClientModules", "clientOnlyModules")

# The exact set of package/deployment groups a project's declared
# compatibility scope requires it to belong to -- no more, no less. A
# project must appear in every listed group and in none of the others.
SCOPE_PACKAGE_GROUPS: dict[str, frozenset[str]] = {
    "common": frozenset(),
    "serverOnly": frozenset({"serverModules"}),
    "sharedRequired": frozenset({"serverModules", "requiredClientModules"}),
    "sharedOptional": frozenset({"serverModules", "optionalClientModules"}),
    "clientOnly": frozenset({"clientOnlyModules"}),
}

# The Thunderstore namespace charset (reviewer-verified contract): max 64
# characters; first and last character alphanumeric; internal characters
# alphanumeric or '_'. Distinct from the looser package-name charset at
# https://wiki.thunderstore.io/mods/creating-a-package, which allows '_'
# at the edges -- namespaces do not.
THUNDERSTORE_NAMESPACE_MAX_LENGTH = 64
THUNDERSTORE_NAMESPACE = re.compile(r"^[A-Za-z0-9]+(?:[A-Za-z0-9_]*[A-Za-z0-9])?\Z")

# SemVer 2.0.0 (https://semver.org): MAJOR.MINOR.PATCH numeric core with no
# leading zeroes; optional dot-separated prerelease identifiers (numeric
# ones may not have leading zeroes); optional dot-separated build-metadata
# identifiers (leading zeroes allowed there). Syntax only -- no ordering.
_SEMVER_CORE_RE = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_SEMVER_IDENT_RE = re.compile(r"^[0-9A-Za-z-]+\Z")

# A single, portable filesystem path component: every value that becomes a
# directory/file name segment (project names, target framework monikers) or
# a name embedded in package/archive paths (suiteName). The charset alone
# rules out '/', '\\', '..', leading/trailing whitespace, control
# characters, and empty values; reserved Windows device names are rejected
# separately since the charset can't express that.
NAME_COMPONENT = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9._-]*[A-Za-z0-9_])?\Z")
_RESERVED_DEVICE_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{d}" for d in "123456789"),
    *(f"LPT{d}" for d in "123456789"),
}

# scripts/deploy.py's deployment manifest filename is
# f".{suiteName}.deploy-manifest.json" -- 1 leading dot + suiteName + the
# 21-character ".deploy-manifest.json" suffix. Bounding suiteName at 233
# ASCII bytes keeps that rendered filename at exactly 255 bytes, the
# common POSIX/NTFS single-path-component limit, so deployment never
# discovers an oversized suiteName as a late ENAMETOOLONG failure.
MAX_SUITE_NAME_LENGTH = 233

# A single dot-separated C# namespace segment: must be usable as an
# ordinary, unescaped C# identifier.
NAMESPACE_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")
CSHARP_KEYWORDS = {
    "abstract", "as", "base", "bool", "break", "byte", "case", "catch", "char",
    "checked", "class", "const", "continue", "decimal", "default", "delegate",
    "do", "double", "else", "enum", "event", "explicit", "extern", "false",
    "finally", "fixed", "float", "for", "foreach", "goto", "if", "implicit",
    "in", "int", "interface", "internal", "is", "lock", "long", "namespace",
    "new", "null", "object", "operator", "out", "override", "params",
    "private", "protected", "public", "readonly", "ref", "return", "sbyte",
    "sealed", "short", "sizeof", "stackalloc", "static", "string", "struct",
    "switch", "this", "throw", "true", "try", "typeof", "uint", "ulong",
    "unchecked", "unsafe", "ushort", "using", "virtual", "void", "volatile",
    "while",
}


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value)


class MetadataError(RuntimeError):
    pass


def load_config() -> dict:
    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8")
        cfg = json.loads(raw)
    except FileNotFoundError as exc:
        raise MetadataError(f"Missing {CONFIG_PATH.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise MetadataError(f"Invalid JSON in {CONFIG_PATH.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(cfg, dict):
        raise MetadataError("suite.config.json must contain a JSON object")
    return cfg


# The exact set of `suite.config.json` fields that are generation-time
# identity/layout, not editable mutable metadata: `rootNamespace` already
# determined the `.sln` filename, every project directory under `src/`,
# and every handwritten/generated C# namespace when `render_tree()` ran;
# `suiteName` already determined the deployment-manifest identity
# (`.<suiteName>.deploy-manifest.json` in `deploy.py`'s `manifest_name()`)
# that tracks which DLLs this suite owns at a deployment destination --
# changing it post-deployment would start a second, unrelated ownership
# manifest for the same DLLs rather than renaming the existing one.
# Nothing in `validate()` re-derives either field from reality at check
# time, so an edited value is never independently caught the way an
# unknown/missing project already is -- this baseline closes that gap.
# Mirrors `bootstrap/model.py`'s `identity_lock_dict()`; keep both in sync.
IMMUTABLE_IDENTITY_FIELDS = ("suiteName", "rootNamespace")

# suite.identity.lock.json is a closed schema: exactly these keys, no more
# and no less. An extra key could hide a field a future reader assumes is
# also checked; a missing one is caught below regardless.
IDENTITY_LOCK_KEYS = frozenset({"schemaVersion", *IMMUTABLE_IDENTITY_FIELDS})


def load_identity_lock() -> dict:
    try:
        raw = IDENTITY_LOCK_PATH.read_text(encoding="utf-8")
        lock = json.loads(raw)
    except FileNotFoundError as exc:
        raise MetadataError(
            f"Missing {IDENTITY_LOCK_PATH.relative_to(ROOT)}: every generated suite carries its "
            "generation-time identity/layout baseline; regenerate the suite if this file was deleted"
        ) from exc
    except json.JSONDecodeError as exc:
        raise MetadataError(f"{IDENTITY_LOCK_PATH.relative_to(ROOT)} is malformed: invalid JSON: {exc}") from exc
    if not isinstance(lock, dict):
        raise MetadataError(f"{IDENTITY_LOCK_PATH.relative_to(ROOT)} is malformed: must contain a JSON object")
    missing = sorted(IDENTITY_LOCK_KEYS - set(lock))
    extra = sorted(set(lock) - IDENTITY_LOCK_KEYS)
    if missing or extra:
        problems = []
        if missing:
            problems.append(f"missing {missing}")
        if extra:
            problems.append(f"unexpected {extra}")
        raise MetadataError(
            f"{IDENTITY_LOCK_PATH.relative_to(ROOT)} is malformed: must contain exactly the keys "
            f"{sorted(IDENTITY_LOCK_KEYS)}: " + "; ".join(problems)
        )
    if type(lock["schemaVersion"]) is not int or lock["schemaVersion"] != 1:
        raise MetadataError(
            f"{IDENTITY_LOCK_PATH.relative_to(ROOT)} is malformed: schemaVersion must be the JSON integer 1, "
            f"got {lock['schemaVersion']!r}"
        )
    try:
        suite_name = validate_path_component(lock["suiteName"], "suiteName")
        if len(suite_name) > MAX_SUITE_NAME_LENGTH:
            raise MetadataError(f"suiteName must be at most {MAX_SUITE_NAME_LENGTH} characters (got {len(suite_name)})")
        validate_namespace(lock["rootNamespace"], "rootNamespace")
    except MetadataError as exc:
        raise MetadataError(f"{IDENTITY_LOCK_PATH.relative_to(ROOT)} is malformed: {exc}") from exc
    return lock


def validate_identity(cfg: dict) -> None:
    """Reject any `suite.config.json` edit to a generation-time
    identity/layout field before `sync`/`check`/packaging act on it.
    Call after `validate(cfg)` so a syntactically invalid value is still
    reported as an invalid value, not as an immutable-field change."""
    lock = load_identity_lock()
    for field in IMMUTABLE_IDENTITY_FIELDS:
        expected = lock[field]
        actual = cfg.get(field)
        if actual != expected:
            raise MetadataError(
                f"{field} is immutable after generation: expected {expected}, got {actual}; "
                "regenerate the suite (or create a new project) to change repository identity/layout"
            )


def require_string(cfg: dict, key: str) -> str:
    value = cfg.get(key)
    if not isinstance(value, str) or not value or value != value.strip() or _has_control_chars(value):
        raise MetadataError(f"{key} must be a non-empty, trimmed string with no control characters")
    return value


# Unicode categories rejected from free-text display labels: Cc (control,
# including C0/DEL/C1 such as U+0085 NEXT LINE and U+009F), Zl (line
# separator, U+2028), and Zp (paragraph separator, U+2029) -- every one
# of them can corrupt a single-line generated text/props/JSON context.
_REJECTED_LABEL_CATEGORIES = frozenset({"Cc", "Zl", "Zp"})


def _is_xml_1_0_char(codepoint: int) -> bool:
    """XML 1.0 `Char` production (https://www.w3.org/TR/xml/#charsets):
    `#x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]`.
    `author` is emitted into `build/Suite.Generated.props` (XML), so every
    accepted character must additionally satisfy this -- independent of
    the Cc/Zl/Zp category rule above, which already excludes TAB/CR/LF
    and every other control/separator but not the surrogate range
    (category `Cs`) or the U+FFFE/U+FFFF noncharacters (category `Cn`)."""
    return (
        codepoint in (0x9, 0xA, 0xD)
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def validate_label(cfg: dict, key: str) -> str:
    """Free-text display metadata (author): safely embeddable anywhere
    it is used (XML/JSON-escaped at each generation site) but never a
    path or an external-platform identifier, so ordinary spaces, Unicode
    letters, quotes, apostrophes, ampersands, and angle brackets remain
    allowed. Not for fields with a closed external grammar -- see
    `validate_thunderstore_namespace`."""
    value = require_string(cfg, key)
    if "/" in value or "\\" in value:
        raise MetadataError(f"{key} must not contain a path separator: {value!r}")
    if any(unicodedata.category(ch) in _REJECTED_LABEL_CATEGORIES for ch in value):
        raise MetadataError(
            f"{key} must not contain Unicode control/line-separator/paragraph-separator characters: {value!r}"
        )
    if any(not _is_xml_1_0_char(ord(ch)) for ch in value):
        raise MetadataError(f"{key} must not contain characters invalid in XML 1.0 character data: {value!r}")
    return value


def validate_thunderstore_namespace(value: str, field: str) -> str:
    """The Thunderstore namespace charset: ASCII alphanumeric first and
    last character, alphanumeric or '_' internally, at most
    `THUNDERSTORE_NAMESPACE_MAX_LENGTH` characters. Deliberately not
    `validate_label`: this is an external-platform identifier with its
    own closed grammar, not free-text display metadata."""
    if (
        not isinstance(value, str)
        or len(value) > THUNDERSTORE_NAMESPACE_MAX_LENGTH
        or not THUNDERSTORE_NAMESPACE.match(value)
    ):
        raise MetadataError(
            f"{field} must be 1-{THUNDERSTORE_NAMESPACE_MAX_LENGTH} ASCII letters/digits/underscore, "
            f"starting and ending with a letter or digit: {value!r}"
        )
    return value


def _valid_semver_prerelease_identifier(ident: str) -> bool:
    if not _SEMVER_IDENT_RE.match(ident):
        return False
    return not (ident.isdigit() and len(ident) > 1 and ident[0] == "0")


def validate_semver(value: str, field: str) -> str:
    """SemVer 2.0.0 syntax only (https://semver.org): a three-component,
    non-leading-zero numeric core, an optional dot-separated prerelease
    (numeric identifiers may not have leading zeroes), and an optional
    dot-separated build-metadata suffix (leading zeroes allowed there).
    Ordering/precedence is intentionally not implemented."""
    if not isinstance(value, str) or not value:
        raise MetadataError(f"{field} is not valid SemVer 2.0.0 syntax: {value!r}")
    core_and_prerelease, has_build, build = value.partition("+")
    core, has_prerelease, prerelease = core_and_prerelease.partition("-")
    if (
        not _SEMVER_CORE_RE.match(core)
        or (has_prerelease and not all(_valid_semver_prerelease_identifier(i) for i in prerelease.split(".")))
        or (has_build and not all(_SEMVER_IDENT_RE.match(i) for i in build.split(".")))
    ):
        raise MetadataError(f"{field} is not valid SemVer 2.0.0 syntax: {value!r}")
    return value


def validate_component_length(value: str, field: str) -> str:
    if len(value.encode("utf-8")) > 255:
        raise MetadataError(f"{field} exceeds the portable 255-byte filesystem component limit")
    return value


def validate_path_component(value: str, field: str) -> str:
    """A value that becomes exactly one filesystem or archive path segment:
    reject anything that isn't a plain, portable name."""
    if not isinstance(value, str) or not NAME_COMPONENT.match(value):
        raise MetadataError(
            f"{field} must be a single portable path component: letters, digits, "
            f"'.', '_', '-' only, starting and ending with a letter, digit, or underscore: {value!r}"
        )
    if value.split(".", 1)[0].upper() in _RESERVED_DEVICE_NAMES:
        raise MetadataError(f"{field} must not use a reserved platform device name: {value!r}")
    validate_component_length(value, field)
    return value


def validate_namespace(value: str, field: str) -> str:
    """A dot-separated C# namespace: every segment must be a valid, ordinary
    (unescaped) C# identifier. Reserved keywords are rejected outright
    rather than generating an escaped `@keyword` namespace segment."""
    if not isinstance(value, str) or not value:
        raise MetadataError(f"{field} must be a non-empty string")
    for segment in value.split("."):
        if not NAMESPACE_SEGMENT.match(segment):
            raise MetadataError(
                f"{field} must be a dot-separated sequence of valid C# identifiers "
                f"(e.g. ExampleCompany.Vibeheim), each starting with a letter or underscore: {value!r}"
            )
        if segment in CSHARP_KEYWORDS:
            raise MetadataError(f"{field} segment {segment!r} is a reserved C# keyword: {value!r}")
    return value


def _relative_parts(path: Path, root: Path, *, error_cls: type[Exception]) -> tuple[str, ...]:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise error_cls(f"refusing to write outside {root}: {path}") from exc
    if any(part in ("", ".", "..") for part in relative.parts):
        raise error_cls(f"refusing unsafe path beneath {root}: {path}")
    return relative.parts


def _reject_symlink_components(path: Path, anchor: Path, *, error_cls: type[Exception]) -> None:
    current = anchor
    for part in _relative_parts(path, anchor, error_cls=error_cls):
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            return
        except OSError as exc:
            raise error_cls(f"cannot inspect generated path {current}: {exc}") from exc
        if stat.S_ISLNK(mode):
            raise error_cls(f"refusing symlinked generated path: {current}")


def contain(path: Path, root: Path, *, error_cls: type[Exception] = MetadataError) -> Path:
    """Require a write target to remain under its logical root and the
    generated repository, without following redirected path components."""
    path = path.absolute()
    root = root.absolute()
    repository = ROOT
    try:
        _relative_parts(root, repository, error_cls=error_cls)
    except error_cls:
        repository = root

    _relative_parts(root, repository, error_cls=error_cls)
    _relative_parts(path, root, error_cls=error_cls)
    _reject_symlink_components(path, repository, error_cls=error_cls)

    resolved = path.resolve()
    root_resolved = root.resolve()
    repository_resolved = repository.resolve()
    _relative_parts(root_resolved, repository_resolved, error_cls=error_cls)
    _relative_parts(resolved, root_resolved, error_cls=error_cls)
    _relative_parts(resolved, repository_resolved, error_cls=error_cls)
    return path


def validate(cfg: dict, release: bool = False, *, structural_only: bool = False) -> None:
    if type(cfg.get("schemaVersion")) is not int or cfg.get("schemaVersion") != 1:
        raise MetadataError("schemaVersion must be the JSON integer 1")

    suite_name = validate_path_component(require_string(cfg, "suiteName"), "suiteName")
    if len(suite_name) > MAX_SUITE_NAME_LENGTH:
        raise MetadataError(
            f"suiteName must be at most {MAX_SUITE_NAME_LENGTH} characters so the deployment manifest "
            f"filename stays within common filesystem limits (got {len(suite_name)})"
        )
    validate_namespace(require_string(cfg, "rootNamespace"), "rootNamespace")
    guid_root = require_string(cfg, "pluginGuidRoot")
    author = validate_label(cfg, "author")
    thunderstore_namespace = validate_thunderstore_namespace(
        require_string(cfg, "thunderstoreNamespace"), "thunderstoreNamespace"
    )
    suite_version = require_string(cfg, "suiteVersion")
    require_string(cfg, "csharpLanguageVersion")
    jotunn_version = require_string(cfg, "jotunnVersion")
    bepinex_version = require_string(cfg, "bepInExPackVersion")
    reference_version = require_string(cfg, "netFrameworkReferenceAssembliesVersion")

    validate_semver(suite_version, "suiteVersion")
    for key, value in (("jotunnVersion", jotunn_version), ("bepInExPackVersion", bepinex_version), ("netFrameworkReferenceAssembliesVersion", reference_version)):
        validate_semver(value, key)
    if not GUID_ROOT.match(guid_root):
        raise MetadataError(f"pluginGuidRoot has invalid syntax: {guid_root}")

    projects = cfg.get("projects")
    if not isinstance(projects, dict) or not projects:
        raise MetadataError("projects must be a non-empty object")
    for project, item in projects.items():
        validate_path_component(project, "project name")
        if not isinstance(item, dict):
            raise MetadataError(f"projects.{project} must be an object")
        scope = item.get("scope")
        tfm = item.get("targetFramework")
        if not isinstance(scope, str) or scope not in VALID_SCOPES:
            raise MetadataError(f"projects.{project}.scope must be one of {sorted(VALID_SCOPES)}")
        if not isinstance(tfm, str):
            raise MetadataError(f"projects.{project}.targetFramework must be a non-empty string")
        validate_path_component(tfm, f"projects.{project}.targetFramework")
        expected_tfm = "netstandard2.0" if scope == "common" else "net48"
        if tfm != expected_tfm:
            raise MetadataError(f"projects.{project}.targetFramework must be {expected_tfm} for scope {scope}")
        validate_component_length(f"{project}.csproj", "project filename")
        validate_component_length(f"{project}.dll", "assembly filename")
        validate_component_length(f"{project}.GeneratedMSBuildEditorConfig.editorconfig", "MSBuild generated filename")
    _reject_case_collisions(projects, "project names")
    _reject_case_collisions((f"src/{p}/{p}.csproj" for p in projects), "canonical source paths")
    _reject_case_collisions((f"{p}.dll" for p in projects), "assembly filenames")

    packages = cfg.get("packages")
    if not isinstance(packages, dict):
        raise MetadataError("packages must be an object")
    common = packages.get("commonModule")
    if not isinstance(common, str) or common not in projects or projects[common]["scope"] != "common":
        raise MetadataError("packages.commonModule must identify the project with scope=common")
    if [project for project, item in projects.items() if item["scope"] == "common"] != [common]:
        raise MetadataError("exactly one project must have scope=common and be packages.commonModule")

    group_values: dict[str, list[str]] = {}
    for group in PACKAGE_GROUPS:
        values = packages.get(group)
        if not isinstance(values, list):
            raise MetadataError(f"packages.{group} must be an array")
        if not all(isinstance(project, str) for project in values):
            raise MetadataError(f"packages.{group} must contain project-name strings")
        if len(values) != len(set(values)):
            raise MetadataError(f"packages.{group} contains duplicates")
        for project in values:
            if project not in projects:
                raise MetadataError(f"packages.{group} references unknown project {project}")
        group_values[group] = values

    # Every configured project's membership across the four groups must
    # match exactly what its declared scope requires -- not merely a
    # superset. This is what rejects a module silently disappearing from a
    # side its scope requires (e.g. a sharedOptional module omitted from
    # optionalClientModules) as well as a module placed in an incompatible
    # group (e.g. a clientOnly module appearing in serverModules).
    for project, item in projects.items():
        scope = item["scope"]
        required_groups = SCOPE_PACKAGE_GROUPS[scope]
        actual_groups = {group for group in PACKAGE_GROUPS if project in group_values[group]}
        if actual_groups != required_groups:
            missing = sorted(required_groups - actual_groups)
            extra = sorted(actual_groups - required_groups)
            problems = []
            if missing:
                problems.append(f"must appear in {' and '.join(missing)}")
            if extra:
                problems.append(f"must not appear in {' and '.join(extra)}")
            raise MetadataError(f"project {project} with scope {scope} " + "; ".join(problems))

    # A suite with only `common`-scope projects builds no runtime BepInEx
    # plugin at all -- Common is a shared library other plugins reference,
    # not itself a plugin. `projects` can legitimately gain/lose entries
    # after generation (see the module-membership contract above), so this
    # is re-checked here rather than only once at bootstrap time.
    if all(item["scope"] == "common" for item in projects.values()):
        raise MetadataError(
            "at least one configured project must have a runtime scope other than common "
            "(serverOnly, clientOnly, sharedOptional, or sharedRequired); a suite with only "
            "common-scope projects produces no runtime BepInEx plugin"
        )

    validate_component_length(f"{cfg['rootNamespace']}.sln", "solution filename")
    validate_component_length(
        f"{cfg['rootNamespace']}.Common.Tests.GeneratedMSBuildEditorConfig.editorconfig", "test MSBuild generated filename"
    )
    validate_component_length(f".{suite_name}.deploy-manifest.json", "deployment manifest")
    definitions = package_definitions(cfg)
    _reject_case_collisions((name for name, _modules, _kind in definitions), "package output names")
    for name, _modules, _kind in definitions:
        validate_component_length(f"{name}-{suite_version}.zip", "package filename")

    for project, item in projects.items():
        csproj = ROOT / "src" / project / f"{project}.csproj"
        if not csproj.exists():
            raise MetadataError(f"Configured project is missing: {csproj.relative_to(ROOT)}")
        try:
            tree = ET.parse(csproj)
        except ET.ParseError as exc:
            raise MetadataError(f"Invalid MSBuild XML in {csproj.relative_to(ROOT)}: {exc}") from exc
        target = tree.find(".//TargetFramework")
        assembly = tree.find(".//AssemblyName")
        if target is None or (target.text or "").strip() != item["targetFramework"]:
            actual = None if target is None else (target.text or "").strip()
            raise MetadataError(f"{project} TargetFramework is {actual!r}, expected {item['targetFramework']!r}")
        if assembly is None or (assembly.text or "").strip() != project:
            actual = None if assembly is None else (assembly.text or "").strip()
            raise MetadataError(f"{project} AssemblyName is {actual!r}, expected {project!r}")

    if release:
        bad = []
        if "TODO" in author.upper():
            bad.append("author")
        if "TODO" in thunderstore_namespace.upper():
            bad.append("thunderstoreNamespace")
        if guid_root.startswith("com.example."):
            bad.append("pluginGuidRoot")

        license_path = ROOT / "LICENSE"
        try:
            license_info = license_path.lstat()
        except FileNotFoundError:
            bad.append("LICENSE")
        else:
            if not stat.S_ISREG(license_info.st_mode):
                bad.append("LICENSE")
            else:
                try:
                    if not license_path.read_text(encoding="utf-8").strip():
                        bad.append("LICENSE")
                except (OSError, UnicodeError):
                    bad.append("LICENSE")

        try:
            (ROOT / "LICENSE.todo").lstat()
        except FileNotFoundError:
            pass
        else:
            bad.append("LICENSE.todo")

        if bad:
            raise MetadataError(
                "Public-release metadata is incomplete: " + ", ".join(bad)
            )

    if not structural_only:
        validate_effective_projects(cfg)


def solution_evaluation_properties(sln_text: str, solution: Path, configuration: str) -> dict[str, str]:
    project_rows = []
    for line in sln_text.splitlines():
        match = SOLUTION_PROJECT_LINE.fullmatch(line.strip())
        if match is None or match.group("type_guid").upper() != CSHARP_PROJECT_TYPE_GUID:
            continue
        project_path = os.path.abspath(ROOT / match.group("path").replace("\\", "/"))
        escaped_path = project_path.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
        project_rows.append(
            f'  <ProjectConfiguration Project="{match.group("project_guid").upper()}" '
            f'AbsolutePath="{escaped_path}" BuildProjectInSolution="True">'
            f"{configuration}|AnyCPU</ProjectConfiguration>"
        )
    contents = "<SolutionConfiguration>\n" + "\n".join(project_rows) + "\n</SolutionConfiguration>"
    return {
        "Configuration": configuration,
        "Platform": "AnyCPU",
        "BuildingSolutionFile": "true",
        "CurrentSolutionConfigurationContents": contents,
        "SolutionDir": str(ROOT) + os.sep,
        "SolutionPath": str(solution),
        "SolutionName": solution.stem,
        "SolutionFileName": solution.name,
        "SolutionExt": solution.suffix,
    }


def validate_effective_projects(cfg: dict) -> None:
    """Evaluate canonical projects with the complete solution global context."""
    validate_identity(cfg)
    validate_solution_membership(cfg)
    solution = ROOT / f"{cfg['rootNamespace']}.sln"
    sln_text = solution.read_text(encoding="utf-8")
    for configuration in ("Debug", "Release"):
        globals_ = solution_evaluation_properties(sln_text, solution, configuration)
        for project, item in cfg["projects"].items():
            context = f"project {project} for {configuration}|AnyCPU"
            csproj = ROOT / "src" / project / f"{project}.csproj"
            expected = {
                "MSBuildProjectFullPath": str(csproj),
                **globals_,
                "TargetFramework": item["targetFramework"],
                "AssemblyName": project,
            }
            command = ["dotnet", "msbuild", str(csproj), "-nologo",
                       f"-getProperty:{','.join(expected)}"]
            for name, value in globals_.items():
                escaped = re.sub(r"""[%$@();'"?,*]""", lambda match: f"%{ord(match[0]):02X}", value)
                command.append(f"-property:{name}={escaped}")
            try:
                result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
                if result.returncode:
                    raise MetadataError(
                        f"cannot evaluate {context}: MSBuild exited {result.returncode}: "
                        f"{result.stdout.strip()} {result.stderr.strip()}"
                    )
                properties = json.loads(result.stdout)["Properties"]
                if not isinstance(properties, dict) or properties.keys() != expected.keys():
                    raise ValueError("missing, duplicate, or unexpected evaluated properties")
                for name, value in expected.items():
                    actual = properties[name]
                    if actual != value:
                        raise MetadataError(f"{context} evaluates {name}={actual!r}; expected {value!r}")
            except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise MetadataError(f"cannot evaluate {context}: {exc}") from exc


def package_definitions(cfg: dict) -> list[tuple[str, list[str], str]]:
    packages = cfg["packages"]
    projects = cfg["projects"]
    definitions: list[tuple[str, list[str], str]] = []

    server_core_modules = [p for p in packages["serverModules"] if projects[p]["scope"] == "serverOnly"]
    if server_core_modules:
        definitions.append((f"{cfg['suiteName']}-ServerCore", server_core_modules, "server-core"))

    if packages["clientOnlyModules"]:
        definitions.append((f"{cfg['suiteName']}-Client", packages["clientOnlyModules"], "client-only"))

    for module in packages["requiredClientModules"] + packages["optionalClientModules"]:
        definitions.append((module.replace(".", "-"), [module], "shared-module"))

    if packages["serverModules"]:
        definitions.append((f"{cfg['suiteName']}-ServerPack", packages["serverModules"], "server-pack"))

    client_pack_modules = packages["requiredClientModules"] + packages["optionalClientModules"] + packages["clientOnlyModules"]
    if client_pack_modules:
        definitions.append((f"{cfg['suiteName']}-ClientPack", client_pack_modules, "client-pack"))

    return definitions


def _reject_case_collisions(values, field: str) -> None:
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            raise MetadataError(f"case-insensitive collision in {field}: {value!r}")
        seen.add(key)


def parse_solution_src_projects(sln_text: str) -> list[tuple[str, str]]:
    """Every C# project entry in the solution whose path's first
    component is `src` -- i.e. every project `suite.config.json`'s
    `projects` is supposed to declare -- as a `(name, normalized_path)`
    list that **preserves every entry, including duplicates**: turning
    this straight into a dict here would silently collapse malformed
    multiplicity (two entries with the same name, or two names sharing
    one path) before `validate_solution_membership()` ever gets a
    chance to reject it. A syntactically *valid* solution folder or
    non-C#-project entry is deliberately excluded by role/type, not
    merely left unrecognized, so its presence never fails the
    invariant; the generated test project (`tests/...`) is excluded by
    path the same way.

    A small state machine, not a general `.sln` grammar: it tracks
    exactly one open `Project(...)`/`EndProject` block at a time, since
    that is the only shape `bootstrap/model.py`'s `solution_text()` ever
    emits. A `Project(...)` opened before the prior one's `EndProject`,
    an `EndProject` with nothing open, or a block still open at
    end-of-file are all malformed structure and raise -- never silently
    misparsed into a false membership match.

    Every line that *opens* a project block (`Project(...`) must itself
    parse as a well-formed declaration (`SOLUTION_PROJECT_LINE`) once its
    `EndProject` is reached -- `dotnet sln <solution> list` already
    rejects a solution containing a header it cannot parse, and this
    parser must reject the same solution for the same reason instead of
    silently ignoring the block as "not a C# project". Only a header
    that *does* parse, but names a type other than the C# project-type
    GUID (a solution folder, some other project type), is excluded as
    intentionally irrelevant rather than rejected.

    Every recognized C# entry's own path must equal exactly
    `src/<name>/<name>.csproj` for *that entry's own declared name* --
    rejected immediately (not merely excluded) if it doesn't, so a
    traversal/absolute/mismatched-filename path can never survive to be
    compared against `suite.config.json` under a matching project name.
    """
    entries: list[tuple[str, str]] = []
    open_line: str | None = None
    guids: set[str] = set()
    for line in sln_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Project("):
            if open_line is not None:
                raise MetadataError(
                    f"malformed solution: a Project(...) entry opened before the prior one's "
                    f"EndProject: {open_line!r}"
                )
            open_line = stripped
        elif stripped == "EndProject":
            if open_line is None:
                raise MetadataError("malformed solution: EndProject with no matching Project(...) entry")
            header = open_line
            open_line = None
            match = SOLUTION_PROJECT_LINE.match(header)
            if match is None:
                raise MetadataError(
                    f"malformed solution: Project(...) entry does not match the supported declaration "
                    f"syntax: {header!r}"
                )
            guid = match.group("project_guid").upper()
            if guid in guids:
                raise MetadataError(f"solution contains a duplicate project GUID: {guid}")
            guids.add(guid)
            if match.group("type_guid").upper() != CSHARP_PROJECT_TYPE_GUID:
                continue
            name = match.group("name")
            normalized = match.group("path").replace("\\", "/")
            if normalized.split("/")[0] != "src":
                continue
            expected = f"src/{name}/{name}.csproj"
            if normalized != expected:
                raise MetadataError(
                    f"solution project {name!r} has a malformed path: expected {expected!r}, got {normalized!r}"
                )
            entries.append((name, normalized))
    if open_line is not None:
        raise MetadataError(f"malformed solution: Project(...) entry never closed with EndProject: {open_line!r}")
    return entries


def _reject_duplicate_source_entries(entries: list[tuple[str, str]]) -> None:
    seen_names: dict[str, str] = {}
    seen_paths: dict[str, str] = {}
    for name, path in entries:
        if name in seen_names:
            if seen_names[name] == path:
                raise MetadataError(f"solution contains a duplicate project entry: {name!r} ({path!r}) appears more than once")
            raise MetadataError(f"solution project {name!r} appears at two different paths: {seen_names[name]!r} and {path!r}")
        if path in seen_paths:
            raise MetadataError(f"solution path {path!r} is used by two different project names: {seen_paths[path]!r} and {name!r}")
        seen_names[name] = path
        seen_paths[path] = name


def validate_solution_membership(cfg: dict) -> None:
    """`suite.config.json`'s `projects` must exactly match which projects
    the canonical `<rootNamespace>.sln` actually builds under `src/`:
    the same name set, and -- since `parse_solution_src_projects()`
    already proved each recognized entry's own path equals its own
    canonical `src/<name>/<name>.csproj` -- a solution entry that keeps a
    configured project's *name* while its path silently redirected
    elsewhere (e.g. a `..` traversal to an external project) was already
    rejected there, not merely accepted because the name matched. Call
    after `validate_identity(cfg)` so `cfg['rootNamespace']` is already
    confirmed to name the real, generated solution."""
    sln_path = ROOT / f"{cfg['rootNamespace']}.sln"
    try:
        sln_text = sln_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MetadataError(f"Missing solution file: {sln_path.relative_to(ROOT)}") from exc
    entries = parse_solution_src_projects(sln_text)
    _reject_duplicate_source_entries(entries)
    solution_projects = dict(entries)
    configured = set(cfg["projects"])
    missing_from_solution = sorted(configured - set(solution_projects))
    missing_from_config = sorted(set(solution_projects) - configured)
    if missing_from_solution or missing_from_config:
        problems = []
        if missing_from_solution:
            problems.append(
                f"configured but absent from {sln_path.name} at its canonical src/<name>/<name>.csproj path: {missing_from_solution}"
            )
        if missing_from_config:
            problems.append(f"present in {sln_path.name} but absent from projects: {missing_from_config}")
        raise MetadataError(
            "projects must exactly match the canonical solution's src/ project membership: " + "; ".join(problems)
        )
    validate_solution_configurations(sln_text)


def validate_solution_configurations(sln_text: str) -> None:
    configurations = ("Debug|Any CPU", "Release|Any CPU")
    projects = [
        match.group("project_guid").upper()
        for line in sln_text.splitlines()
        if (match := SOLUTION_PROJECT_LINE.fullmatch(line.strip()))
        and match.group("type_guid").upper() == CSHARP_PROJECT_TYPE_GUID
    ]
    expected = {
        "SolutionConfigurationPlatforms": {cfg: cfg for cfg in configurations},
        "ProjectConfigurationPlatforms": {
            f"{guid}.{cfg}.{mapping}": cfg
            for guid in projects for cfg in configurations for mapping in ("ActiveCfg", "Build.0")
        },
    }
    sections: dict[str, dict[str, str]] = {}
    section = None
    for line in sln_text.splitlines():
        line = line.strip()
        if line.startswith("GlobalSection("):
            if section is not None:
                raise MetadataError("malformed solution configuration section")
            match = re.fullmatch(r"GlobalSection\(([^)]+)\)\s*=\s*(preSolution|postSolution)", line)
            if match is None:
                raise MetadataError("malformed solution GlobalSection")
            section = match[1]
            if section in sections:
                raise MetadataError(f"duplicate solution section: {section}")
            sections[section] = {}
            if section in expected and match[2] != (
                "preSolution" if section == "SolutionConfigurationPlatforms" else "postSolution"
            ):
                raise MetadataError(f"invalid solution section placement: {section}")
        elif line == "EndGlobalSection":
            if section is None:
                raise MetadataError("malformed solution: unmatched EndGlobalSection")
            section = None
        elif section in expected and line:
            key, separator, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if section == "ProjectConfigurationPlatforms":
                guid, dot, suffix = key.partition(".")
                key = guid.upper() + dot + suffix
            if not separator or not key or not value or key in sections[section]:
                raise MetadataError(f"malformed or duplicate solution configuration entry: {line}")
            sections[section][key] = value
    if section is not None:
        raise MetadataError("malformed solution: unclosed GlobalSection")
    for name, mappings in expected.items():
        if sections.get(name) != mappings:
            raise MetadataError(f"{name} must define exactly Debug/Release Any CPU ActiveCfg and Build.0 mappings")


def xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def cs_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def expected_files(cfg: dict) -> dict[Path, str]:
    props = f'''<?xml version="1.0" encoding="utf-8"?>\n<Project>\n  <!-- GENERATED from suite.config.json by scripts/suite_metadata.py. Do not edit manually. -->\n  <PropertyGroup>\n    <SuiteName>{xml_escape(cfg['suiteName'])}</SuiteName>\n    <SuiteRootNamespace>{xml_escape(cfg['rootNamespace'])}</SuiteRootNamespace>\n    <SuitePluginGuidRoot>{xml_escape(cfg['pluginGuidRoot'])}</SuitePluginGuidRoot>\n    <SuiteAuthors>{xml_escape(cfg['author'])}</SuiteAuthors>\n    <SuiteThunderstoreNamespace>{xml_escape(cfg['thunderstoreNamespace'])}</SuiteThunderstoreNamespace>\n    <SuiteVersion>{xml_escape(cfg['suiteVersion'])}</SuiteVersion>\n    <SuiteCSharpLanguageVersion>{xml_escape(cfg['csharpLanguageVersion'])}</SuiteCSharpLanguageVersion>\n    <JotunnVersion>{xml_escape(cfg['jotunnVersion'])}</JotunnVersion>\n    <BepInExPackVersion>{xml_escape(cfg['bepInExPackVersion'])}</BepInExPackVersion>\n    <NetFrameworkReferenceAssembliesVersion>{xml_escape(cfg['netFrameworkReferenceAssembliesVersion'])}</NetFrameworkReferenceAssembliesVersion>\n  </PropertyGroup>\n</Project>\n'''

    generated_props = contain(GENERATED_PROPS, ROOT / "build")
    common_project = cfg["packages"]["commonModule"]
    generated_cs = contain(ROOT / "src" / common_project / "SuiteConstants.Generated.cs", ROOT / "src")
    cs = (
        f"// <auto-generated />\nnamespace {cfg['rootNamespace']}.Common;\n\n"
        "public static class SuiteConstants\n{\n"
        f'    public const string Name = "{cs_escape(cfg["suiteName"])}";\n'
        f'    public const string Version = "{cs_escape(cfg["suiteVersion"])}";\n'
        f'    public const string GuidRoot = "{cs_escape(cfg["pluginGuidRoot"])}";\n'
        "}\n"
    )

    packages = cfg["packages"]
    lock = {
        "schemaVersion": 1,
        "generatedFrom": "suite.config.json",
        "suiteVersion": cfg["suiteVersion"],
        "dependencies": {
            "denikson-BepInExPack_Valheim": cfg["bepInExPackVersion"],
            "ValheimModding-Jotunn": cfg["jotunnVersion"],
        },
        "serverModules": packages["serverModules"],
        "requiredClientModules": packages["requiredClientModules"],
        "optionalClientModules": packages["optionalClientModules"],
        "clientOnlyModules": packages["clientOnlyModules"],
    }
    lock_text = json.dumps(lock, indent=2) + "\n"
    profile_lock = contain(PROFILE_LOCK, ROOT / "packaging")
    return {generated_props: props, generated_cs: cs, profile_lock: lock_text}


@dataclass
class _OutputParent:
    directory_fd: int
    owner_fd: int | None
    owner_name: str | None
    dev: int
    ino: int

    def verify(self, error_cls: type[Exception]) -> None:
        current = os.fstat(self.directory_fd)
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (self.dev, self.ino):
            raise error_cls("authorized output directory changed")
        if self.owner_fd is None:
            return
        try:
            entry = os.stat(self.owner_name, dir_fd=self.owner_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise error_cls("authorized output directory was removed") from exc
        if (
            stat.S_ISLNK(entry.st_mode)
            or not stat.S_ISDIR(entry.st_mode)
            or (entry.st_dev, entry.st_ino) != (self.dev, self.ino)
        ):
            raise error_cls("authorized output directory was replaced")

    def close(self) -> None:
        os.close(self.directory_fd)
        if self.owner_fd is not None:
            os.close(self.owner_fd)


def open_confined_parent(path: Path, *, error_cls: type[Exception] = MetadataError) -> tuple[_OutputParent, str]:
    """Open the exact parent directory of a generated output without
    following symlinks, creating only missing descendants through directory FDs."""
    path = contain(path, ROOT, error_cls=error_cls)
    parts = path.relative_to(ROOT).parts
    if not parts:
        raise error_cls(f"generated output must be beneath {ROOT}: {path}")
    try:
        current_fd = os.open(ROOT, _DIRECTORY_FLAGS)
    except OSError as exc:
        raise error_cls(f"cannot open generated repository: {exc}") from exc
    try:
        root_state = os.fstat(current_fd)
        if (root_state.st_dev, root_state.st_ino) != _ROOT_ID:
            raise error_cls("generated repository was replaced")
        parent_parts = parts[:-1]
        if not parent_parts:
            return _OutputParent(current_fd, None, None, root_state.st_dev, root_state.st_ino), parts[-1]
        for index, part in enumerate(parent_parts):
            try:
                child_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o755, dir_fd=current_fd)
                except FileExistsError:
                    pass
                try:
                    child_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
                except OSError as exc:
                    raise error_cls(f"cannot open generated directory {part!r}: {exc}") from exc
            except OSError as exc:
                raise error_cls(f"cannot open generated directory {part!r}: {exc}") from exc
            if index == len(parent_parts) - 1:
                state = os.fstat(child_fd)
                return _OutputParent(child_fd, current_fd, part, state.st_dev, state.st_ino), parts[-1]
            os.close(current_fd)
            current_fd = child_fd
    except BaseException:
        os.close(current_fd)
        raise
    raise AssertionError("unreachable")


@dataclass
class _TemporaryOutput:
    file_fd: int
    name: str
    dev: int
    ino: int

    def close(self) -> None:
        os.close(self.file_fd)


@dataclass
class _FinalTarget:
    """An existing final output, opened and retained for the entire
    promotion so its identity survives until the swap is verified -- or
    `fd is None` when no final output exists yet."""

    fd: int | None
    mode: int | None
    dev: int | None
    ino: int | None

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _stat_output_entry(
    parent: _OutputParent, name: str, *, error_cls: type[Exception], missing_ok: bool
) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent.directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise error_cls(f"generated output entry disappeared: {name}")
    except OSError as exc:
        raise error_cls(f"cannot inspect generated output {name}: {exc}") from exc


def preflight_output_target(parent: _OutputParent, final_name: str, *, error_cls: type[Exception]) -> _FinalTarget:
    """Validate an existing final output (if any) and retain an open,
    no-follow FD to it so its identity can be verified again immediately
    before promotion and restored if promotion is corrupted."""
    parent.verify(error_cls)
    existing = _stat_output_entry(parent, final_name, error_cls=error_cls, missing_ok=True)
    if existing is None:
        return _FinalTarget(None, None, None, None)
    if stat.S_ISLNK(existing.st_mode):
        raise error_cls(f"refusing symlinked generated output: {final_name}")
    if not stat.S_ISREG(existing.st_mode):
        raise error_cls(f"generated output is not a regular file: {final_name}")
    try:
        fd = os.open(final_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent.directory_fd)
    except OSError as exc:
        raise error_cls(f"cannot retain generated output {final_name}: {exc}") from exc
    state = os.fstat(fd)
    if not stat.S_ISREG(state.st_mode):
        os.close(fd)
        raise error_cls(f"generated output is not a regular file: {final_name}")
    return _FinalTarget(fd, stat.S_IMODE(state.st_mode), state.st_dev, state.st_ino)


def create_temp_file(parent: _OutputParent, final_name: str, *, error_cls: type[Exception]) -> _TemporaryOutput:
    parent.verify(error_cls)
    for _ in range(16):
        # The random suffix owns uniqueness; a bounded label allows 255-byte final names.
        temp_name = f".{final_name[:32]}.{uuid.uuid4().hex}.tmp"
        try:
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o644,
                dir_fd=parent.directory_fd,
            )
            state = os.fstat(temp_fd)
            if not stat.S_ISREG(state.st_mode):
                os.close(temp_fd)
                raise error_cls("generated temporary file is not a regular file")
            return _TemporaryOutput(temp_fd, temp_name, state.st_dev, state.st_ino)
        except FileExistsError:
            continue
        except OSError as exc:
            raise error_cls(f"cannot create generated temporary file: {exc}") from exc
    raise error_cls("cannot allocate a unique generated temporary file")


def _verify_temporary_output(
    parent: _OutputParent, temp: _TemporaryOutput, *, error_cls: type[Exception]
) -> None:
    parent.verify(error_cls)
    try:
        current = os.fstat(temp.file_fd)
    except OSError as exc:
        raise error_cls(f"cannot inspect generated temporary file: {exc}") from exc
    if (
        not stat.S_ISREG(current.st_mode)
        or (current.st_dev, current.st_ino) != (temp.dev, temp.ino)
    ):
        raise error_cls("generated temporary file changed")
    entry = _stat_output_entry(parent, temp.name, error_cls=error_cls, missing_ok=False)
    if (
        entry is None
        or not stat.S_ISREG(entry.st_mode)
        or (entry.st_dev, entry.st_ino) != (temp.dev, temp.ino)
    ):
        raise error_cls("generated temporary file was replaced")


def _remove_temporary_output(parent: _OutputParent, temp: _TemporaryOutput) -> None:
    try:
        os.unlink(temp.name, dir_fd=parent.directory_fd)
    except (FileNotFoundError, OSError):
        pass


_RECOVERY_ATTEMPTS = 4
_RECOVERY_CHUNK_SIZE = 1 << 20


def _write_all(fd: int, data: bytes, *, error_cls: type[Exception]) -> None:
    """Write the complete buffer to `fd`, looping since a single
    `os.write()` may legally write fewer bytes than requested. A
    non-positive return makes no progress and must never be retried
    indefinitely -- it fails closed as a controlled writer error instead
    of livelocking."""
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except OSError as exc:
            raise error_cls(f"cannot write generated recovery temporary file: {exc}") from exc
        if written <= 0:
            raise error_cls("cannot write generated recovery temporary file: write made no progress")
        view = view[written:]


def _copy_retained_final(source_fd: int, dest_fd: int, size: int, *, error_cls: type[Exception]) -> None:
    """Copy exactly `size` bytes from the retained final FD into a
    recovery temp's FD, streaming in bounded chunks rather than
    allocating the whole file in memory. A single `pread()` may legally
    return fewer bytes than requested, so this loops until the full
    captured length has been read; an empty read before that point means
    the retained inode shrank during recovery, which fails closed instead
    of silently installing truncated content."""
    remaining = size
    offset = 0
    while remaining > 0:
        try:
            chunk = os.pread(source_fd, min(remaining, _RECOVERY_CHUNK_SIZE), offset)
        except OSError as exc:
            raise error_cls(f"cannot read previous generated output for recovery: {exc}") from exc
        if not chunk:
            raise error_cls(
                f"previous generated output changed size during recovery: expected {size} bytes, got {offset}"
            )
        _write_all(dest_fd, chunk, error_cls=error_cls)
        offset += len(chunk)
        remaining -= len(chunk)


def _swap_and_verify(
    parent: _OutputParent,
    src_name: str,
    final_name: str,
    identity: tuple[int, int],
    *,
    error_cls: type[Exception],
) -> bool:
    """Attempt to atomically move `src_name` onto `final_name`; return
    whether the promoted entry is a regular file matching `identity`
    (dev, ino). Never raises for a failed or corrupted swap."""
    try:
        os.replace(src_name, final_name, src_dir_fd=parent.directory_fd, dst_dir_fd=parent.directory_fd)
        final = _stat_output_entry(parent, final_name, error_cls=error_cls, missing_ok=True)
        return (
            final is not None
            and stat.S_ISREG(final.st_mode)
            and (final.st_dev, final.st_ino) == identity
        )
    except (OSError, error_cls):
        return False


def _ensure_final_absent(parent: _OutputParent, final_name: str, *, error_cls: type[Exception]) -> None:
    """Remove whatever entry currently occupies `final_name` (without
    following it) and confirm, via a fresh no-follow stat, that it is
    genuinely gone. Raises `error_cls` rather than assuming success if
    removal or the confirming stat fails -- an unsafe final entry must
    never be left in place because cleanup silently swallowed an error."""
    try:
        os.unlink(final_name, dir_fd=parent.directory_fd)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise error_cls(f"cannot remove unsafe generated output {final_name}: {exc}") from exc
    try:
        os.stat(final_name, dir_fd=parent.directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise error_cls(f"cannot confirm generated output {final_name} is safe: {exc}") from exc
    raise error_cls(f"cannot confirm generated output {final_name} is safe: entry still present")


def _recover_from_failed_promotion(
    parent: _OutputParent,
    final_name: str,
    final_target: _FinalTarget,
    *,
    error_cls: type[Exception],
) -> None:
    """A promoted entry didn't match the retained temp-file identity.
    Remove whatever ended up at `final_name`, then -- if a previous final
    output existed -- reconstruct it from the identity-pinned FD retained
    at preflight time. Recovery never trusts a directory-entry pathname as
    its data source (there is no staged `.bak` to substitute): the
    retained FD is the sole recovery authority, and each reconstruction
    attempt is itself a freshly created, freshly verified temp file,
    verified again immediately before -- with no gap after -- it is
    promoted.

    The whole reconstruction (allocation, reading, writing, verifying,
    promoting, and retrying) is enclosed by an outer fail-safe boundary: a
    failure that occurs *within* one attempt (e.g. its own temp entry
    substituted) is retried with a fresh, unpredictable name, but a
    failure that escapes an attempt entirely (e.g. temp allocation itself
    failing) still lands here rather than propagating past cleanup. Every
    unsuccessful exit -- retries exhausted or an escaped failure --
    removes any unsafe entry at `final_name` and confirms that removal
    succeeded before raising."""
    _ensure_final_absent(parent, final_name, error_cls=error_cls)

    if final_target.fd is None:
        return

    restored = False
    cause: BaseException | None = None
    try:
        size = os.fstat(final_target.fd).st_size
        for _ in range(_RECOVERY_ATTEMPTS):
            recovery = create_temp_file(parent, final_name, error_cls=error_cls)
            try:
                _copy_retained_final(final_target.fd, recovery.file_fd, size, error_cls=error_cls)
                if final_target.mode is not None:
                    os.fchmod(recovery.file_fd, final_target.mode)
                _verify_temporary_output(parent, recovery, error_cls=error_cls)
                restored = _swap_and_verify(
                    parent, recovery.name, final_name, (recovery.dev, recovery.ino), error_cls=error_cls
                )
            except (OSError, error_cls):
                restored = False
            finally:
                if not restored:
                    _remove_temporary_output(parent, recovery)
                recovery.close()
            if restored:
                break
    except (OSError, error_cls) as exc:
        cause = exc

    if restored:
        return

    _ensure_final_absent(parent, final_name, error_cls=error_cls)
    raise error_cls(f"cannot restore previous generated output {final_name}") from cause


def promote_temp_file(
    parent: _OutputParent,
    temp: _TemporaryOutput,
    final_name: str,
    *,
    final_target: _FinalTarget,
    error_cls: type[Exception],
) -> None:
    if final_target.mode is not None:
        try:
            os.fchmod(temp.file_fd, final_target.mode)
        except OSError as exc:
            raise error_cls(f"cannot preserve generated output permissions: {exc}") from exc
    _verify_temporary_output(parent, temp, error_cls=error_cls)

    ok = _swap_and_verify(parent, temp.name, final_name, (temp.dev, temp.ino), error_cls=error_cls)
    if not ok:
        _recover_from_failed_promotion(parent, final_name, final_target, error_cls=error_cls)
        raise error_cls(f"generated output {final_name} changed during promotion")


def atomic_write_bytes(
    path: Path,
    content: bytes,
    *,
    parent: _OutputParent | None = None,
    final_target: _FinalTarget | object = _UNSET,
) -> None:
    """Atomically replace bytes through an authorized parent directory FD."""
    owns_parent = parent is None
    if parent is None:
        parent, final_name = open_confined_parent(path)
    else:
        parent.verify(MetadataError)
        final_name = path.name
    if final_target is _UNSET:
        final_target = preflight_output_target(parent, final_name, error_cls=MetadataError)
    temp: _TemporaryOutput | None = None
    promoted = False
    try:
        temp = create_temp_file(parent, final_name, error_cls=MetadataError)
        _write_all(temp.file_fd, content, error_cls=MetadataError)
        promote_temp_file(parent, temp, final_name, final_target=final_target, error_cls=MetadataError)
        promoted = True
    finally:
        final_target.close()
        if temp is not None:
            if not promoted:
                _remove_temporary_output(parent, temp)
            temp.close()
        if owns_parent:
            parent.close()


def atomic_write_text(
    path: Path,
    content: str,
    *,
    parent: _OutputParent | None = None,
    final_target: _FinalTarget | object = _UNSET,
) -> None:
    """Atomically replace UTF-8 text through an authorized parent directory FD."""
    atomic_write_bytes(path, content.encode("utf-8"), parent=parent, final_target=final_target)


def _read_retained_final(final_target: _FinalTarget) -> bytes | None:
    if final_target.fd is None:
        return None
    try:
        size = os.fstat(final_target.fd).st_size
        chunks: list[bytes] = []
        offset = 0
        while offset < size:
            chunk = os.pread(final_target.fd, min(_RECOVERY_CHUNK_SIZE, size - offset), offset)
            if not chunk:
                raise MetadataError("generated output disappeared while preparing transaction rollback")
            chunks.append(chunk)
            offset += len(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise MetadataError("cannot snapshot generated output for transaction rollback") from exc


def _remove_generated_output(path: Path) -> None:
    parent, final_name = open_confined_parent(path)
    try:
        parent.verify(MetadataError)
        _ensure_final_absent(parent, final_name, error_cls=MetadataError)
    finally:
        parent.close()


def _write_sync_recovery(snapshots: list[tuple[Path, bytes | None]]) -> Path:
    recovery_path = ROOT / f".suite-metadata-sync-recovery-{uuid.uuid4().hex}.json"
    recovery = {
        "schemaVersion": 1,
        "generatedFrom": "suite.config.json",
        "outputs": [
            {
                "path": str(path.relative_to(ROOT)),
                "original": None if original is None else base64.b64encode(original).decode("ascii"),
            }
            for path, original in snapshots
        ],
    }
    atomic_write_text(recovery_path, json.dumps(recovery, indent=2) + "\n")
    return recovery_path


def _restore_sync_outputs(snapshots: list[tuple[Path, bytes | None]]) -> None:
    failures: list[str] = []
    for path, original in reversed(snapshots):
        try:
            if original is None:
                _remove_generated_output(path)
            else:
                atomic_write_bytes(path, original)
        except BaseException as exc:
            failures.append(f"{path.relative_to(ROOT)}: {exc}")
    if failures:
        try:
            recovery_path = _write_sync_recovery(snapshots)
        except BaseException as recovery_exc:
            raise MetadataError(
                "generated metadata transaction rollback was incomplete and recovery data could not be saved: "
                + "; ".join(failures)
                + f"; recovery write failed: {recovery_exc}"
            ) from recovery_exc
        raise MetadataError(
            "generated metadata transaction rollback was incomplete; original bytes were saved in "
            f"{recovery_path.relative_to(ROOT)}: " + "; ".join(failures)
        )

def _promote_sync_outputs(outputs: list[tuple[Path, str, _OutputParent, _FinalTarget]]) -> None:
    snapshots = [
        (path, _read_retained_final(final_target))
        for path, _content, _parent, final_target in outputs
    ]
    attempted: list[tuple[Path, bytes | None]] = []
    try:
        for output, snapshot in zip(outputs, snapshots):
            path, content, parent, final_target = output
            attempted.append(snapshot)
            atomic_write_text(path, content, parent=parent, final_target=final_target)
            print(f"wrote {path.relative_to(ROOT)}")
    except BaseException as exc:
        try:
            _restore_sync_outputs(attempted)
        except MetadataError as rollback_exc:
            raise rollback_exc from exc
        raise


def sync(cfg: dict, *, structural_only: bool = False) -> None:
    validate(cfg, structural_only=structural_only)
    validate_identity(cfg)
    validate_solution_membership(cfg)
    outputs: list[tuple[Path, str, _OutputParent, _FinalTarget]] = []
    try:
        for path, content in expected_files(cfg).items():
            parent, final_name = open_confined_parent(path)
            try:
                final_target = preflight_output_target(parent, final_name, error_cls=MetadataError)
            except BaseException:
                parent.close()
                raise
            outputs.append((path, content, parent, final_target))
        _promote_sync_outputs(outputs)
    finally:
        for _path, _content, parent, final_target in outputs:
            final_target.close()
            parent.close()


def check(cfg: dict, release: bool = False, *, structural_only: bool = False) -> None:
    validate(cfg, release=release, structural_only=structural_only)
    validate_identity(cfg)
    validate_solution_membership(cfg)
    mismatches = []
    for path, expected in expected_files(cfg).items():
        if not path.exists():
            mismatches.append(f"missing generated file {path.relative_to(ROOT)}")
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            mismatches.append(f"stale generated file {path.relative_to(ROOT)}")
    if mismatches:
        raise MetadataError("; ".join(mismatches) + ". Run: python3 scripts/suite_metadata.py sync")
    if structural_only:
        print("suite metadata: structurally synchronized; MSBuild artifact contract NOT certified")
    else:
        print("suite metadata: valid and synchronized")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sync_parser = sub.add_parser("sync", help="Regenerate committed metadata outputs from suite.config.json")
    check_parser = sub.add_parser("check", help="Validate config and generated outputs")
    check_parser.add_argument("--release", action="store_true", help="Also require public-release naming metadata")
    for command_parser in (sync_parser, check_parser):
        command_parser.add_argument(
            "--structural-only", action="store_true",
            help="Bootstrap/scaffold only: skip MSBuild evaluation; does NOT certify build artifacts",
        )
    args = parser.parse_args()
    try:
        cfg = load_config()
        if args.command == "sync":
            sync(cfg, structural_only=args.structural_only)
        else:
            check(cfg, release=args.release, structural_only=args.structural_only)
        return 0
    except MetadataError as exc:
        print(f"metadata error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
