#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from dev_config import ConfigError, ServerDeployment, load_development_config
from remote_deploy import RemoteDeployError, deploy_ssh

import suite_metadata as metadata

ROOT = Path(__file__).resolve().parents[1]

class DeployError(RuntimeError):
    pass


MANIFEST_VERSION = 1

class LifecycleError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeploymentPlan:
    artifacts: tuple[tuple[str, Path], ...]
    manifest_filename: str
    manifest_payload: bytes


def safe_destination(raw: str) -> Path:
    dest = Path(raw).expanduser()
    if not dest.is_absolute():
        raise DeployError(f"deployment destination must be absolute: {dest}")
    resolved = dest.resolve(strict=False)
    if resolved == Path("/") or resolved == Path.home().resolve():
        raise DeployError(f"refusing unsafe deployment destination: {resolved}")
    if resolved.name.lower() == "plugins" and resolved.parent.name.lower() == "bepinex":
        raise DeployError(
            f"refusing to deploy directly into the shared BepInEx/plugins directory: {resolved}; "
            "configure a suite-specific subdirectory instead, e.g. BepInEx/plugins/<SuiteName>"
        )
    return resolved


def _same_destination(a: Path, b: Path) -> bool:
    """Whether `a` and `b` name the same effective directory. Resolved-path
    equality already folds in `..`/symlink normalization for every existing
    leading component (`safe_destination` always runs `resolve(strict=False)`
    first); the `os.stat` identity check on top of that also catches
    equivalent paths `resolve()` cannot fold, such as bind mounts, once both
    sides actually exist."""
    if a == b:
        return True
    try:
        return os.path.samestat(os.stat(a), os.stat(b))
    except OSError:
        return False


def artifact_for(project: str, tfm: str, configuration: str) -> Path:
    exact = ROOT / "src" / project / "bin" / configuration / tfm / f"{project}.dll"
    if exact.is_file():
        return exact
    raise DeployError(f"missing build artifact for {project} ({configuration}/{tfm}); run ./scripts/build.sh {configuration}")


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


def side_has_runtime_module(cfg: dict, target: str) -> bool:
    """Whether at least one non-`common` project actually targets `target`,
    derived from the same validated `packages` groups `modules_for()`
    reads -- current metadata, not bootstrap-time module identity, so this
    stays correct after a supported post-generation structural edit
    (custom `serverOnly`/`clientOnly`/`sharedRequired`/`sharedOptional`
    project added or removed). Common alone never satisfies this: it is a
    shared library other plugins reference, not itself a runtime plugin."""
    packages = cfg["packages"]
    if target == "server":
        return bool(packages["serverModules"])
    return bool(packages["requiredClientModules"] or packages["optionalClientModules"] or packages["clientOnlyModules"])


def open_deployment_dir(destination: Path) -> int:
    """Open the validated deployment directory once, without following a
    symlinked final path component, for every stale-cleanup and DLL write
    below to share -- never re-resolved by pathname per file."""
    try:
        return os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise DeployError(f"cannot open deployment directory {destination}: {exc}") from exc


def _check_replaceable(dir_fd: int, name: str, *, what: str) -> None:
    """Refuse to replace whatever currently occupies `name` unless it is
    absent, a regular file, or a symlink -- a directory or other
    non-regular object is never silently destroyed."""
    try:
        existing = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DeployError(f"cannot inspect {what} {name}: {exc}") from exc
    if not stat.S_ISLNK(existing.st_mode) and not stat.S_ISREG(existing.st_mode):
        raise DeployError(f"refusing to replace non-regular {what}: {name}")


