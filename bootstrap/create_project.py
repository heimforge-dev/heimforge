"""CLI orchestration: render a template into a fresh standalone project,
generate its identity-dependent metadata, and validate the result.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import stat
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import naming
from .model import ProjectModel, ProjectParams, build_model, solution_text, suite_config_dict, validate_params
from .render import render_tree
from .validate_generated import ValidationResult, validate_generated


class GenerationError(RuntimeError):
    pass


def _prompt(label: str, default: str | None = None, required: bool = True) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if not value and default is not None:
            return default
        if value or not required:
            return value
        print("  (required)")


def _prompt_yes_no(label: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        value = input(f"{label} {suffix}: ").strip().lower()
        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print("  (please answer y or n)")


def interactive_params() -> tuple[ProjectParams, str]:
    suite_name = _prompt("Suite name")
    root_namespace = _prompt("Root namespace", default=suite_name)
    plugin_guid_root = _prompt("Plugin GUID root")
    author = _prompt("Author")
    thunderstore_namespace = _prompt("Thunderstore namespace")
    suite_version = _prompt("Initial version", default="0.1.0")
    output_directory = _prompt("Output directory")
    include_server_core = _prompt_yes_no("Include ServerCore?")
    include_client = _prompt_yes_no("Include Client?")
    include_shared_diagnostics = _prompt_yes_no("Include Shared.Diagnostics?")
    params = ProjectParams(
        suite_name=suite_name,
        root_namespace=root_namespace,
        plugin_guid_root=plugin_guid_root,
        author=author,
        thunderstore_namespace=thunderstore_namespace,
        suite_version=suite_version,
        include_server_core=include_server_core,
        include_client=include_client,
        include_shared_diagnostics=include_shared_diagnostics,
    )
    return params, output_directory


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a standalone Valheim mod-suite project.")
    parser.add_argument("--name")
    parser.add_argument("--namespace")
    parser.add_argument("--guid")
    parser.add_argument("--author")
    parser.add_argument("--thunderstore-namespace")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--output")
    parser.add_argument("--no-server-core", action="store_true")
    parser.add_argument("--no-client", action="store_true")
    parser.add_argument("--no-shared-diagnostics", action="store_true")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def resolve_params(args: argparse.Namespace) -> tuple[ProjectParams, str]:
    if args.name is None:
        if not sys.stdin.isatty():
            raise GenerationError("missing required --name (and other flags) for non-interactive use")
        return interactive_params()

    missing = [
        flag
        for flag, value in (
            ("--guid", args.guid),
            ("--author", args.author),
            ("--thunderstore-namespace", args.thunderstore_namespace),
            ("--output", args.output),
        )
        if value is None
    ]
    if missing:
        raise GenerationError(f"missing required flags for non-interactive use: {', '.join(missing)}")

    params = ProjectParams(
        suite_name=args.name,
        root_namespace=args.namespace or args.name,
        plugin_guid_root=args.guid,
        author=args.author,
        thunderstore_namespace=args.thunderstore_namespace,
        suite_version=args.version,
        include_server_core=not args.no_server_core,
        include_client=not args.no_client,
        include_shared_diagnostics=not args.no_shared_diagnostics,
    )
    return params, args.output


BOOTSTRAPPER_ROOT = Path(__file__).resolve().parents[1]
_VCS_MARKERS = (".git", ".hg", ".svn")
_RENAME_NOREPLACE = 0x1


class _AtomicPromotionUnavailable(RuntimeError):
    """The `renameat2(RENAME_NOREPLACE)` primitive isn't available here."""


def _renameat2_noreplace(src_name: str, dst_name: str, dir_fd: int) -> None:
    """Atomically rename `src_name` to `dst_name`, both resolved relative
    to `dir_fd`, failing if `dst_name` already exists.

    `os.rename` silently replaces an existing destination on POSIX, which
    would let a concurrently created entry be clobbered without a trace.
    There is no portable stdlib equivalent, so this wraps the Linux
    `renameat2(2)` syscall directly via `ctypes`; this bootstrapper's
    canonical execution environment is WSL/Linux. Both names are resolved
    against the same directory-fd rather than a re-resolved pathname, so
    a rename of that directory's own name elsewhere cannot redirect the
    operation. If the syscall is unavailable (older glibc, non-Linux),
    this fails closed by raising `_AtomicPromotionUnavailable` rather
    than falling back to a racy plain rename.
    """
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        renameat2 = libc.renameat2
    except (OSError, AttributeError) as exc:
        raise _AtomicPromotionUnavailable("renameat2(2) is unavailable on this system") from exc

    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    ctypes.set_errno(0)
    rc = renameat2(dir_fd, os.fsencode(src_name), dir_fd, os.fsencode(dst_name), _RENAME_NOREPLACE)
    if rc != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), dst_name)


