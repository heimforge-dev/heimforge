#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import stat
import sys
import unicodedata
import zipfile
from pathlib import Path

import suite_metadata as metadata

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "packages"
ZIP_TIME = (2020, 1, 1, 0, 0, 0)

class PackageError(RuntimeError):
    pass


_UNSET = object()


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise PackageError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PackageError(f"{path} must contain a JSON object")
    return value


def _validate_name(value: str, field: str) -> str:
    """Reuse suite_metadata's path-component grammar but fail with
    `PackageError`, so packaging fails safely even when invoked directly
    with a config that was never run through `suite_metadata.validate()`."""
    try:
        return metadata.validate_path_component(value, field)
    except metadata.MetadataError as exc:
        raise PackageError(str(exc)) from exc


def _package_output_path(name: str, version: str) -> Path:
    _validate_name(name, "package name")
    try:
        metadata.validate_semver(version, "package version")
        metadata.validate_component_length(f"{name}-{version}.zip", "package filename")
    except metadata.MetadataError as exc:
        raise PackageError(str(exc)) from exc
    return metadata.contain(OUT / f"{name}-{version}.zip", OUT, error_cls=PackageError)


def validate_arcname(name: str) -> str:
    """Archive-member paths are portable, normalized POSIX-relative names."""
    if not isinstance(name, str) or not name or name != name.strip():
        raise PackageError(f"unsafe archive member path: {name!r}")
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        raise PackageError(f"archive member path has control characters: {name!r}")
    if "\\" in name:
        raise PackageError(f"archive member path must not contain a backslash: {name!r}")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise PackageError(f"archive member path must not be absolute: {name!r}")
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PackageError(f"archive member path has an unsafe component: {name!r}")
    if posixpath.normpath(name) != name:
        raise PackageError(f"archive member path is not normalized: {name!r}")
    return name


def _require_arcname_under(name: str, prefix: str) -> str:
    validate_arcname(name)
    if name != prefix and not name.startswith(f"{prefix}/"):
        raise PackageError(f"archive member {name!r} escapes its intended directory {prefix!r}")
    return name


def artifact_for(project: str, tfm: str) -> Path:
    _validate_name(project, "project")
    _validate_name(tfm, "targetFramework")
    exact = metadata.contain(
        ROOT / "src" / project / "bin" / "Release" / tfm / f"{project}.dll", ROOT / "src", error_cls=PackageError
    )
    if not exact.is_file():
        raise PackageError(f"missing Release artifact: {exact.relative_to(ROOT)}")
    return exact


def _register_arcname(arcname: str, seen: set[str]) -> None:
    validate_arcname(arcname)
    key = arcname.casefold()
    if key in seen:
        raise PackageError(f"duplicate archive member: {arcname!r}")
    seen.add(key)


def add_bytes(zf: zipfile.ZipFile, arcname: str, data: bytes, seen: set[str]) -> None:
    _register_arcname(arcname, seen)
    info = zipfile.ZipInfo(arcname, ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, data)


def _plan_member(members: list[tuple[str, bytes]], arcname: str, data: bytes, seen: set[str]) -> None:
    _register_arcname(arcname, seen)
    members.append((arcname, data))


def _plan_package(name: str, version: str, modules: list[str], cfg: dict, package_kind: str) -> tuple[Path, list[tuple[str, bytes]]]:
    suite_name = _validate_name(cfg["suiteName"], "suiteName")
    filename = _package_output_path(name, version)
    if not isinstance(modules, list) or not all(isinstance(module, str) for module in modules):
        raise PackageError("package modules must be a list of project names")
    try:
        common = cfg["packages"]["commonModule"]
        projects = cfg["projects"]
    except (KeyError, TypeError) as exc:
        raise PackageError("invalid package metadata") from exc
    if not isinstance(common, str) or not isinstance(projects, dict):
        raise PackageError("invalid package metadata")
    ordered = [common] + [module for module in modules if module != common]
    package_info = {
        "schemaVersion": 1,
        "suite": cfg["suiteName"],
        "version": version,
        "packageKind": package_kind,
        "modules": ordered,
        "dependencies": {
            "BepInExPack_Valheim": cfg["bepInExPackVersion"],
            "Jotunn": cfg["jotunnVersion"],
        },
    }
    plugin_root = f"BepInEx/plugins/{suite_name}"
    members: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    for project in ordered:
        try:
            tfm = projects[project]["targetFramework"]
        except (KeyError, TypeError) as exc:
            raise PackageError(f"package references unknown project: {project!r}") from exc
        dll = artifact_for(project, tfm)
        arcname = _require_arcname_under(f"{plugin_root}/{dll.name}", plugin_root)
        _plan_member(members, arcname, dll.read_bytes(), seen)
    _plan_member(members, "package-info.json", (json.dumps(package_info, indent=2) + "\n").encode(), seen)
    for doc in ("README.md", "CHANGELOG.md", "LICENSE"):
        source = ROOT / doc
        if source.exists():
            _plan_member(members, doc, source.read_bytes(), seen)
    return filename, members