def _atomic_replace(dir_fd: int, name: str, write) -> None:
    """Stage `write(file_object)` into a fresh temporary regular file inside
    the directory referenced by `dir_fd`, then atomically rename it onto
    `name`. Whatever currently occupies `name` -- including a symlink -- is
    never opened for writing, so it is replaced as a directory entry
    instead of followed."""
    temp_name = None
    temp_fd = None
    for _ in range(16):
        candidate = f".deploy-tmp-{uuid.uuid4().hex}"
        try:
            temp_fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=dir_fd)
            temp_name = candidate
            break
        except FileExistsError:
            continue
    if temp_fd is None:
        raise DeployError(f"cannot allocate a temporary file for {name}")

    promoted = False
    try:
        try:
            with os.fdopen(temp_fd, "wb") as dst:
                write(dst)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(temp_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
            promoted = True
        except OSError as exc:
            raise DeployError(f"cannot write {name}: {exc}") from exc
    finally:
        if not promoted:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except OSError:
                pass


def deploy_dll(source: Path, dir_fd: int, name: str) -> None:
    """Copy `source` into the directory referenced by `dir_fd` as `name`
    via `_atomic_replace`, so an existing directory entry -- including a
    symlink -- is replaced instead of followed."""
    _check_replaceable(dir_fd, name, what="deployment target")

    def _write(dst) -> None:
        with open(source, "rb") as src:
            source_stat = os.fstat(src.fileno())
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fchmod(dst.fileno(), stat.S_IMODE(source_stat.st_mode))
            os.utime(dst.fileno(), ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))

    _atomic_replace(dir_fd, name, _write)


def manifest_name(cfg: dict) -> str:
    """The suite-specific deployment manifest filename: a hidden dotfile
    that cannot be mistaken for a deployed DLL, scoped to this suite so it
    never collides with another suite's manifest in a shared directory."""
    return f".{cfg['suiteName']}.deploy-manifest.json"


def _validated_manifest_files(payload: object, *, manifest: str) -> list[str]:
    if not isinstance(payload, dict):
        raise DeployError(f"deployment manifest {manifest} must contain a JSON object")
    version = payload.get("version")
    if type(version) is not int or version != MANIFEST_VERSION:
        raise DeployError(f"deployment manifest {manifest} has an unsupported or missing version: {version!r}")
    files = payload.get("files")
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise DeployError(f"deployment manifest {manifest}: 'files' must be a list of strings")
    if len(set(files)) != len(files):
        raise DeployError(f"deployment manifest {manifest} contains duplicate entries")
    for item in files:
        try:
            metadata.validate_path_component(item, "deployment manifest entry")
        except metadata.MetadataError as exc:
            raise DeployError(f"deployment manifest {manifest} contains an unsafe filename: {exc}") from exc
    return files