@dataclass(frozen=True)
class _EntryState:
    """Filesystem identity of a single directory entry, from `lstat`/`fstat`
    — the entry itself, never resolved through a symlink."""

    exists: bool
    is_symlink: bool
    is_dir: bool
    dev: int | None = None
    ino: int | None = None


_ABSENT_ENTRY = _EntryState(exists=False, is_symlink=False, is_dir=False)


def _lstat_entry_at(name: str, dir_fd: int) -> _EntryState:
    try:
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return _ABSENT_ENTRY
    return _EntryState(
        exists=True,
        is_symlink=stat.S_ISLNK(st.st_mode),
        is_dir=stat.S_ISDIR(st.st_mode),
        dev=st.st_dev,
        ino=st.st_ino,
    )


def _entry_state_matches(current: _EntryState, initial: _EntryState) -> bool:
    """Same on-disk object `_approve_destination` inspected at generation
    start? Absence must match absence; presence must match the exact
    (non-symlink, same-device, same-inode) directory."""
    if current.exists != initial.exists:
        return False
    if not current.exists:
        return True
    return (
        not current.is_symlink
        and not initial.is_symlink
        and current.is_dir
        and initial.is_dir
        and current.dev == initial.dev
        and current.ino == initial.ino
    )


def _open_dir_at(name: str, dir_fd: int) -> int:
    return os.open(name, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)


def _dir_content_state(fd: int) -> tuple[bool, bool]:
    """`(is_empty, has_vcs_marker)` for the directory referenced by `fd`,
    read directly off that open file descriptor rather than a pathname —
    so it always reflects the exact object the caller is holding, even if
    its directory-entry name has since been renamed or replaced."""
    names = {entry.name for entry in os.scandir(fd)}
    return not names, bool(names & set(_VCS_MARKERS))


def _clear_dir_contents(fd: int, *, protect_markers: bool = False) -> None:
    """Recursively remove everything inside the directory referenced by
    `fd`.

    When `protect_markers` is set — only for the outermost call, on the
    directory actually being discarded — a top-level `.git`/`.hg`/`.svn`
    entry (directory, regular file, or symlink; whichever it currently
    is) is left untouched instead of deleted. This is decided per entry
    during the single `scandir` pass that also does the deleting, so
    there is no separate scan-then-delete step to race: an entry either
    is or isn't a protected marker at the instant it's examined, and
    that's the same instant it would otherwise be removed. VCS
    protection is unconditional, even for a destination explicitly
    authorized for recursive removal via `force=True`. Nested markers
    inside ordinary subdirectories are cleared normally — this mirrors
    the VCS check's own top-level-only scope, not a new policy.
    """
    for entry in os.scandir(fd):
        if protect_markers and entry.name in _VCS_MARKERS:
            continue
        if entry.is_dir(follow_symlinks=False):
            child_fd = _open_dir_at(entry.name, fd)
            try:
                _clear_dir_contents(child_fd)
            finally:
                os.close(child_fd)
            os.rmdir(entry.name, dir_fd=fd)
        else:
            os.unlink(entry.name, dir_fd=fd)


def _remove_dir_at(name: str, dir_fd: int, *, fd: int | None = None) -> None:
    """Recursively remove `name` within `dir_fd`.

    If `fd` — an already-open descriptor for that exact directory object —
    is given, its contents are cleared through that descriptor rather than
    by re-resolving `name`, so a directory-entry swap after `fd` was
    opened cannot redirect the deletion. A top-level VCS marker is never
    deleted (see `_clear_dir_contents`); if one is present, the directory
    is non-empty afterward and the final `rmdir` below fails, preserving
    the whole isolated backup rather than forcing the marker's removal.
    Otherwise, the final (by then empty) directory shell is removed by
    name; `rmdir` refuses a non-empty directory, so a replacement planted
    at that name is never destroyed, merely left in place.
    """
    owns_fd = fd is None
    if owns_fd:
        fd = _open_dir_at(name, dir_fd)
    try:
        _clear_dir_contents(fd, protect_markers=True)
    finally:
        if owns_fd:
            os.close(fd)
    os.rmdir(name, dir_fd=dir_fd)


