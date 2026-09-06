#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import uuid
from pathlib import Path

import suite_metadata as metadata

ROOT = Path(__file__).resolve().parents[1]

class DeployError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise DeployError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DeployError(f"{path} must contain a JSON object")
    return value


def safe_destination(raw: str) -> Path:
    dest = Path(raw).expanduser()
    if not dest.is_absolute():
        raise DeployError(f"deployment destination must be absolute: {dest}")
    resolved = dest.resolve(strict=False)
    if resolved == Path("/") or resolved == Path.home().resolve():
        raise DeployError(f"refusing unsafe deployment destination: {resolved}")
    return resolved


def artifact_for(project: str, tfm: str, configuration: str) -> Path:
    exact = ROOT / "src" / project / "bin" / configuration / tfm / f"{project}.dll"
    if exact.is_file():
        return exact
    candidates = sorted((ROOT / "src" / project / "bin" / configuration).glob(f"**/{project}.dll"))
    candidates = [p for p in candidates if p.is_file()]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise DeployError(f"missing build artifact for {project} ({configuration}/{tfm}); run ./scripts/build.sh {configuration}")
    raise DeployError(f"ambiguous build artifacts for {project}: {', '.join(str(p.relative_to(ROOT)) for p in candidates)}")


def modules_for(cfg: dict, target: str) -> list[str]:
    packages = cfg["packages"]
    common = packages["commonModule"]
    if target == "server":
        modules = packages["serverModules"]
    else:
        modules = packages["requiredClientModules"] + packages["optionalClientModules"] + packages["clientOnlyModules"]
    ordered = [common]
    for item in modules:
        if item not in ordered:
            ordered.append(item)
    return ordered


def open_deployment_dir(destination: Path) -> int:
    """Open the validated deployment directory once, without following a
    symlinked final path component, for every stale-cleanup and DLL write
    below to share -- never re-resolved by pathname per file."""
    try:
        return os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise DeployError(f"cannot open deployment directory {destination}: {exc}") from exc


def deploy_dll(source: Path, dir_fd: int, name: str) -> None:
    """Copy `source` into the directory referenced by `dir_fd` as `name`,
    replacing whatever directory entry currently occupies `name` -- including
    a symlink -- via an atomic rename of a freshly written temporary file.
    The existing entry, if any, is never opened for writing, so a symlinked
    `name` is replaced as a directory entry instead of followed."""
    try:
        existing = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    except OSError as exc:
        raise DeployError(f"cannot inspect deployment target {name}: {exc}") from exc
    if existing is not None and not stat.S_ISLNK(existing.st_mode) and not stat.S_ISREG(existing.st_mode):
        raise DeployError(f"refusing to deploy over non-regular deployment target: {name}")

    temp_name = None
    temp_fd = None
    for _ in range(16):
        candidate = f".{name}.{uuid.uuid4().hex}.tmp"
        try:
            temp_fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=dir_fd)
            temp_name = candidate
            break
        except FileExistsError:
            continue
    if temp_fd is None:
        raise DeployError(f"cannot allocate a temporary deployment file for {name}")

    promoted = False
    try:
        try:
            with open(source, "rb") as src:
                source_stat = os.fstat(src.fileno())
                with os.fdopen(temp_fd, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                    dst.flush()
                    os.fchmod(dst.fileno(), stat.S_IMODE(source_stat.st_mode))
                    os.utime(dst.fileno(), ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
                    os.fsync(dst.fileno())
            os.replace(temp_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            promoted = True
        except OSError as exc:
            raise DeployError(f"cannot deploy {name}: {exc}") from exc
    finally:
        if not promoted:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("client", "server"), required=True)
    parser.add_argument("--configuration", choices=("Debug", "Release"), default="Debug")
    parser.add_argument("--destination")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        cfg = metadata.load_config()
        metadata.validate(cfg)
        for generated_path, expected in metadata.expected_files(cfg).items():
            if not generated_path.exists() or generated_path.read_text(encoding="utf-8") != expected:
                raise DeployError(
                    f"generated metadata is stale: {generated_path.relative_to(ROOT)}; "
                    "run python3 scripts/suite_metadata.py sync"
                )
        dev_path = ROOT / ".valheim" / "dev.json"
        dev = load_json(dev_path)
        if dev.get("schemaVersion") != 1:
            raise DeployError(".valheim/dev.json schemaVersion must be 1")
        if dev.get("developmentOnly") is not True:
            raise DeployError(".valheim/dev.json must set developmentOnly=true before deployment")
        raw_dest = args.destination
        if not raw_dest:
            key = "clientPluginDir" if args.target == "client" else "serverPluginDir"
            raw_dest = dev.get(key)
        if not isinstance(raw_dest, str) or not raw_dest.strip():
            raise DeployError("no deployment destination supplied and no matching destination configured in .valheim/dev.json")
        destination = safe_destination(raw_dest)
        projects = cfg["projects"]
        modules = modules_for(cfg, args.target)
        artifacts = [(module, artifact_for(module, projects[module]["targetFramework"], args.configuration)) for module in modules]

        print(f"target: {args.target}")
        print(f"destination: {destination}")
        for module, source in artifacts:
            print(f"  {module}: {source.relative_to(ROOT)}")
        if args.dry_run:
            return 0
        destination.mkdir(parents=True, exist_ok=True)
        dir_fd = open_deployment_dir(destination)
        try:
            desired_names = {source.name for _module, source in artifacts}
            prefix = f"{cfg['rootNamespace']}.".lower()
            removed: list[str] = []
            for name in os.listdir(dir_fd):
                if name.endswith(".dll") and name.lower().startswith(prefix) and name not in desired_names:
                    os.unlink(name, dir_fd=dir_fd)
                    removed.append(name)
            for _module, source in artifacts:
                deploy_dll(source, dir_fd, source.name)
            if removed:
                print("removed stale suite DLLs: " + ", ".join(sorted(removed)))
            print(f"deployed {len(artifacts)} DLL(s)")
        finally:
            os.close(dir_fd)
        return 0
    except DeployError as exc:
        print(f"deploy error: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
