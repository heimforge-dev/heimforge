#!/usr/bin/env python3
"""Inspect and deliberately maintain the local Valheim modding stack."""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import preflight
import suite_metadata

ROOT = Path(__file__).resolve().parents[1]
STEAM_APP_MANIFEST = "appmanifest_892970.acf"
JOTUNN_MANIFEST_NAMES = frozenset({"Jotunn"})
BEPINEX_MANIFEST_NAMES = frozenset({"BepInExPack_Valheim", "BepInExPack Valheim"})
JOTUNN_PROFILE_NAMES = frozenset({"ValheimModding-Jotunn"})
BEPINEX_PROFILE_NAMES = frozenset({"denikson-BepInExPack_Valheim"})
STEAM_BUILD_ID = re.compile(r'"buildid"\s+"(?P<value>\d+)"')
FOUND = "found"
NOT_FOUND = "not_found"
AMBIGUOUS_OR_INVALID = "ambiguous_or_invalid"


class StackError(RuntimeError):
    pass


@dataclass(frozen=True)
class Discovery:
    status: str
    version: str | None = None


@dataclass(frozen=True)
class RuntimeState:
    valheim: str
    jotunn: str
    bepinex: str
    publicized: bool | None
    environment_error: str | None = None



def run_command(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def package_version(manifest: Path, names: frozenset[str]) -> Discovery:
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except OSError:
        return Discovery(NOT_FOUND)
    except json.JSONDecodeError:
        return Discovery(AMBIGUOUS_OR_INVALID if manifest.parent.name in names else NOT_FOUND)
    if not isinstance(payload, dict) or payload.get("name") not in names:
        return Discovery(NOT_FOUND)
    version = payload.get("version_number")
    if not isinstance(version, str):
        return Discovery(AMBIGUOUS_OR_INVALID)
    try:
        suite_metadata.validate_semver(version, "installed version")
    except suite_metadata.MetadataError:
        return Discovery(AMBIGUOUS_OR_INVALID)
    return Discovery(FOUND, version)


def discover_package_version(root: Path, names: frozenset[str]) -> Discovery:
    if not root.is_dir():
        return Discovery(NOT_FOUND)
    versions: set[str] = set()
    invalid = False
    for manifest in root.rglob("manifest.json"):
        result = package_version(manifest, names)
        if result.status == FOUND:
            assert result.version is not None
            versions.add(result.version)
        elif result.status == AMBIGUOUS_OR_INVALID:
            invalid = True
    if invalid or len(versions) > 1:
        return Discovery(AMBIGUOUS_OR_INVALID)
    return Discovery(FOUND, next(iter(versions))) if versions else Discovery(NOT_FOUND)


def profile_package_version(profile_root: Path, names: frozenset[str]) -> Discovery:
    try:
        text = (profile_root / "mods.yml").read_text(encoding="utf-8-sig")
    except OSError:
        return Discovery(NOT_FOUND)
    records = re.split(r"(?m)^- manifestVersion:.*(?:\n|$)", text)
    versions: set[str] = set()
    invalid = False
    for record in records:
        name_match = re.search(r"(?m)^  name: (?P<value>[^\n]+)$", record)
        if not name_match or name_match.group("value") not in names:
            continue
        version_match = re.search(
            r"(?m)^  versionNumber:\n    major: (?P<major>\d+)\n    minor: (?P<minor>\d+)\n    patch: (?P<patch>\d+)$",
            record,
        )
        if not version_match:
            invalid = True
            continue
        version = "{major}.{minor}.{patch}".format(**version_match.groupdict())
        try:
            suite_metadata.validate_semver(version, "installed version")
        except suite_metadata.MetadataError:
            invalid = True
        else:
            versions.add(version)
    if invalid or len(versions) > 1:
        return Discovery(AMBIGUOUS_OR_INVALID)
    return Discovery(FOUND, next(iter(versions))) if versions else Discovery(NOT_FOUND)


def installed_valheim_version(install: Path) -> str:
    manifest = install.parent.parent / STEAM_APP_MANIFEST
    try:
        match = STEAM_BUILD_ID.search(manifest.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return "unknown"
    return f"Steam build ID {match.group('value')}" if match else "unknown"


def inspect_runtime() -> RuntimeState:
    try:
        environment = preflight.parse_environment_props(ROOT / "Environment.props")
        install = Path(environment["VALHEIM_INSTALL"])
        managed = Path(environment["VALHEIM_MANAGED"])
        bepinex_root = Path(environment["BEPINEX_PATH"])
    except (KeyError, preflight.PreflightError) as exc:
        return RuntimeState("unknown", "unknown", "unknown", None, str(exc))

    profile_root = bepinex_root.parent
    jotunn_result = discover_package_version(bepinex_root / "plugins", JOTUNN_MANIFEST_NAMES)
    if jotunn_result.status == NOT_FOUND:
        jotunn_result = profile_package_version(profile_root, JOTUNN_PROFILE_NAMES)
    bepinex_result = discover_package_version(profile_root, BEPINEX_MANIFEST_NAMES)
    if bepinex_result.status == NOT_FOUND:
        bepinex_result = profile_package_version(profile_root, BEPINEX_PROFILE_NAMES)
    jotunn = jotunn_result.version if jotunn_result.status == FOUND else "unknown"
    bepinex = bepinex_result.version if bepinex_result.status == FOUND else "unknown"
    publicized = (managed / "publicized_assemblies" / "assembly_valheim_publicized.dll").is_file()
    return RuntimeState(installed_valheim_version(install), jotunn, bepinex, publicized)


def drift_status(pinned: str, installed: str) -> str:
    if installed == "unknown":
        return "unknown"
    return "matching" if pinned == installed else "drift"


def print_report(cfg: dict, runtime: RuntimeState) -> None:
    jotunn_pin = cfg["jotunnVersion"]
    bepinex_pin = cfg["bepInExPackVersion"]
    print("Valheim")
    print(f"  installed version: {runtime.valheim}")
    print("Jötunn")
    print(f"  pinned version: {jotunn_pin}")
    print(f"  installed development-profile version: {runtime.jotunn}")
    print(f"  drift status: {drift_status(jotunn_pin, runtime.jotunn)}")
    print("BepInExPack Valheim")
    print(f"  pinned version: {bepinex_pin}")
    print(f"  installed development-profile version: {runtime.bepinex}")
    print(f"  drift status: {drift_status(bepinex_pin, runtime.bepinex)}")
    print("Publicized Valheim assemblies")
    print(f"  presence: {'present' if runtime.publicized else 'missing' if runtime.publicized is not None else 'unknown'}")
    print("  freshness: unknown")
    if runtime.publicized:
        print("  recommendation: refresh after a Valheim or Jötunn update")
    elif runtime.publicized is False:
        print("  recommendation: run python3 scripts/update-game-stack.py refresh")
    if runtime.environment_error:
        print(f"Runtime inspection unavailable: {runtime.environment_error}")


def require_valid_metadata() -> None:
    run_command([sys.executable, "scripts/suite_metadata.py", "check"])


def update_config(jotunn: str | None, bepinex: str | None) -> tuple[dict, bytes]:
    cfg = suite_metadata.load_config()
    original = suite_metadata.CONFIG_PATH.read_bytes()
    if jotunn is not None:
        cfg["jotunnVersion"] = jotunn
    if bepinex is not None:
        cfg["bepInExPackVersion"] = bepinex
    suite_metadata.atomic_write_text(suite_metadata.CONFIG_PATH, json.dumps(cfg, indent=2) + "\n")
    return cfg, original


def restore_config(original: bytes) -> None:
    suite_metadata.atomic_write_text(suite_metadata.CONFIG_PATH, original.decode("utf-8"))


def deployment_steps(cfg: dict, configuration: str) -> list[str]:
    packages = cfg["packages"]
    steps = []
    if packages["requiredClientModules"] or packages["optionalClientModules"] or packages["clientOnlyModules"]:
        steps.append(f"  ./scripts/deploy-client.sh {configuration}")
    if packages["serverModules"]:
        steps.append(f"  ./scripts/deploy-server.sh {configuration} --restart")
    return steps


def _run_project_maintenance(
    cfg: dict,
    configuration: str,
    *,
    pins_changed: bool,
    refresh_references: bool,
) -> int:
    if refresh_references:
        try:
            run_command(["bash", "scripts/refresh-references.sh", configuration])
        except subprocess.CalledProcessError as exc:
            raise StackError(f"reference refresh failed: {exc}") from exc
    try:
        run_command(["bash", "scripts/build.sh", configuration])
    except subprocess.CalledProcessError as exc:
        raise StackError(f"normal build failed: {exc}") from exc
    try:
        run_command([sys.executable, "scripts/preflight.py"])
    except subprocess.CalledProcessError as exc:
        raise StackError(f"preflight failed: {exc}") from exc
    print("\nProject maintenance completed successfully.")
    print("Runtime alignment:")
    print_report(cfg, inspect_runtime())
    print("Remote/server runtime: not inspected")
    if pins_changed:
        print("\nDependency pin changes and generated metadata remain applied.")
    print("\nNext:")
    print("\n".join(deployment_steps(cfg, configuration)))
    print("\nThen perform the multiplayer smoke test.")
    return 0
def apply(args: argparse.Namespace) -> int:
    if args.jotunn is None and args.bepinex is None:
        raise StackError("apply requires --jotunn and/or --bepinex")
    for field, version in (("jotunnVersion", args.jotunn), ("bepInExPackVersion", args.bepinex)):
        if version is not None:
            suite_metadata.validate_semver(version, field)

    require_valid_metadata()
    cfg, original = update_config(args.jotunn, args.bepinex)
    try:
        run_command([sys.executable, "scripts/suite_metadata.py", "sync"])
    except (OSError, subprocess.CalledProcessError) as sync_exc:
        try:
            restore_config(original)
        except (OSError, suite_metadata.MetadataError) as restore_exc:
            raise StackError(
                "metadata synchronization failed and suite.config.json restoration also failed; "
                "project metadata may now be inconsistent/split: "
                f"synchronization failure: {sync_exc}; restoration failure: {restore_exc}"
            ) from restore_exc
        print("metadata synchronization failed; restored suite.config.json", file=sys.stderr)
        return 2

    print("Updated dependency pins:")
    if args.jotunn is not None:
        print(f"  Jötunn: {cfg['jotunnVersion']}")
    if args.bepinex is not None:
        print(f"  BepInExPack Valheim: {cfg['bepInExPackVersion']}")
    try:
        return _run_project_maintenance(
            cfg,
            args.configuration,
            pins_changed=True,
            refresh_references=args.jotunn is not None,
        )
    except StackError as exc:
        print(f"game stack maintenance error: {exc}", file=sys.stderr)
        print("Synchronized dependency pins and generated metadata remain applied.", file=sys.stderr)
        return 2


def refresh(args: argparse.Namespace) -> int:
    require_valid_metadata()
    cfg = suite_metadata.load_config()
    return _run_project_maintenance(
        cfg,
        args.configuration,
        pins_changed=False,
        refresh_references=True,
    )

def check() -> int:
    cfg = suite_metadata.load_config()
    suite_metadata.check(cfg, structural_only=True)
    print_report(cfg, inspect_runtime())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("check", help="Report local runtime versions and pin drift without changing files")
    refresh_parser = subcommands.add_parser("refresh", help="Refresh Valheim references, build, and preflight without changing pins")
    refresh_parser.add_argument("--configuration", choices=("Debug", "Release"), default="Debug")
    apply_parser = subcommands.add_parser("apply", help="Set explicitly requested pins, refresh references, build, and preflight")
    apply_parser.add_argument("--jotunn", help="Explicit Jötunn SemVer pin")
    apply_parser.add_argument("--bepinex", help="Explicit BepInExPack Valheim SemVer pin")
    apply_parser.add_argument("--configuration", choices=("Debug", "Release"), default="Debug")
    args = parser.parse_args()
    try:
        if args.command == "check":
            return check()
        if args.command == "refresh":
            return refresh(args)
        return apply(args)
    except (StackError, suite_metadata.MetadataError, subprocess.CalledProcessError) as exc:
        print(f"game stack maintenance error: {exc}", file=sys.stderr)
        if args.command == "refresh":
            print("Project metadata and dependency pins were not changed.", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