def _try_remove_dir_at(name: str, dir_fd: int, *, fd: int | None = None) -> None:
    """Best-effort `_remove_dir_at`: swallow failures so a cleanup hiccup
    never masks the error already being reported, and never destroys a
    replacement object that a non-empty-directory `rmdir` refused."""
    try:
        _remove_dir_at(name, dir_fd, fd=fd)
    except OSError:
        pass


def _split_final_component(candidate: Path) -> tuple[Path, str]:
    """Split into a canonical parent directory and a raw final component.

    The final component is the exact destination entry the caller named;
    unlike the parent, it is never passed through `resolve()`. A symlink
    planted at that exact path must never be able to redirect subsequent
    location checks, isolation, or promotion to whatever it points at.
    """
    expanded = Path(candidate).expanduser()
    name = expanded.name
    parent = expanded.parent.resolve()
    if not name or name in (".", ".."):
        raise GenerationError(f"refusing unsafe output directory: {parent}")
    return parent, name


def _validate_output_location(nominal: Path) -> None:
    """Reject unsafe output *locations*, by name and position only — never
    by following the final component, whether or not it exists yet."""
    if nominal == Path.home().resolve():
        raise GenerationError(f"refusing unsafe output directory: {nominal}")
    if nominal.is_relative_to(BOOTSTRAPPER_ROOT) or BOOTSTRAPPER_ROOT.is_relative_to(nominal):
        raise GenerationError(
            "refusing output directory that is the bootstrapper repository, "
            f"or an ancestor/descendant of it: {nominal}"
        )
    if nominal.is_mount():
        raise GenerationError(f"refusing filesystem mount point as output directory: {nominal}")


def _safe_output_dir(raw: str) -> Path:
    parent, name = _split_final_component(Path(raw))
    nominal = parent / name
    _validate_output_location(nominal)
    return nominal


@dataclass(frozen=True)
class _DestinationApproval:
    """The destination identity and overwrite authorization decided once,
    at generation start, anchored to the approved parent *directory
    object* via `parent_fd` rather than its (rebindable) pathname.
    `_promote_staging` never re-derives permission from a fresh reading
    of the destination path; it only ever asks whether the object it
    isolates at the swap boundary is still this one, in this state.
    """

    parent_fd: int
    name: str
    initial: _EntryState
    initially_empty: bool


