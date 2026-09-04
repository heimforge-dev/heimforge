#!/usr/bin/env python3
"""Validate and synchronize generated project metadata from suite.config.json."""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "suite.config.json"
GENERATED_PROPS = ROOT / "build" / "Suite.Generated.props"
GENERATED_CS = ROOT / "src" / "ValheimSuite.Common" / "SuiteConstants.Generated.cs"
PROFILE_LOCK = ROOT / "packaging" / "profile-lock.json"

SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
GUID_ROOT = re.compile(r"^[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)+$")
VALID_SCOPES = {"common", "serverOnly", "clientOnly", "sharedOptional", "sharedRequired"}


class MetadataError(RuntimeError):
    pass


def load_config() -> dict:
    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8")
        cfg = json.loads(raw)
    except FileNotFoundError as exc:
        raise MetadataError(f"Missing {CONFIG_PATH.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise MetadataError(f"Invalid JSON in {CONFIG_PATH.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(cfg, dict):
        raise MetadataError("suite.config.json must contain a JSON object")
    return cfg


def require_string(cfg: dict, key: str) -> str:
    value = cfg.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MetadataError(f"{key} must be a non-empty string")
    return value.strip()


def validate(cfg: dict, release: bool = False) -> None:
    if cfg.get("schemaVersion") != 1:
        raise MetadataError("schemaVersion must currently be 1")

    suite_name = require_string(cfg, "suiteName")
    require_string(cfg, "rootNamespace")
    guid_root = require_string(cfg, "pluginGuidRoot")
    author = require_string(cfg, "author")
    thunderstore_namespace = require_string(cfg, "thunderstoreNamespace")
    suite_version = require_string(cfg, "suiteVersion")
    require_string(cfg, "csharpLanguageVersion")
    jotunn_version = require_string(cfg, "jotunnVersion")
    bepinex_version = require_string(cfg, "bepInExPackVersion")
    reference_version = require_string(cfg, "netFrameworkReferenceAssembliesVersion")

    if not SEMVER.match(suite_version):
        raise MetadataError(f"suiteVersion is not valid semantic-version syntax: {suite_version}")
    for key, value in (("jotunnVersion", jotunn_version), ("bepInExPackVersion", bepinex_version), ("netFrameworkReferenceAssembliesVersion", reference_version)):
        if not SEMVER.match(value):
            raise MetadataError(f"{key} is not valid version syntax: {value}")
    if not GUID_ROOT.match(guid_root):
        raise MetadataError(f"pluginGuidRoot has invalid syntax: {guid_root}")

    projects = cfg.get("projects")
    if not isinstance(projects, dict) or not projects:
        raise MetadataError("projects must be a non-empty object")
    for project, item in projects.items():
        if not isinstance(project, str) or not project:
            raise MetadataError("project names must be non-empty strings")
        if not isinstance(item, dict):
            raise MetadataError(f"projects.{project} must be an object")
        scope = item.get("scope")
        tfm = item.get("targetFramework")
        if scope not in VALID_SCOPES:
            raise MetadataError(f"projects.{project}.scope must be one of {sorted(VALID_SCOPES)}")
        if not isinstance(tfm, str) or not tfm:
            raise MetadataError(f"projects.{project}.targetFramework must be a non-empty string")

    packages = cfg.get("packages")
    if not isinstance(packages, dict):
        raise MetadataError("packages must be an object")
    common = packages.get("commonModule")
    if common not in projects or projects[common]["scope"] != "common":
        raise MetadataError("packages.commonModule must identify the project with scope=common")

    groups = {
        "serverModules": {"serverOnly", "sharedOptional", "sharedRequired"},
        "requiredClientModules": {"sharedRequired"},
        "optionalClientModules": {"sharedOptional"},
        "clientOnlyModules": {"clientOnly"},
    }
    seen_client: set[str] = set()
    for group, allowed_scopes in groups.items():
        values = packages.get(group)
        if not isinstance(values, list):
            raise MetadataError(f"packages.{group} must be an array")
        if len(values) != len(set(values)):
            raise MetadataError(f"packages.{group} contains duplicates")
        for project in values:
            if project not in projects:
                raise MetadataError(f"packages.{group} references unknown project {project}")
            if projects[project]["scope"] not in allowed_scopes:
                raise MetadataError(
                    f"packages.{group} contains {project} with incompatible scope {projects[project]['scope']}"
                )
            if group != "serverModules":
                if project in seen_client:
                    raise MetadataError(f"client package groups overlap at {project}")
                seen_client.add(project)

    expected_server_only = {p for p, item in projects.items() if item["scope"] == "serverOnly"}
    if not expected_server_only.issubset(set(packages["serverModules"])):
        missing = sorted(expected_server_only - set(packages["serverModules"]))
        raise MetadataError(f"server-only projects missing from packages.serverModules: {missing}")

    for project, item in projects.items():
        csproj = ROOT / "src" / project / f"{project}.csproj"
        if not csproj.exists():
            raise MetadataError(f"Configured project is missing: {csproj.relative_to(ROOT)}")
        try:
            tree = ET.parse(csproj)
        except ET.ParseError as exc:
            raise MetadataError(f"Invalid MSBuild XML in {csproj.relative_to(ROOT)}: {exc}") from exc
        target = tree.find(".//TargetFramework")
        assembly = tree.find(".//AssemblyName")
        if target is None or (target.text or "").strip() != item["targetFramework"]:
            actual = None if target is None else (target.text or "").strip()
            raise MetadataError(f"{project} TargetFramework is {actual!r}, expected {item['targetFramework']!r}")
        if assembly is None or (assembly.text or "").strip() != project:
            actual = None if assembly is None else (assembly.text or "").strip()
            raise MetadataError(f"{project} AssemblyName is {actual!r}, expected {project!r}")

    if release:
        bad = []
        if "TODO" in author.upper():
            bad.append("author")
        if "TODO" in thunderstore_namespace.upper():
            bad.append("thunderstoreNamespace")
        if guid_root.startswith("com.example."):
            bad.append("pluginGuidRoot")
        if suite_name == "ValheimSuite":
            bad.append("suiteName (still working codename)")
        if bad:
            raise MetadataError("Public-release metadata is incomplete: " + ", ".join(bad))


def xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;")


def cs_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def expected_files(cfg: dict) -> dict[Path, str]:
    props = f'''<?xml version="1.0" encoding="utf-8"?>\n<Project>\n  <!-- GENERATED from suite.config.json by scripts/suite_metadata.py. Do not edit manually. -->\n  <PropertyGroup>\n    <SuiteName>{xml_escape(cfg['suiteName'])}</SuiteName>\n    <SuiteRootNamespace>{xml_escape(cfg['rootNamespace'])}</SuiteRootNamespace>\n    <SuitePluginGuidRoot>{xml_escape(cfg['pluginGuidRoot'])}</SuitePluginGuidRoot>\n    <SuiteAuthors>{xml_escape(cfg['author'])}</SuiteAuthors>\n    <SuiteThunderstoreNamespace>{xml_escape(cfg['thunderstoreNamespace'])}</SuiteThunderstoreNamespace>\n    <SuiteVersion>{xml_escape(cfg['suiteVersion'])}</SuiteVersion>\n    <SuiteCSharpLanguageVersion>{xml_escape(cfg['csharpLanguageVersion'])}</SuiteCSharpLanguageVersion>\n    <JotunnVersion>{xml_escape(cfg['jotunnVersion'])}</JotunnVersion>\n    <BepInExPackVersion>{xml_escape(cfg['bepInExPackVersion'])}</BepInExPackVersion>\n    <NetFrameworkReferenceAssembliesVersion>{xml_escape(cfg['netFrameworkReferenceAssembliesVersion'])}</NetFrameworkReferenceAssembliesVersion>\n  </PropertyGroup>\n</Project>\n'''

    cs = f'''// <auto-generated />\nnamespace ValheimSuite.Common;\n\npublic static class SuiteConstants\n{{\n    public const string Name = "{cs_escape(cfg['suiteName'])}";\n    public const string Version = "{cs_escape(cfg['suiteVersion'])}";\n    public const string GuidRoot = "{cs_escape(cfg['pluginGuidRoot'])}";\n}}\n'''

    packages = cfg["packages"]
    lock = {
        "schemaVersion": 1,
        "generatedFrom": "suite.config.json",
        "suiteVersion": cfg["suiteVersion"],
        "dependencies": {
            "denikson-BepInExPack_Valheim": cfg["bepInExPackVersion"],
            "ValheimModding-Jotunn": cfg["jotunnVersion"],
        },
        "serverModules": packages["serverModules"],
        "requiredClientModules": packages["requiredClientModules"],
        "optionalClientModules": packages["optionalClientModules"],
        "clientOnlyModules": packages["clientOnlyModules"],
    }
    lock_text = json.dumps(lock, indent=2) + "\n"
    return {GENERATED_PROPS: props, GENERATED_CS: cs, PROFILE_LOCK: lock_text}


def sync(cfg: dict) -> None:
    validate(cfg)
    for path, content in expected_files(cfg).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")


def check(cfg: dict, release: bool = False) -> None:
    validate(cfg, release=release)
    mismatches = []
    for path, expected in expected_files(cfg).items():
        if not path.exists():
            mismatches.append(f"missing generated file {path.relative_to(ROOT)}")
            continue
        actual = path.read_text(encoding="utf-8")
        if actual != expected:
            mismatches.append(f"stale generated file {path.relative_to(ROOT)}")
    if mismatches:
        raise MetadataError("; ".join(mismatches) + ". Run: python3 scripts/suite_metadata.py sync")
    print("suite metadata: valid and synchronized")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync", help="Regenerate committed metadata outputs from suite.config.json")
    check_parser = sub.add_parser("check", help="Validate config and generated outputs")
    check_parser.add_argument("--release", action="store_true", help="Also require public-release naming metadata")
    args = parser.parse_args()
    try:
        cfg = load_config()
        if args.command == "sync":
            sync(cfg)
        else:
            check(cfg, release=args.release)
        return 0
    except MetadataError as exc:
        print(f"metadata error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
