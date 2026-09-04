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
NAMESPACE_RE = re.compile(rf"^{NAMESPACE_SEGMENT}(?:\.{NAMESPACE_SEGMENT})*$")
GUID_ROOT_RE = re.compile(r"^[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)+$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


def validate_namespace(value: str, field: str) -> str:
    if not value or not NAMESPACE_RE.match(value):
        raise NamingError(
            f"{field} must be a dot-separated sequence of valid identifiers "
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
    if not value or value != value.strip() or "/" in value or "\\" in value:
        raise NamingError(f"{field} must be a non-empty, trimmed string without path separators: {value!r}")
    return value
