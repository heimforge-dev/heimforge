#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from dev_config import ConfigError, parse_development_config

ROOT = Path(__file__).resolve().parents[1]

ENVIRONMENT_PROPERTIES = frozenset({"VALHEIM_INSTALL", "VALHEIM_MANAGED", "BEPINEX_PATH", "MOD_DEPLOYPATH"})
PROPERTY_REFERENCE = re.compile(r"\$\(([^()]*)\)")
GAME_ASSEMBLY_NAMES = ("assembly_valheim.dll", "Assembly-CSharp.dll")


class PreflightError(RuntimeError):
    pass


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check)


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PreflightError(f"missing {path.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise PreflightError(f"invalid JSON in {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(data, dict):
        raise PreflightError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return data


def parse_environment_props(path: Path) -> dict[str, str]:
    if not path.exists():
        raise PreflightError("missing Environment.props; copy Environment.props.example and configure your local Valheim path")
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise PreflightError(f"invalid XML in Environment.props: {exc}") from exc
    values: dict[str, str] = {}
    for element in tree.iter():
        tag = element.tag.split("}")[-1]
        if tag in ENVIRONMENT_PROPERTIES and element.text:
            values[tag] = element.text.strip()

    def expand(name: str, chain: tuple[str, ...]) -> str:
        if name in chain:
            raise PreflightError(
                f"cyclic Environment.props property reference: {' -> '.join((*chain, name))}"
            )
        value = values.get(name)
        if value is None:
            raise PreflightError(f"unresolved Environment.props property reference: $({name})")

        def replace(match: re.Match[str]) -> str:
            reference = match.group(1)
            if not reference:
                raise PreflightError(f"invalid Environment.props property reference in {name}")
            if reference not in ENVIRONMENT_PROPERTIES:
                raise PreflightError(f"unknown Environment.props property reference: $({reference})")
            return expand(reference, (*chain, name))

        expanded = PROPERTY_REFERENCE.sub(replace, value)
        if "$(" in expanded:
            raise PreflightError(f"invalid Environment.props property reference in {name}: {value}")
        return expanded

    return {name: expand(name, ()) for name in values}


def find_jotunn(plugin_root: Path) -> Path | None:
    if not plugin_root.exists():
        return None
    for path in sorted(plugin_root.rglob("Jotunn.dll")):
        if path.is_file():
            return path
    return None

def resolve_game_assembly(managed: Path) -> Path:
    for filename in GAME_ASSEMBLY_NAMES:
        assembly = managed / filename
        if assembly.is_file():
            return assembly
    raise PreflightError(
        f"Valheim gameplay assembly not found in {managed}; expected {' or '.join(GAME_ASSEMBLY_NAMES)}"
    )


def require_abs_wsl_path(value: object, key: str, *, nullable: bool = False) -> Path | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PreflightError(f".valheim/dev.json {key} must be a non-empty string")
    p = Path(value).expanduser()
    if not p.is_absolute():
        raise PreflightError(f".valheim/dev.json {key} must be an absolute WSL/Linux path: {value}")
    return p


def validate_dev_config(path: Path) -> tuple[dict, list[str]]:
    cfg = load_json(path)
    warnings: list[str] = []
    try:
        development = parse_development_config(cfg)
    except ConfigError as exc:
        raise PreflightError(f".valheim/dev.json: {exc}") from exc
    install = require_abs_wsl_path(cfg.get("valheimInstall"), "valheimInstall")
    client = require_abs_wsl_path(cfg.get("clientPluginDir"), "clientPluginDir")
    if development.server_deployment.type == "local":
        server = require_abs_wsl_path(
            development.server_deployment.plugin_dir,
            "serverPluginDir" if cfg["schemaVersion"] == 1 else "server.deployment.pluginDir",
        )
    else:
        server = None
    compose = require_abs_wsl_path(cfg.get("dockerComposeFile"), "dockerComposeFile", nullable=True)
    log_file = require_abs_wsl_path(cfg.get("serverLogFile"), "serverLogFile", nullable=True)
    solution = cfg.get("solution")
    if not isinstance(solution, str) or not solution.strip():
        raise PreflightError(".valheim/dev.json solution must be a non-empty string")
    if not (ROOT / solution).exists():
        raise PreflightError(f"configured solution does not exist: {solution}")
    if install is not None and not str(install).startswith("/mnt/"):
        warnings.append(f"valheimInstall is not under /mnt/*: {install}; this is valid only if Valheim is actually available there")
    if client is not None and "BepInEx/plugins" not in str(client).replace("\\", "/"):
        warnings.append(f"clientPluginDir does not contain BepInEx/plugins: {client}")
    if compose is not None and not compose.exists():
        warnings.append(f"dockerComposeFile does not exist yet: {compose}")
    if log_file is not None and not log_file.exists():
        warnings.append(f"serverLogFile does not exist yet: {log_file}")
    if server is not None and str(server) in {"/", str(Path.home())}:
        raise PreflightError(f"unsafe server deployment directory: {server}")
    return cfg, warnings


def main() -> int:
    bootstrap_validation = os.environ.pop("SUITE_BOOTSTRAP_VALIDATION", None) == "1"
    parser = argparse.ArgumentParser()
    parser.add_argument("--portable", action="store_true", help="Skip machine-specific Valheim/server checks")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    checks: dict[str, object] = {}
    warnings: list[str] = []
    try:
        if bootstrap_validation:
            checks["metadata"] = "already certified by bootstrap validation"
        else:
            meta = run([sys.executable, "scripts/suite_metadata.py", "check"])
            checks["metadata"] = meta.stdout.strip()

        cwd = str(ROOT.resolve())
        checks["repoPath"] = cwd
        if cwd.startswith(("/mnt/c/", "/mnt/d/", "/mnt/e/")):
            warnings.append("repository is on a Windows-mounted filesystem; prefer the WSL filesystem such as ~/src")

        checks["isWsl"] = bool(os.environ.get("WSL_DISTRO_NAME")) or "microsoft" in Path("/proc/version").read_text(errors="ignore").lower()
        if not checks["isWsl"]:
            warnings.append("canonical development environment is WSL/Linux; current environment does not appear to be WSL")

        for tool in ("python3", "bash"):
            location = shutil.which(tool)
            if not location:
                raise PreflightError(f"required tool not found: {tool}")
            checks[tool] = location

        dotnet = shutil.which("dotnet")
        if not dotnet:
            raise PreflightError("dotnet SDK is required; install it inside WSL")
        checks["dotnet"] = run([dotnet, "--version"]).stdout.strip()
        checks["ilspycmd"] = shutil.which("ilspycmd") or "not installed (optional until assembly inspection is needed)"

        if not args.portable:
            env = parse_environment_props(ROOT / "Environment.props")
            for key in ("VALHEIM_INSTALL", "VALHEIM_MANAGED", "BEPINEX_PATH"):
                if not env.get(key):
                    raise PreflightError(f"Environment.props {key} must be set to an actual WSL-visible path")
            env_install = Path(env["VALHEIM_INSTALL"]).expanduser()
            managed = Path(env["VALHEIM_MANAGED"]).expanduser()
            bepinex_root = Path(env["BEPINEX_PATH"]).expanduser()
            checks["environmentValheimInstall"] = str(env_install)

            dev, dev_warnings = validate_dev_config(ROOT / ".valheim" / "dev.json")
            warnings.extend(dev_warnings)
            dev_install = Path(str(dev["valheimInstall"])).expanduser()
            if env_install.resolve() != dev_install.resolve():
                raise PreflightError(
                    f"Valheim path mismatch: Environment.props={env_install} but .valheim/dev.json={dev_install}"
                )
            assembly = resolve_game_assembly(managed)
            bepinex = bepinex_root / "core" / "BepInEx.dll"
            jotunn = find_jotunn(bepinex_root / "plugins")
            checks["gameAssembly"] = str(assembly)
            checks["bepInEx"] = str(bepinex)
            checks["jotunn"] = str(jotunn)

            publicized_dir = managed / "publicized_assemblies"
            publicized_main = publicized_dir / "assembly_valheim_publicized.dll"
            checks["publicizedAssembliesPresent"] = publicized_main.is_file()
            try:
                prebuild_tree = ET.parse(ROOT / "DoPrebuild.props")
                prebuild_node = next((el for el in prebuild_tree.iter() if el.tag.split("}")[-1] == "ExecutePrebuild"), None)
                execute_prebuild = (prebuild_node.text or "").strip().lower() == "true" if prebuild_node is not None else False
            except ET.ParseError as exc:
                raise PreflightError(f"invalid XML in DoPrebuild.props: {exc}") from exc
            checks["jotunnExecutePrebuild"] = execute_prebuild
            if not publicized_main.is_file() and not execute_prebuild:
                warnings.append(
                    "publicized Valheim assemblies were not detected and Jotunn ExecutePrebuild=false; "
                    "after verifying VALHEIM_INSTALL, run python3 scripts/update-game-stack.py refresh "
                    "(or ./scripts/refresh-references.sh) before the first full plugin build"
                )

            development = parse_development_config(dev)
            if dev["schemaVersion"] == 1:
                compose = dev.get("dockerComposeFile")
                if compose:
                    docker = shutil.which("docker")
                    if not docker:
                        warnings.append("dockerComposeFile is configured but docker was not found in WSL")
                    else:
                        checks["docker"] = docker
            elif development.server_deployment.type == "ssh":
                for label, executable in (
                    ("ssh", development.server_deployment.ssh_executable),
                    ("scp", development.server_deployment.scp_executable),
                ):
                    location = shutil.which(executable)
                    if not location:
                        raise PreflightError(f"configured {label} executable was not found: {executable}")
                    checks[label] = location
                checks["serverDeployment"] = (
                    f"ssh:{development.server_deployment.host}:"
                    f"{development.server_deployment.remote_platform}"
                )
            elif development.server_lifecycle.type == "docker":
                docker = shutil.which("docker")
                if not docker:
                    warnings.append("Docker lifecycle is configured but docker was not found in WSL")
                else:
                    checks["docker"] = docker

        result = {"ok": True, "checks": checks, "warnings": warnings}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print("Preflight passed")
            for key, value in checks.items():
                print(f"  {key}: {value}")
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)
        return 0
    except (PreflightError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            message = exc.stdout.strip() or str(exc)
        else:
            message = str(exc)
        result = {"ok": False, "checks": checks, "warnings": warnings, "error": message}
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"preflight error: {message}", file=sys.stderr)
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
