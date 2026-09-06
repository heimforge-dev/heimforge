"""Validation for generator identity inputs.

Deliberately duplicates the SEMVER/GUID_ROOT regex shape used by
template/scripts/suite_metadata.py: generated projects must never import
bootstrapper code, so the generated project keeps its own copies. See
docs/TEMPLATE_MAINTENANCE.md.
"""

from __future__ import annotations

import re


class NamingError(ValueError):
    pass


NAMESPACE_SEGMENT = r"[A-Za-z_][A-Za-z0-9_]*"
NAMESPACE_RE = re.compile(rf"^{NAMESPACE_SEGMENT}(?:\.{NAMESPACE_SEGMENT})*\Z")
GUID_ROOT_RE = re.compile(r"^[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)+\Z")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?\Z")
NAME_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9._-]*[A-Za-z0-9_])?\Z")
_RESERVED_DEVICE_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{d}" for d in "123456789"),
    *(f"LPT{d}" for d in "123456789"),
}
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


def validate_namespace(value: str, field: str) -> str:
    if not value or not NAMESPACE_RE.match(value) or any(segment in CSHARP_KEYWORDS for segment in value.split(".")):
        raise NamingError(
            f"{field} must be a dot-separated sequence of valid, non-keyword identifiers "
            f"(e.g. ExampleCompany.Vibeheim), each starting with a letter/underscore: {value!r}"
        )
    return value


def validate_guid_root(value: str) -> str:
    if not value or not GUID_ROOT_RE.match(value):
        raise NamingError(
            f"pluginGuidRoot has invalid syntax (dot/hyphen separated segments, e.g. com.example.suite): {value!r}"
        )
    return value


def validate_semver(value: str, field: str) -> str:
    if not value or not SEMVER_RE.match(value):
        raise NamingError(f"{field} is not valid semantic-version syntax: {value!r}")
    return value


def validate_label(value: str, field: str) -> str:
    if not value or value != value.strip() or "/" in value or "\\" in value or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise NamingError(f"{field} must be a non-empty, trimmed string without path separators or control characters: {value!r}")
    return value


def validate_path_component(value: str, field: str) -> str:
    if not isinstance(value, str) or not NAME_COMPONENT_RE.match(value):
        raise NamingError(
            f"{field} must be a single portable path component: letters, digits, '.', '_', '-' only, "
            f"starting and ending with a letter, digit, or underscore: {value!r}"
        )
    if value.split(".", 1)[0].upper() in _RESERVED_DEVICE_NAMES:
        raise NamingError(f"{field} must not use a reserved platform device name: {value!r}")
    return value