def _write_package(
    filename: Path,
    members: list[tuple[str, bytes]],
    *,
    parent: metadata._OutputParent | None = None,
    final_target: metadata._FinalTarget | object = _UNSET,
) -> Path:
    owns_parent = parent is None
    if parent is None:
        parent, final_name = metadata.open_confined_parent(filename, error_cls=PackageError)
    else:
        parent.verify(PackageError)
        final_name = filename.name
    if final_target is _UNSET:
        final_target = metadata.preflight_output_target(parent, final_name, error_cls=PackageError)
    temp: metadata._TemporaryOutput | None = None
    promoted = False
    try:
        temp = metadata.create_temp_file(parent, final_name, error_cls=PackageError)
        with os.fdopen(os.dup(temp.file_fd), "w+b") as output:
            with zipfile.ZipFile(output, "w") as zf:
                seen: set[str] = set()
                for arcname, data in members:
                    add_bytes(zf, arcname, data, seen)
        metadata.promote_temp_file(parent, temp, final_name, final_target=final_target, error_cls=PackageError)
        promoted = True
    finally:
        final_target.close()
        if temp is not None:
            if not promoted:
                metadata._remove_temporary_output(parent, temp)
            temp.close()
        if owns_parent:
            parent.close()
    return filename


def create_package(name: str, version: str, modules: list[str], cfg: dict, package_kind: str) -> Path:
    filename, members = _plan_package(name, version, modules, cfg, package_kind)
    return _write_package(filename, members)




def _clean_output_directory(parent: metadata._OutputParent) -> None:
    """Two-pass cleanup: validate every matching candidate before deleting
    any of them, so a non-regular entry can never be discovered only after
    earlier candidates -- including SHA256SUMS -- have already been removed."""
    try:
        with os.scandir(parent.directory_fd) as entries:
            candidates = [entry.name for entry in entries if entry.name.endswith(".zip") or entry.name == "SHA256SUMS"]
    except OSError as exc:
        raise PackageError(f"cannot list package outputs for cleanup: {exc}") from exc

    for name in candidates:
        try:
            info = os.stat(name, dir_fd=parent.directory_fd, follow_symlinks=False)
        except OSError as exc:
            raise PackageError(f"cannot inspect package output {name} during cleanup: {exc}") from exc
        if not stat.S_ISREG(info.st_mode):
            raise PackageError(f"refusing non-regular package output during cleanup: {name}")

    for name in candidates:
        try:
            os.unlink(name, dir_fd=parent.directory_fd)
        except OSError as exc:
            raise PackageError(f"cannot clean package output {name}: {exc}") from exc






def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true", help="Remove old package ZIPs before writing")
    args = parser.parse_args()
    try:
        cfg = metadata.load_config()
        metadata.validate(cfg)
        metadata.validate_identity(cfg)
        metadata.validate_solution_membership(cfg)
        for generated_path, expected in metadata.expected_files(cfg).items():
            if not generated_path.exists() or generated_path.read_text(encoding="utf-8") != expected:
                raise PackageError(
                    f"generated metadata is stale: {generated_path.relative_to(ROOT)}; "
                    "run python3 scripts/suite_metadata.py sync"
                )
        version = cfg["suiteVersion"]
        definitions = metadata.package_definitions(cfg)
        plans = [_plan_package(name, version, modules, cfg, kind) for name, modules, kind in definitions]
        seen_outputs: dict[str, Path] = {}
        for filename, _members in plans:
            key = filename.name.casefold()
            if key in seen_outputs:
                raise PackageError(
                    f"duplicate package output path(s): {seen_outputs[key].name!r}, {filename.name!r}"
                )
            seen_outputs[key] = filename
        metadata.contain(OUT, ROOT / "artifacts", error_cls=PackageError)
        checksum_path = metadata.contain(OUT / "SHA256SUMS", OUT, error_cls=PackageError)

        output_parent, _checksum_name = metadata.open_confined_parent(checksum_path, error_cls=PackageError)
        try:
            output_parent.verify(PackageError)
            for filename, _members in plans:
                metadata.preflight_output_target(output_parent, filename.name, error_cls=PackageError).close()
            metadata.preflight_output_target(output_parent, checksum_path.name, error_cls=PackageError).close()

            if args.clean:
                _clean_output_directory(output_parent)

            created = []
            for filename, members in plans:
                final_target = metadata.preflight_output_target(output_parent, filename.name, error_cls=PackageError)
                created.append(_write_package(filename, members, parent=output_parent, final_target=final_target))
            output_parent.verify(PackageError)
            lines = []
            for path in sorted(created):
                try:
                    file_fd = os.open(
                        path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=output_parent.directory_fd
                    )
                except OSError as exc:
                    raise PackageError(f"cannot read created package {path.name}: {exc}") from exc
                with os.fdopen(file_fd, "rb") as package_file:
                    digest = hashlib.sha256(package_file.read()).hexdigest()
                lines.append(f"{digest}  {path.name}")
            checksum_target = metadata.preflight_output_target(output_parent, checksum_path.name, error_cls=PackageError)
            metadata.atomic_write_text(
                checksum_path, "\n".join(lines) + "\n", parent=output_parent, final_target=checksum_target
            )
            print("created packages:")
            for path in created:
                print(f"  {path.relative_to(ROOT)}")
            print(f"  {(OUT / 'SHA256SUMS').relative_to(ROOT)}")
            return 0
        finally:
            output_parent.close()
    except (PackageError, metadata.MetadataError, OSError) as exc:
        print(f"package error: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