def _open_validated_parent_dir(parent: Path, name: str) -> int:
    """Open `parent` as a directory and validate the *opened object*,
    not the pathname examined before the open.

    `O_NOFOLLOW` refuses to follow a symlink planted at that exact entry.
    The resulting descriptor's own current, real path — read live via
    `/proc/<pid>/fd/<fd>`, never re-derived from the pre-open string — is
    then compared against `parent` and re-run through the destination's
    protected-location checks. If the entry became a symlink, or now
    names a different directory, in the window between
    `_validate_output_location` and this open, generation fails closed
    instead of silently anchoring the whole transaction to whatever now
    occupies the name.
    """
    try:
        parent_fd = os.open(parent, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise GenerationError(f"refusing unsafe output directory: {parent}: {exc}") from exc

    try:
        resolved_parent = Path(f"/proc/{os.getpid()}/fd/{parent_fd}").resolve()
        if resolved_parent != parent:
            raise GenerationError(
                f"refusing output directory: {parent} no longer refers to the directory that was approved"
            )
        _validate_output_location(resolved_parent / name)
    except BaseException:
        os.close(parent_fd)
        raise
    return parent_fd


def _current_parent_path(parent_fd: int) -> Path:
    """The parent directory's current, real pathname, read live off the
    held descriptor — correct even if the directory has since been
    renamed elsewhere, unlike a value captured once at approval time.
    Used only for human-readable recovery messages."""
    return Path(f"/proc/{os.getpid()}/fd/{parent_fd}").resolve()


def _approve_destination(candidate: Path, force: bool) -> _DestinationApproval:
    """Validate and capture the approved destination for `generate()`.

    Location safety (roots, mounts, home, the bootstrapper repository) is
    checked without ever resolving the final path component through a
    symlink. The approved parent directory is then opened and held open
    for the caller (`parent_fd`) so every later transaction operation is
    anchored to that exact directory object, immune to the parent's own
    pathname later being renamed or replaced. An existing destination
    must not itself be a symlink or a version-control checkout, and —
    without `force` — must be empty. What is found here (existence,
    identity, and whether it was empty) becomes the sole authorization
    re-checked at the swap boundary; `force` never authorizes replacing
    whatever object, or whatever content, happens to occupy the path
    later — an initially empty directory only ever authorizes replacing
    an empty directory.
    """
    parent, name = _split_final_component(Path(candidate))
    nominal = parent / name
    _validate_output_location(nominal)

    parent.mkdir(parents=True, exist_ok=True)
    parent_fd = _open_validated_parent_dir(parent, name)
    try:
        initial = _lstat_entry_at(name, parent_fd)
        if initial.is_symlink:
            raise GenerationError(f"refusing output directory that is a symlink: {nominal}")
        if initial.exists and not initial.is_dir:
            raise GenerationError(f"refusing output directory that is not a directory: {nominal}")

        initially_empty = True
        if initial.exists:
            child_fd = _open_dir_at(name, parent_fd)
            try:
                initially_empty, has_vcs_marker = _dir_content_state(child_fd)
            finally:
                os.close(child_fd)
            if has_vcs_marker:
                raise GenerationError(f"refusing to overwrite an existing version-control checkout: {nominal}")
            if not initially_empty and not force:
                raise GenerationError(f"output directory is not empty: {nominal}; pass --force to overwrite")
    except BaseException:
        os.close(parent_fd)
        raise

    return _DestinationApproval(parent_fd=parent_fd, name=name, initial=initial, initially_empty=initially_empty)


def _generate_isolated_name(target_name: str) -> str:
    return f".{target_name}.isolated-{uuid.uuid4().hex}"


def _promote_staging(approval: _DestinationApproval, staging_name: str) -> None:
    """Swap the validated staging directory into the approved destination.

    Isolate-then-inspect, entirely relative to `approval.parent_fd`: the
    destination entry is atomically (no-clobber) renamed aside first — a
    rename never follows a symlink, it renames the link entry itself —
    and only the isolated copy is compared against the identity and
    content state `_approve_destination` captured at generation start.
    Nothing appearing, retargeting, gaining content, or being swapped in
    at the destination between approval and this call can affect what
    gets inspected, because by the time it is inspected it has already
    been moved off the live, racy name, onto a private one this function
    chose. The final promotion (and any restore) is also no-clobber, so a
    third entry created after isolation can never be silently overwritten.

    Cleanup of a discarded isolated backup mirrors what was actually
    authorized: an initially empty destination only ever authorized
    replacing emptiness, so its isolated backup is removed with a single
    fd-relative `rmdir` — which fails if anything is inside — never a
    recursive clear; an initially non-empty destination explicitly
    approved via `force=True` keeps the existing recursive cleanup for
    that specific, identity-checked object. Any recovery message reports
    the parent's current, live path (via the held descriptor), not a
    pathname captured before generation began.
    """
    parent_fd = approval.parent_fd
    target_name = approval.name
    isolated_name = _generate_isolated_name(target_name)

    def _current_target_path() -> Path:
        return _current_parent_path(parent_fd) / target_name

    isolated_fd = None
    try:
        try:
            _renameat2_noreplace(target_name, isolated_name, parent_fd)
        except FileNotFoundError:
            isolated_name = None
            isolated_state = _ABSENT_ENTRY
        except _AtomicPromotionUnavailable as exc:
            raise GenerationError(f"cannot atomically isolate {_current_target_path()}: {exc}") from exc
        except OSError as exc:
            raise GenerationError(f"failed to isolate {_current_target_path()} for replacement: {exc}") from exc
        else:
            isolated_state = _lstat_entry_at(isolated_name, parent_fd)
            if isolated_state.is_dir and not isolated_state.is_symlink:
                try:
                    isolated_fd = _open_dir_at(isolated_name, parent_fd)
                except OSError:
                    isolated_fd = None

        authorized = _entry_state_matches(isolated_state, approval.initial)
        if authorized and isolated_fd is not None:
            is_empty, has_vcs_marker = _dir_content_state(isolated_fd)
            if has_vcs_marker or (approval.initially_empty and not is_empty):
                authorized = False

        def _restore() -> bool:
            if isolated_name is None:
                return True
            try:
                _renameat2_noreplace(isolated_name, target_name, parent_fd)
                return True
            except (OSError, _AtomicPromotionUnavailable):
                return False

        if not authorized:
            restored = _restore()
            detail = (
                "nothing was overwritten"
                if restored
                else f"the original is preserved at {_current_parent_path(parent_fd) / isolated_name}"
            )
            raise GenerationError(
                f"refusing to replace {_current_target_path()}: its contents changed since generation began; {detail}"
            )

        try:
            _renameat2_noreplace(staging_name, target_name, parent_fd)
        except (_AtomicPromotionUnavailable, OSError) as exc:
            restored = _restore()
            detail = (
                "its prior contents were restored"
                if restored
                else f"the original data is preserved at {_current_parent_path(parent_fd) / isolated_name}"
            )
            raise GenerationError(f"failed to promote generated project to {_current_target_path()}: {exc}; {detail}") from exc

        if isolated_fd is not None:
            if approval.initially_empty:
                try:
                    os.rmdir(isolated_name, dir_fd=parent_fd)
                except OSError:
                    pass  # unexpected content appeared; preserve it, leave the backup orphaned
            else:
                _try_remove_dir_at(isolated_name, parent_fd, fd=isolated_fd)
    finally:
        if isolated_fd is not None:
            os.close(isolated_fd)


def generate(params: ProjectParams, output_dir: Path, force: bool = False) -> ValidationResult:
    validate_params(params)
    approval = _approve_destination(output_dir, force)
    parent_fd = approval.parent_fd
    try:
        staging_name = f".{approval.name}.staging-{uuid.uuid4().hex}"
        os.mkdir(staging_name, dir_fd=parent_fd)
        staging_fd = _open_dir_at(staging_name, parent_fd)
        try:
            staging_dir = Path(f"/proc/{os.getpid()}/fd/{staging_fd}")
            model: ProjectModel = build_model(params)
            render_tree(model, staging_dir)

            (staging_dir / "suite.config.json").write_text(
                json.dumps(suite_config_dict(model), indent=2) + "\n", encoding="utf-8"
            )
            (staging_dir / f"{params.root_namespace}.sln").write_text(solution_text(model), encoding="utf-8")

            sync = subprocess.run(
                ["python3", "scripts/suite_metadata.py", "sync"], cwd=staging_dir, text=True, capture_output=True
            )
            if sync.returncode != 0:
                raise GenerationError(f"suite_metadata.py sync failed: {sync.stdout}{sync.stderr}")

            result = validate_generated(staging_dir, params)
            if result.ok:
                _promote_staging(approval, staging_name)
            else:
                _try_remove_dir_at(staging_name, parent_fd, fd=staging_fd)
        except BaseException:
            _try_remove_dir_at(staging_name, parent_fd, fd=staging_fd)
            raise
        finally:
            os.close(staging_fd)
    finally:
        os.close(parent_fd)
    return result


def _print_summary(params: ProjectParams, model: ProjectModel, output_dir: Path, result: ValidationResult) -> None:
    for note in result.skipped:
        print(f"note: {note}")
    for warning in result.warnings:
        print(f"note: {warning}")

    print(f"Created {params.suite_name}")
    print()
    print("Solution:")
    print(f"  {output_dir}/{params.root_namespace}.sln")
    print()
    print("Projects:")
    for m in model.modules:
        print(f"  {m.project_name}")
    print()
    print("Validation:")
    print("  PASS" if result.ok else "  FAIL")
    if not result.ok:
        for error in result.errors:
            print(f"    - {error}")
        return
    print()
    print("Next:")
    print(f"  cd {output_dir}")
    print("  cp Environment.props.example Environment.props")
    print("  cp .valheim/dev.json.example .valheim/dev.json")
    print("  ./scripts/preflight.sh --portable")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        params, output_raw = resolve_params(args)
        output_dir = _safe_output_dir(output_raw)
        result = generate(params, output_dir, force=args.force)
    except (GenerationError, naming.NamingError) as exc:
        print(f"create-project: {exc}", file=sys.stderr)
        return 2

    model = build_model(params)
    _print_summary(params, model, output_dir, result)
    return 0 if result.ok else 2


if __name__ == "__main__":
    sys.exit(main())