def load_manifest(dir_fd: int, name: str) -> set[str]:
    """Load the set of filenames this suite deployed to this destination on
    the previous successful deployment, from the directory referenced by
    `dir_fd`, without following a symlinked manifest path. Returns the
    empty set only when no manifest entry exists at all -- the first
    deployment to a destination has no ownership history. A manifest entry
    that exists but is a symlink, a non-regular object, or malformed JSON
    fails the deployment instead of being treated as absent, since silently
    discarding unreadable ownership history could broaden cleanup to files
    this suite never recorded as its own."""
    try:
        state = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return set()
    except OSError as exc:
        raise DeployError(f"cannot inspect deployment manifest {name}: {exc}") from exc
    if not stat.S_ISREG(state.st_mode):
        raise DeployError(f"deployment manifest {name} must be a regular file, not a symlink or other object")
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as exc:
        raise DeployError(f"cannot open deployment manifest {name}: {exc}") from exc
    try:
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise DeployError(f"cannot read deployment manifest {name}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DeployError(f"deployment manifest {name} is not valid JSON: {exc}") from exc
    return set(_validated_manifest_files(payload, manifest=name))


def write_manifest(dir_fd: int, name: str, files: set[str]) -> None:
    """Atomically (re)write the deployment manifest to record exactly the
    filenames just successfully deployed, via the same no-follow
    temporary-file-then-rename pattern as `deploy_dll`, then fsync the
    containing directory so the rename is durably committed. A file fsync
    alone (already done inside `_atomic_replace`) does not guarantee
    durability of the directory-entry replacement -- the caller must not
    begin stale cleanup until this returns successfully."""
    payload = (json.dumps({"version": MANIFEST_VERSION, "files": sorted(files)}, indent=2) + "\n").encode("utf-8")
    _check_replaceable(dir_fd, name, what="deployment manifest")
    _atomic_replace(dir_fd, name, lambda dst: dst.write(payload))
    try:
        os.fsync(dir_fd)
    except OSError as exc:
        raise DeployError(f"cannot durably commit deployment manifest {name}: {exc}") from exc


def remove_stale_entry(dir_fd: int, name: str) -> bool:
    """Remove exactly the directory entry `name` -- previously recorded as
    this suite's own deployed output but no longer desired -- from the
    directory referenced by `dir_fd`. Never follows the entry: a symlink is
    unlinked as a directory entry without touching its target, a directory
    or other unexpected non-regular object fails safely instead of being
    recursively destroyed. Return whether an entry was actually unlinked."""
    try:
        entry = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise DeployError(f"cannot inspect stale deployment entry {name}: {exc}") from exc
    if not stat.S_ISREG(entry.st_mode) and not stat.S_ISLNK(entry.st_mode):
        raise DeployError(f"refusing to remove non-regular stale deployment entry: {name}")
    try:
        os.unlink(name, dir_fd=dir_fd)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise DeployError(f"cannot remove stale deployment entry {name}: {exc}") from exc
    return True

def build_deployment_plan(cfg: dict, target: str, configuration: str) -> DeploymentPlan:
    projects = cfg["projects"]
    artifacts = tuple(
        (module, artifact_for(module, projects[module]["targetFramework"], configuration))
        for module in modules_for(cfg, target)
    )
    desired_names = {source.name for _module, source in artifacts}
    payload = (json.dumps({"version": MANIFEST_VERSION, "files": sorted(desired_names)}, indent=2) + "\n").encode(
        "utf-8"
    )
    return DeploymentPlan(
        artifacts=artifacts,
        manifest_filename=manifest_name(cfg),
        manifest_payload=payload,
    )


def deploy_local(plan: DeploymentPlan, destination: Path) -> set[str]:
    destination.mkdir(parents=True, exist_ok=True)
    dir_fd = open_deployment_dir(destination)
    try:
        try:
            fcntl.flock(dir_fd, fcntl.LOCK_EX)
        except OSError as exc:
            raise DeployError(f"cannot acquire deployment lock on {destination}: {exc}") from exc
        try:
            desired_names = {source.name for _module, source in plan.artifacts}
            previously_owned = load_manifest(dir_fd, plan.manifest_filename)
            for _module, source in plan.artifacts:
                deploy_dll(source, dir_fd, source.name)
            stale = previously_owned - desired_names
            write_manifest(dir_fd, plan.manifest_filename, desired_names)
            removed = False
            removal_error = None
            try:
                for name in sorted(stale):
                    if remove_stale_entry(dir_fd, name):
                        removed = True
            except DeployError as exc:
                removal_error = exc
                raise
            finally:
                if removed:
                    try:
                        os.fsync(dir_fd)
                    except OSError as exc:
                        detail = f"cannot durably commit stale deployment removals: {exc}"
                        if removal_error is not None:
                            raise DeployError(f"{removal_error}; additionally, {detail}") from removal_error
                        raise DeployError(detail) from exc
        finally:
            fcntl.flock(dir_fd, fcntl.LOCK_UN)
        return stale
    finally:
        os.close(dir_fd)


def restart_local_docker(container: str) -> str:
    try:
        result = subprocess.run(
            ["docker", "restart", container],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise LifecycleError(f"cannot execute docker: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise LifecycleError(f"docker restart failed: {detail}")
    return result.stdout.strip()


def _configured_local_destination(development, target: str, override: str | None) -> tuple[ServerDeployment, Path]:
    if target == "client":
        raw = override or development.raw.get("clientPluginDir")
        deployment = ServerDeployment(type="local", plugin_dir=raw if isinstance(raw, str) else None)
    elif override:
        deployment = ServerDeployment(type="local", plugin_dir=override)
    else:
        deployment = development.server_deployment
    if deployment.type != "local":
        raise DeployError("internal error: requested a local destination for a non-local deployment")
    if not isinstance(deployment.plugin_dir, str) or not deployment.plugin_dir.strip():
        raise DeployError("no deployment destination supplied and no matching destination configured in .valheim/dev.json")
    return deployment, safe_destination(deployment.plugin_dir)


def _check_other_local_destination(development, target: str, destination: Path) -> None:
    if target == "client":
        if development.server_deployment.type != "local":
            return
        other_key = "server deployment"
        other_raw = development.server_deployment.plugin_dir
    else:
        other_key = "clientPluginDir"
        other_raw = development.raw.get(other_key)
    if isinstance(other_raw, str) and other_raw.strip():
        other_destination = safe_destination(other_raw)
        if _same_destination(destination, other_destination):
            raise DeployError(
                f"{target} destination {destination} must not resolve to the same directory as "
                f"the other role's configured {other_key} ({other_destination}); use separate "
                "client/server suite directories"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("client", "server"), required=True)
    parser.add_argument("--configuration", choices=("Debug", "Release"), default="Debug")
    parser.add_argument("--destination")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restart", action="store_true", help="Restart the configured server lifecycle after deployment")
    args = parser.parse_args()

    remote_host = None
    deployment = None
    development = None
    try:
        if args.restart and args.target != "server":
            raise DeployError("--restart is only valid for server deployment")
        cfg = metadata.load_config()
        metadata.validate(cfg)
        metadata.validate_identity(cfg)
        metadata.validate_solution_membership(cfg)
        for generated_path, expected in metadata.expected_files(cfg).items():
            if not generated_path.exists() or generated_path.read_text(encoding="utf-8") != expected:
                raise DeployError(
                    f"generated metadata is stale: {generated_path.relative_to(ROOT)}; "
                    "run python3 scripts/suite_metadata.py sync"
                )
        if not side_has_runtime_module(cfg, args.target):
            raise DeployError(
                f"no runtime module targets the {args.target} side; Common alone is a shared library, "
                "not a runtime BepInEx plugin, and deploying only Common would create an ownership "
                f"manifest for a {args.target} side with nothing to load"
            )
        try:
            development = load_development_config(ROOT / ".valheim" / "dev.json")
        except ConfigError as exc:
            raise DeployError(f".valheim/dev.json: {exc}") from exc

        if args.target == "client" or args.destination:
            deployment, destination = _configured_local_destination(
                development, args.target, args.destination
            )
            _check_other_local_destination(development, args.target, destination)
            destination_display = str(destination)
        else:
            deployment = development.server_deployment
            if not isinstance(deployment.plugin_dir, str) or not deployment.plugin_dir.strip():
                raise DeployError("no server deployment destination configured in .valheim/dev.json")
            destination = None
            destination_display = (
                str(safe_destination(deployment.plugin_dir))
                if deployment.type == "local"
                else f"ssh://{deployment.host}/{deployment.plugin_dir}"
            )

        plan = build_deployment_plan(cfg, args.target, args.configuration)
        print(f"target: {args.target}")
        print(f"destination: {destination_display}")
        for module, source in plan.artifacts:
            print(f"  {module}: {source.relative_to(ROOT)}")
        if args.dry_run:
            return 0

        if deployment.type == "local":
            if destination is None:
                destination = safe_destination(deployment.plugin_dir or "")
                _check_other_local_destination(development, args.target, destination)
            stale = deploy_local(plan, destination)
        elif deployment.type == "ssh":
            remote_host, platform, stale = deploy_ssh(
                deployment,
                [source for _module, source in plan.artifacts],
                plan.manifest_filename,
                plan.manifest_payload,
            )
            print(f"remote platform: {platform}")
        else:
            raise DeployError(f"unsupported deployment type: {deployment.type}")

        if stale:
            print("removed stale suite DLLs: " + ", ".join(sorted(stale)))
        print(f"deployed {len(plan.artifacts)} DLL(s)")
    except (DeployError, ConfigError, RemoteDeployError, metadata.MetadataError) as exc:
        print(f"deploy error: {exc}", file=sys.stderr)
        return 2

    if args.restart:
        try:
            lifecycle = development.server_lifecycle
            if lifecycle.type == "none":
                raise LifecycleError("server lifecycle type is none; configure docker to use --restart")
            if lifecycle.type != "docker" or lifecycle.container is None:
                raise LifecycleError(f"unsupported server lifecycle type: {lifecycle.type}")
            output = (
                restart_local_docker(lifecycle.container)
                if deployment.type == "local"
                else remote_host.restart_docker(lifecycle.container)
            )
            print(f"restarted Docker container: {lifecycle.container}")
            if output:
                print(output)
        except (LifecycleError, RemoteDeployError) as exc:
            print(f"lifecycle error (deployment succeeded): {exc}", file=sys.stderr)
            return 3
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
