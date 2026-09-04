#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

import suite_metadata as metadata

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "packages"
ZIP_TIME = (2020, 1, 1, 0, 0, 0)

class PackageError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise PackageError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PackageError(f"{path} must contain a JSON object")
    return value


def artifact_for(project: str, tfm: str) -> Path:
    exact = ROOT / "src" / project / "bin" / "Release" / tfm / f"{project}.dll"
    if not exact.is_file():
        raise PackageError(f"missing Release artifact: {exact.relative_to(ROOT)}")
    return exact


def add_bytes(zf: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arcname, ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    zf.writestr(info, data)


def add_file(zf: zipfile.ZipFile, arcname: str, source: Path) -> None:
    add_bytes(zf, arcname, source.read_bytes())


def create_package(name: str, version: str, modules: list[str], cfg: dict, package_kind: str) -> Path:
    common = cfg["packages"]["commonModule"]
    ordered = [common] + [m for m in modules if m != common]
    projects = cfg["projects"]
    filename = OUT / f"{name}-{version}.zip"
    metadata = {
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
    with zipfile.ZipFile(filename, "w") as zf:
        for project in ordered:
            dll = artifact_for(project, projects[project]["targetFramework"])
            add_file(zf, f"BepInEx/plugins/{cfg['suiteName']}/{dll.name}", dll)
        add_bytes(zf, "package-info.json", (json.dumps(metadata, indent=2) + "\n").encode())
        for doc in ("README.md", "CHANGELOG.md"):
            source = ROOT / doc
            if source.exists():
                add_file(zf, doc, source)
    return filename


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clean", action="store_true", help="Remove old package ZIPs before writing")
    args = parser.parse_args()
    try:
        cfg = metadata.load_config()
        metadata.validate(cfg)
        for generated_path, expected in metadata.expected_files(cfg).items():
            if not generated_path.exists() or generated_path.read_text(encoding="utf-8") != expected:
                raise PackageError(
                    f"generated metadata is stale: {generated_path.relative_to(ROOT)}; "
                    "run python3 scripts/suite_metadata.py sync"
                )
        packages = cfg["packages"]
        version = cfg["suiteVersion"]
        OUT.mkdir(parents=True, exist_ok=True)
        if args.clean:
            for old in OUT.glob("*.zip"):
                old.unlink()
            sums = OUT / "SHA256SUMS"
            if sums.exists():
                sums.unlink()

        definitions = [
            (f"{cfg['suiteName']}-ServerCore", [p for p in packages["serverModules"] if cfg["projects"][p]["scope"] == "serverOnly"], "server-core"),
            (f"{cfg['suiteName']}-Client", packages["clientOnlyModules"], "client-only"),
        ]
        for module in packages["requiredClientModules"] + packages["optionalClientModules"]:
            definitions.append((module.replace(".", "-"), [module], "shared-module"))
        definitions.extend([
            (f"{cfg['suiteName']}-ServerPack", packages["serverModules"], "server-pack"),
            (f"{cfg['suiteName']}-ClientPack", packages["requiredClientModules"] + packages["optionalClientModules"] + packages["clientOnlyModules"], "client-pack"),
        ])

        created = [create_package(name, version, modules, cfg, kind) for name, modules, kind in definitions]
        lines = []
        for path in sorted(created):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.name}")
        (OUT / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("created packages:")
        for path in created:
            print(f"  {path.relative_to(ROOT)}")
        print(f"  {(OUT / 'SHA256SUMS').relative_to(ROOT)}")
        return 0
    except PackageError as exc:
        print(f"package error: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
