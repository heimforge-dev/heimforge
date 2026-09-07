#!/usr/bin/env python3
"""Validate and synchronize generated project metadata from suite.config.json."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "suite.config.json"
GENERATED_PROPS = ROOT / "build" / "Suite.Generated.props"
PROFILE_LOCK = ROOT / "packaging" / "profile-lock.json"
_ROOT_ID = (ROOT.stat().st_dev, ROOT.stat().st_ino)
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

_UNSET = object()

GUID_ROOT = re.compile(r"^[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)+\Z")
VALID_SCOPES = {"common", "serverOnly", "clientOnly", "sharedOptional", "sharedRequired"}

# The four package/deployment membership groups from suite.config.json's
# "packages" object. deploy.py's modules_for() and package.py's
# package_definitions() both read these same four arrays directly, so this
# tuple and SCOPE_PACKAGE_GROUPS below are the single source of truth they
# must stay aligned with.
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


def validate(cfg: dict, release: bool = False) -> None:
    if cfg.get("schemaVersion") != 1:
        raise MetadataError("schemaVersion must currently be 1")

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

    packages = cfg.get("packages")
    if not isinstance(packages, dict):
        raise MetadataError("packages must be an object")
    common = packages.get("commonModule")
    if not isinstance(common, str) or common not in projects or projects[common]["scope"] != "common":
        raise MetadataError("packages.commonModule must identify the project with scope=common")

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
        if bad:
            raise MetadataError("Public-release metadata is incomplete: " + ", ".join(bad))


def xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def cs_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def expected_files(cfg: dict) -> dict[Path, str]:
    props = f'''<?xml version="1.0" encoding="utf-8"?>\n<Project>\n  <!-- GENERATED from suite.config.json by scripts/suite_metadata.py. Do not edit manually. -->\n  <PropertyGroup>\n    <SuiteName>{xml_escape(cfg['suiteName'])}</SuiteName>\n    <SuiteRootNamespace>{xml_escape(cfg['rootNamespace'])}</SuiteRootNamespace>\n    <SuitePluginGuidRoot>{xml_escape(cfg['pluginGuidRoot'])}</SuitePluginGuidRoot>\n    <SuiteAuthors>{xml_escape(cfg['author'])}</SuiteAuthors>\n    <SuiteThunderstoreNamespace>{xml_escape(cfg['thunderstoreNamespace'])}</SuiteThunderstoreNamespace>\n    <SuiteVersion>{xml_escape(cfg['suiteVersion'])}</SuiteVersion>\n    <SuiteCSharpLanguageVersion>{xml_escape(cfg['csharpLanguageVersion'])}</SuiteCSharpLanguageVersion>\n    <JotunnVersion>{xml_escape(cfg['jotunnVersion'])}</JotunnVersion>\n    <BepInExPackVersion>{xml_escape(cfg['bepInExPackVersion'])}</BepInExPackVersion>\n    <NetFrameworkReferenceAssembliesVersion>{xml_escape(cfg['netFrameworkReferenceAssembliesVersion'])}</NetFrameworkReferenceAssembliesVersion>\n  </PropertyGroup>\n</Project>\n'''

    generated_props = contain(GENERATED_PROPS, ROOT / "build")
    common_project = cfg["packages"]["commonModule"]
    generated_cs = contain(ROOT / "src" / common_project / "SuiteConstants.Generated.cs", ROOT / "src")
    cs = f'''// <auto-generated />\nnamespace {cfg['rootNamespace']}.Common;\n\npublic static class SuiteConstants\n{{\n    public const string Name = "{cs_escape(cfg['suiteName'])}";\n    public const string Version = "{cs_escape(cfg['suiteVersion'])}";\n    public const string GuidRoot = "{cs_escape(cfg['pluginGuidRoot'])}";\n}}\n'''

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
        temp_name = f".{final_name}.{uuid.uuid4().hex}.tmp"
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


def atomic_write_text(
    path: Path,
    content: str,
    *,
    parent: _OutputParent | None = None,
    final_target: _FinalTarget | object = _UNSET,
) -> None:
    """Atomically replace text through an authorized parent directory FD."""
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
        with os.fdopen(os.dup(temp.file_fd), "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
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


def sync(cfg: dict) -> None:
    validate(cfg)
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
        for path, content, parent, final_target in outputs:
            atomic_write_text(path, content, parent=parent, final_target=final_target)
            print(f"wrote {path.relative_to(ROOT)}")
    finally:
        for _path, _content, parent, final_target in outputs:
            final_target.close()
            parent.close()


def check(cfg: dict, release: bool = False) -> None:
    validate(cfg, release=release)
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
    print("suite metadata: valid and synchronized")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync", help="Regenerate committed metadata outputs from suite.config.json")
    check_parser = sub.add_parser("check", help="Validate config and generated outputs")
    check_parser.add_argument("--release", action="store_true", help="Also require public-release naming metadata")
    args = parser.parse_args()
    try:
        cfg = load_config()
        if args.command == "sync":
            sync(cfg)
        else:
            check(cfg, release=args.release)
        return 0
    except MetadataError as exc:
        print(f"metadata error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
