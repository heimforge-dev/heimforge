"""Validation for generator identity inputs.

Deliberately duplicates the SEMVER/GUID_ROOT/THUNDERSTORE_NAMESPACE regex
shape used by template/scripts/suite_metadata.py: generated projects must
never import bootstrapper code, so the generated project keeps its own
copies. See docs/TEMPLATE_MAINTENANCE.md.
"""

from __future__ import annotations

import re
import unicodedata


class NamingError(ValueError):
    pass


NAMESPACE_SEGMENT = r"[A-Za-z_][A-Za-z0-9_]*"
NAMESPACE_RE = re.compile(rf"^{NAMESPACE_SEGMENT}(?:\.{NAMESPACE_SEGMENT})*\Z")
GUID_ROOT_RE = re.compile(r"^[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)+\Z")
NAME_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9._-]*[A-Za-z0-9_])?\Z")

# template/scripts/deploy.py's deployment manifest filename is
# f".{suiteName}.deploy-manifest.json" -- 1 leading dot + suiteName + the
# 21-character ".deploy-manifest.json" suffix. Bounding suiteName at 233
# ASCII bytes keeps that rendered filename at exactly 255 bytes, the
# common POSIX/NTFS single-path-component limit. Mirrors
# template/scripts/suite_metadata.py's MAX_SUITE_NAME_LENGTH.
MAX_SUITE_NAME_LENGTH = 233

# The Thunderstore namespace charset (reviewer-verified contract): max 64
# characters; first and last character alphanumeric; internal characters
# alphanumeric or '_'. Distinct from the looser package-name charset at
# https://wiki.thunderstore.io/mods/creating-a-package, which allows '_'
# at the edges -- namespaces do not.
THUNDERSTORE_NAMESPACE_MAX_LENGTH = 64
THUNDERSTORE_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9]+(?:[A-Za-z0-9_]*[A-Za-z0-9])?\Z")

# SemVer 2.0.0 (https://semver.org): MAJOR.MINOR.PATCH numeric core with no
# leading zeroes; optional dot-separated prerelease identifiers (numeric
# ones may not have leading zeroes); optional dot-separated build-metadata
# identifiers (leading zeroes allowed there). Syntax only -- no ordering.
_SEMVER_CORE_RE = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_SEMVER_IDENT_RE = re.compile(r"^[0-9A-Za-z-]+\Z")
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
    error = NamingError(f"{field} is not valid SemVer 2.0.0 syntax: {value!r}")
    if not isinstance(value, str) or not value:
        raise error
    core_and_prerelease, has_build, build = value.partition("+")
    core, has_prerelease, prerelease = core_and_prerelease.partition("-")
    if not _SEMVER_CORE_RE.match(core):
        raise error
    if has_prerelease and not all(_valid_semver_prerelease_identifier(i) for i in prerelease.split(".")):
        raise error
    if has_build and not all(_SEMVER_IDENT_RE.match(i) for i in build.split(".")):
        raise error
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


def validate_label(value: str, field: str) -> str:
    """Free-text display metadata (e.g. author): safely embeddable
    anywhere it is used (JSON/XML-escaped at each generation site) but
    never a path or an external-platform identifier, so ordinary spaces,
    Unicode letters, quotes, apostrophes, ampersands, and angle brackets
    remain allowed. Not for fields with a closed external grammar -- see
    `validate_thunderstore_namespace`."""
    if (
        not value
        or value != value.strip()
        or "/" in value
        or "\\" in value
        or any(unicodedata.category(ch) in _REJECTED_LABEL_CATEGORIES for ch in value)
        or any(not _is_xml_1_0_char(ord(ch)) for ch in value)
    ):
        raise NamingError(
            f"{field} must be a non-empty, trimmed string without path separators, Unicode "
            f"control/line-separator/paragraph-separator characters, or characters invalid "
            f"in XML 1.0 character data: {value!r}"
        )
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
        or not THUNDERSTORE_NAMESPACE_RE.match(value)
    ):
        raise NamingError(
            f"{field} must be 1-{THUNDERSTORE_NAMESPACE_MAX_LENGTH} ASCII letters/digits/underscore, "
            f"starting and ending with a letter or digit: {value!r}"
        )
    return value


def validate_component_length(value: str, field: str) -> str:
    if len(value.encode("utf-8")) > 255:
        raise NamingError(f"{field} exceeds the portable 255-byte filesystem component limit")
    return value


def validate_path_component(value: str, field: str) -> str:
    if not isinstance(value, str) or not NAME_COMPONENT_RE.match(value):
        raise NamingError(
            f"{field} must be a single portable path component: letters, digits, '.', '_', '-' only, "
            f"starting and ending with a letter, digit, or underscore: {value!r}"
        )
    if value.split(".", 1)[0].upper() in _RESERVED_DEVICE_NAMES:
        raise NamingError(f"{field} must not use a reserved platform device name: {value!r}")
    validate_component_length(value, field)
    return value
