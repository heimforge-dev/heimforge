"""Template tree rendering and template self-validation.

No templating dependency (Jinja2 etc.) is used on purpose: the token
vocabulary is small and closed (see docs/TEMPLATE_MAINTENANCE.md), so a
flat regex substitution is sufficient and keeps the generated project's
own tooling free of any bootstrapper dependency.

`render_tree()` never walks `template/`'s filesystem contents: it renders
exactly the files listed in `bootstrap/template_manifest.py`, filtered to
the optional modules a given `ProjectModel` includes. A file placed
anywhere under `template/` without being added to that manifest is never
rendered, and fails `validate_template()` instead of being silently
ignored — the filesystem contents of `template/` are not themselves the
template definition.

A manifest-approved *name* is not enough to trust a source: every source
path is opened through `_open_source_file()`, which refuses to follow a
symlink at any path component — including the final one — and refuses
anything that isn't a plain regular file, so a symlink substituted for an
approved path (or for one of its parent directories) can never redirect
rendering to content outside `template_dir`. Every rendered destination
is also containment- and collision-checked by `_render_plan()` before
anything is written.
"""

from __future__ import annotations

import errno
import json
import os
import posixpath
import re
import stat
from pathlib import Path

from .model import ProjectModel, token_map
from .template_manifest import (
    OPTIONAL_TEMPLATE_FILES,
    REQUIRED_TEMPLATE_FILES,
    all_template_files,
    invalid_manifest_path_reason,
    validate_manifest_structure,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "template"

# First character alphabetic/underscore (matches every current token's
# convention), remaining characters may also be digits -- e.g.
# `PROJECT_SPEC_MILESTONE2_BODY`. This single regex is the renderer's own
# token *grammar*: it backs template token discovery, substitution, and
# `validate_template()`'s known-token check against `KNOWN_TOKENS` --
# whether a `{{...}}` in template *source* is a legal, recognized token.
TOKEN_RE = re.compile(r"\{\{([A-Z_][A-Z0-9_]*)\}\}")

# The one path-sentinel segment `_render_plan()` substitutes with the real
# root namespace (see `template_manifest.py`'s module docstring). A single
# definition so `validate_generated.py`'s unresolved-path-sentinel check
# can never drift from what the renderer actually substitutes.
ROOT_NAMESPACE_PATH_SENTINEL = "__ROOT_NAMESPACE__"

KNOWN_TOKENS = {
    "SUITE_NAME",
    "ROOT_NAMESPACE",
    "ROOT_NAMESPACE_LOWER",
    "PLUGIN_GUID_ROOT",
    "AUTHOR",
    "THUNDERSTORE_NAMESPACE",
    "MODULE_CATALOG_ROWS",
    "INCLUDED_MODULES_LIST",
    "COMPATIBILITY_BOUNDARIES_LIST",
    "RUNTIME_MODULE_CONSTRAINTS_LIST",
    "BOOTSTRAP_DIAGNOSTICS_MILESTONE",
    "BOOTSTRAP_MILESTONES_PROVEN_CLAUSE",
    "RELEASE_PACKAGE_FAMILIES_LIST",
    "SERVER_PACKAGE_FAMILY_LIST",
    "CLIENT_PACKAGE_FAMILY_LIST",
    "PENDING_RUNTIME_PROOF_LIST",
    "HARDENING_PENDING_PROOF_LIST",
    "PROJECT_SPEC_MILESTONE2_BODY",
    "INITIAL_MILESTONES_LIST",
    "CURRENT_STATE_BUILD_STATUS_LINES",
    "DEPLOY_TOPOLOGY_LINES",
    "DEPLOY_COMMANDS_LIST",
    "DEPLOY_SIDE_NOTES_LIST",
}


class RenderError(RuntimeError):
    pass


class TemplateSourceError(OSError):
    """A manifest-approved template path is not a plain regular file
    physically contained beneath the template root -- e.g. a symlink (or
    a symlinked parent directory) was substituted for it."""


# Which `ProjectModel` predicate gates each `template_manifest.OPTIONAL_TEMPLATE_FILES`
# key -- the three module-source groups plus the two package-side doc groups
# (`server_package_docs`/`client_package_docs`), derived from the same
# `has_server_package`/`has_client_package` model properties that drive
# `packaging/server/README.md`'s and `packaging/client/README.md`'s own content.
OPTIONAL_GROUP_PRESENT = {
    "server_core": lambda m: m.server_core is not None,
    "client": lambda m: m.client is not None,
    "shared_diagnostics": lambda m: m.shared_diagnostics is not None,
    "server_package_docs": lambda m: m.has_server_package,
    "client_package_docs": lambda m: m.has_client_package,
}


def _manifest_files_for(model: ProjectModel) -> frozenset[str]:
    """The manifest-approved paths to render for this specific model:
    everything required, plus each optional group's files iff its
    predicate is satisfied."""
    files = set(REQUIRED_TEMPLATE_FILES)
    for group, present in OPTIONAL_GROUP_PRESENT.items():
        if present(model):
            files |= OPTIONAL_TEMPLATE_FILES[group]
    return frozenset(files)


def _open_source_file(template_dir: Path, rel: str) -> int:
    """Open the manifest-approved `rel` path beneath `template_dir` as a
    file descriptor, refusing to follow a symlink at any path component
    — including the final one — and refusing anything that isn't a
    regular file.

    Validation and the eventual read share this exact fd, so there is no
    window between "this was checked" and "this was read" for a symlink
    swap to land in: `os.open(..., O_NOFOLLOW)` at each component *is*
    the check, and the fd it returns (once every component has passed)
    is the same fd the caller reads from. `Path.is_file()`/`read_bytes()`
    are deliberately not used here — both silently follow symlinks.

    Raises `FileNotFoundError` if a component is genuinely absent, or
    `TemplateSourceError` (itself an `OSError`) for anything unsafe: a
    symlink at any level, an intermediate component that isn't a
    directory, or a non-regular final target.
    """
    parts = rel.split("/")
    root_fd = os.open(template_dir, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fd, owns_fd = root_fd, False
        try:
            for part in parts[:-1]:
                try:
                    next_fd = os.open(part, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                except NotADirectoryError as exc:
                    raise TemplateSourceError(f"{rel}: {part!r} is not a directory") from exc
                except OSError as exc:
                    if exc.errno == errno.ELOOP:
                        raise TemplateSourceError(f"{rel}: {part!r} is a symlink") from exc
                    raise
                if owns_fd:
                    os.close(fd)
                fd, owns_fd = next_fd, True
            try:
                file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            except OSError as exc:
                if exc.errno == errno.ELOOP:
                    raise TemplateSourceError(f"{rel}: {parts[-1]!r} is a symlink") from exc
                raise
        finally:
            if owns_fd:
                os.close(fd)
    finally:
        os.close(root_fd)

    try:
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise TemplateSourceError(f"{rel}: not a regular file")
    except BaseException:
        os.close(file_fd)
        raise
    return file_fd


def _read_source_file(template_dir: Path, rel: str) -> bytes:
    fd = _open_source_file(template_dir, rel)
    with os.fdopen(fd, "rb") as f:
        return f.read()


def _ts_string_escape(value: str) -> str:
    """Escape `value` for embedding inside an existing TypeScript/
    JavaScript double-quoted string literal. JSON string escaping is a
    safe subset of JS string escaping -- quotes, backslashes, and every
    control character are escaped identically -- so a generated `.ts`
    file's syntax never depends solely on a token's input grammar."""
    return json.dumps(value)[1:-1]


def _substitute(text: str, tokens: dict[str, str], *, escape=None) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in tokens:
            raise RenderError(f"unknown template token {{{{{key}}}}}")
        value = tokens[key]
        return escape(value) if escape else value

    return TOKEN_RE.sub(repl, text)


def _generated_output_paths(model: ProjectModel) -> frozenset[str]:
    """Paths `generate()` writes *after* `render_tree()` returns: the
    programmatic `suite.config.json`/`.sln`/`suite.identity.lock.json`,
    and `suite_metadata.py sync`'s outputs. A manifest source must never
    render to one of these — it would either be silently overwritten by
    the real generated file or corrupt it.
    """
    ns = model.params.root_namespace
    return frozenset(
        {
            "suite.config.json",
            "suite.identity.lock.json",
            f"{ns}.sln",
            "build/Suite.Generated.props",
            f"src/{ns}.Common/SuiteConstants.Generated.cs",
            "packaging/profile-lock.json",
        }
    )


def _render_plan(model: ProjectModel) -> list[tuple[str, str]]:
    """The `(source_rel, dest_rel)` pairs for this render, fully
    containment- and collision-checked before any file is touched:

    - every destination normalizes to a relative, non-escaping path
    - no two sources render to the same destination
    - no source renders to a path `generate()` itself writes afterward

    This does not merely trust `ProjectParams.root_namespace` to already
    be safe (see `naming.validate_namespace()`) — it is a last line of
    defense independent of whether a caller happened to run
    `validate_params()` first.
    """
    root_namespace = model.params.root_namespace
    reserved = _generated_output_paths(model)
    plan: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    for rel in sorted(_manifest_files_for(model)):
        dest = "/".join(part.replace(ROOT_NAMESPACE_PATH_SENTINEL, root_namespace) for part in rel.split("/"))
        normalized = posixpath.normpath(dest)
        if normalized != dest or normalized == ".." or normalized.startswith("../") or posixpath.isabs(normalized):
            raise RenderError(f"rendered destination for {rel!r} escapes the output root: {dest!r}")
        if dest in reserved:
            raise RenderError(f"{rel!r} renders to {dest!r}, which collides with a generated project file")
        if dest in seen:
            raise RenderError(f"{seen[dest]!r} and {rel!r} both render to {dest!r}")
        seen[dest] = rel
        plan.append((rel, dest))
    return plan


def render_tree(model: ProjectModel, output_dir: Path, template_dir: Path = TEMPLATE_DIR) -> None:
    tokens = token_map(model)
    for rel, dest_str in _render_plan(model):
        data = _read_source_file(template_dir, rel)
        dest = output_dir / dest_str
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            dest.write_bytes(data)
            continue
        escape = _ts_string_escape if dest_str.endswith(".ts") else None
        dest.write_text(_substitute(text, tokens, escape=escape), encoding="utf-8", newline="\n")
        if rel.endswith(".sh"):
            dest.chmod(0o755)


# --- template self-validation (backs scripts/validate-template.sh) ---

SECRET_NAME_PATTERN = re.compile(r"(?i)password|secret|credential|\.pfx$")
GAME_ASSET_PATTERN = re.compile(r"(?i)\.dll$|publicized_assemblies|assembly_valheim_publicized|MMHOOK_|unstripped_corlib")

# Defense-in-depth classification for filesystem entries found under
# `template/` that aren't in the manifest — gives a specific reason for
# known-dangerous categories instead of a generic "unexpected file" error.
# The manifest allowlist above is the actual safety boundary: this list
# never approves a file, it only explains why an already-rejected one is
# dangerous.
FORBIDDEN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(^|/)\.env(\.|$)"), "a local .env file"),
    (re.compile(r"(^|/)__pycache__/"), "a Python bytecode cache directory"),
    (re.compile(r"\.pyc$|\.pyo$"), "compiled Python bytecode"),
    (re.compile(r"(^|/)bin/"), "a build output directory"),
    (re.compile(r"(^|/)obj/"), "a build output directory"),
    (re.compile(r"(^|/)artifacts/"), "a build output directory"),
    (re.compile(r"(^|/)Environment\.props$"), "local Valheim/Jotunn developer configuration"),
    (re.compile(r"(^|/)\.valheim/dev\.json$"), "local Valheim/Jotunn developer configuration"),
    (re.compile(r"(^|/)suite\.config\.json$"), "generated project metadata"),
    (re.compile(r"(^|/)build/Suite\.Generated\.props$"), "generated project metadata"),
    (re.compile(r"(^|/)packaging/profile-lock\.json$"), "generated project metadata"),
    (SECRET_NAME_PATTERN, "a file name that looks like a secret/credential"),
    (GAME_ASSET_PATTERN, "a game/publicized assembly or runtime binary"),
]


def _forbidden_reason(rel: str) -> str | None:
    for pattern, reason in FORBIDDEN_PATTERNS:
        if pattern.search(rel):
            return reason
    return None


def validate_template(template_dir: Path = TEMPLATE_DIR) -> list[str]:
    errors: list[str] = list(validate_manifest_structure())
    approved = all_template_files()
    checkable = {rel for rel in approved if invalid_manifest_path_reason(rel) is None}

    for rel in sorted(checkable):
        try:
            fd = _open_source_file(template_dir, rel)
        except FileNotFoundError:
            errors.append(f"missing required template file: {rel}")
            continue
        except OSError as exc:
            errors.append(f"template source path is not a plain file physically inside the template root: {rel}: {exc}")
            continue
        try:
            st = os.fstat(fd)
        except OSError:
            os.close(fd)
            raise
        if rel.endswith(".sh") and not (st.st_mode & stat.S_IXUSR):
            errors.append(f"template script is not executable: {rel}")
        with os.fdopen(fd, "rb") as f:
            data = f.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for match in TOKEN_RE.finditer(text):
            if match.group(1) not in KNOWN_TOKENS:
                errors.append(f"unknown token {{{{{match.group(1)}}}}} in {rel}")

    expected_dirs: set[str] = set()
    for rel in approved:
        parts = rel.split("/")
        for i in range(1, len(parts)):
            expected_dirs.add("/".join(parts[:i]))

    for f in sorted(template_dir.rglob("*")):
        rel = f.relative_to(template_dir).as_posix()
        mode = f.lstat().st_mode
        if stat.S_ISDIR(mode):
            if rel not in expected_dirs:
                errors.append(f"unexpected directory not required by the template manifest: {rel}")
            continue
        if not stat.S_ISREG(mode):
            errors.append(f"template entry is not a regular file or directory: {rel}")
            continue
        if rel in approved:
            continue
        reason = _forbidden_reason(rel)
        if reason:
            errors.append(f"template must not contain {reason}: {rel}")
        else:
            errors.append(f"unexpected file not listed in the template manifest: {rel}")

    return errors


if __name__ == "__main__":
    import sys

    errs = validate_template()
    if errs:
        for e in errs:
            print(f"template error: {e}", file=sys.stderr)
        sys.exit(2)
    print("template: structure valid, tokens known, no unexpected/forbidden files")
