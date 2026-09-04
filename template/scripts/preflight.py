#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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
        if tag in {"VALHEIM_INSTALL", "VALHEIM_MANAGED", "BEPINEX_PATH", "MOD_DEPLOYPATH"} and element.text:
            values[tag] = element.text.strip()
    return values


def find_jotunn(plugin_root: Path) -> Path | None:
    if not plugin_root.exists():
        return None
    for path in sorted(plugin_root.rglob("Jotunn.dll")):
        if path.is_file():
            return path
    return None


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
    if cfg.get("schemaVersion") != 1:
        raise PreflightError(".valheim/dev.json schemaVersion must be 1")
    if cfg.get("developmentOnly") is not True:
        raise PreflightError(".valheim/dev.json must set developmentOnly=true; deployment remains blocked otherwise")
    install = require_abs_wsl_path(cfg.get("valheimInstall"), "valheimInstall")
    client = require_abs_wsl_path(cfg.get("clientPluginDir"), "clientPluginDir")
    server = require_abs_wsl_path(cfg.get("serverPluginDir"), "serverPluginDir")
    compose = require_abs_wsl_path(cfg.get("dockerComposeFile"), "dockerComposeFile", nullable=True)
    log_file = require_abs_wsl_path(cfg.get("serverLogFile"), "serverLogFile", nullable=True)
    solution = cfg.get("solution")
    if not isinstance(solution, str) or not solution.strip():
        raise PreflightError(".valheim/dev.json solution must be a non-empty string")
    if not (ROOT / solution).exists():
        raise PreflightError(f"configured solution does not exist: {solution}")
    if cfg.get("configuration", "Debug") not in {"Debug", "Release"}:
        raise PreflightError(".valheim/dev.json configuration must be Debug or Release")
    if install is not None and not str(install).startswith("/mnt/"):
        warnings.append(f"valheimInstall is not under /mnt/*: {install}; this is valid only if Valheim is actually available there")
    if client is not None and "BepInEx/plugins" not in str(client).replace("\\", "/"):
        warnings.append(f"clientPluginDir does not contain BepInEx/plugins: {client}")
    if compose is not None and not compose.exists():
        warnings.append(f"dockerComposeFile does not exist yet: {compose}")
    if log_file is not None and not log_file.exists():
        warnings.append(f"serverLogFile does not exist yet: {log_file}")
    if server is not None and str(server) in {"/", str(Path.home())}:
        raise PreflightError(f"unsafe serverPluginDir: {server}")
    return cfg, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--portable", action="store_true", help="Skip machine-specific Valheim/server checks")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    checks: dict[str, object] = {}
    warnings: list[str] = []
    try:
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
            raw_install = env.get("VALHEIM_INSTALL")
            if not raw_install or "$" in raw_install:
                raise PreflightError("Environment.props VALHEIM_INSTALL must be set to the actual WSL-visible Valheim path")
            env_install = Path(raw_install).expanduser()
            checks["environmentValheimInstall"] = str(env_install)

            dev, dev_warnings = validate_dev_config(ROOT / ".valheim" / "dev.json")
            warnings.extend(dev_warnings)
            dev_install = Path(str(dev["valheimInstall"])).expanduser()
            if env_install.resolve() != dev_install.resolve():
                raise PreflightError(
                    f"Valheim path mismatch: Environment.props={env_install} but .valheim/dev.json={dev_install}"
                )
            managed = dev_install / "valheim_Data" / "Managed"
            assembly = managed / "Assembly-CSharp.dll"
            bepinex = dev_install / "BepInEx" / "core" / "BepInEx.dll"
            jotunn = find_jotunn(dev_install / "BepInEx" / "plugins")
            if not assembly.is_file():
                raise PreflightError(f"Assembly-CSharp.dll not found: {assembly}")
            if not bepinex.is_file():
                raise PreflightError(f"BepInEx.dll not found: {bepinex}; install the pinned BepInExPack in the development client")
            if jotunn is None:
                raise PreflightError(f"Jotunn.dll not found recursively under {dev_install / 'BepInEx' / 'plugins'}")
            checks["assemblyCSharp"] = str(assembly)
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
                    "the first full plugin build may fail until you deliberately enable Jotunn prebuild or generate references manually"
                )

            compose = dev.get("dockerComposeFile")
            if compose:
                docker = shutil.which("docker")
                if not docker:
                    warnings.append("dockerComposeFile is configured but docker was not found in WSL")
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
