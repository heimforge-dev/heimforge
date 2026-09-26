"""Update HeimForge's default Jötunn/BepInEx dependency baseline.

This command owns only the bootstrapper's default dependency pins. It does
not modify generated projects, install runtime packages, refresh references,
build, deploy, or restart anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import naming


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "bootstrap" / "model.py"
MANIFEST_PATH = ROOT / "BOOTSTRAP_MANIFEST.json"


class BaselineUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Baseline:
    jotunn: str
    bepinex: str
    netfx: str


_MODEL_PATTERNS = {
    "jotunn": re.compile(
        r'(?m)^(\s*"jotunn_version"\s*:\s*")([^"\r\n]+)(",\s*)$'
    ),
    "bepinex": re.compile(
        r'(?m)^(\s*"bepinex_version"\s*:\s*")([^"\r\n]+)(",\s*)$'
    ),
    "netfx": re.compile(
        r'(?m)^(\s*"netfx_reference_version"\s*:\s*")([^"\r\n]+)(",\s*)$'
    ),
}

_MANIFEST_PATTERNS = {
    "jotunn": re.compile(
        r'(?m)^(\s*"Jotunn"\s*:\s*")([^"\r\n]+)(",\s*)$'
    ),
    "bepinex": re.compile(
        r'(?m)^(\s*"BepInExPack_Valheim"\s*:\s*")([^"\r\n]+)(",\s*)$'
    ),
    "netfx": re.compile(
        r'(?m)^(\s*"Microsoft.NETFramework.ReferenceAssemblies"\s*:\s*")([^"\r\n]+)("\s*,?\s*)$'
    ),
}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update HeimForge's default Jötunn/BepInEx dependency baseline."
    )
    parser.add_argument("--jotunn", help="New default Jötunn version")
    parser.add_argument("--bepinex", help="New default BepInExPack Valheim version")
    args = parser.parse_args(argv)

    if args.jotunn is None and args.bepinex is None:
        parser.error("at least one of --jotunn or --bepinex is required")

    return args


def _validate_version(value: str, field: str) -> str:
    try:
        return naming.validate_semver(value, field)
    except naming.NamingError as exc:
        raise BaselineUpdateError(str(exc)) from exc


def _extract_one(text: str, pattern: re.Pattern[str], label: str) -> str:
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise BaselineUpdateError(
            f"expected exactly one {label} baseline entry, found {len(matches)}"
        )
    return matches[0].group(2)


def _replace_one(
    text: str,
    pattern: re.Pattern[str],
    expected_old: str,
    new: str,
    label: str,
) -> str:
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise BaselineUpdateError(
            f"expected exactly one {label} baseline entry, found {len(matches)}"
        )

    match = matches[0]
    actual = match.group(2)
    if actual != expected_old:
        raise BaselineUpdateError(
            f"{label} changed during update: expected {expected_old!r}, found {actual!r}"
        )

    return text[: match.start(2)] + new + text[match.end(2) :]


def _load_authorities() -> tuple[Baseline, str, str]:
    model_text = MODEL_PATH.read_text(encoding="utf-8")
    manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")

    model = Baseline(
        jotunn=_extract_one(
            model_text, _MODEL_PATTERNS["jotunn"], "bootstrap/model.py Jötunn"
        ),
        bepinex=_extract_one(
            model_text, _MODEL_PATTERNS["bepinex"], "bootstrap/model.py BepInEx"
        ),
        netfx=_extract_one(
            model_text,
            _MODEL_PATTERNS["netfx"],
            "bootstrap/model.py .NET Framework reference assemblies",
        ),
    )

    manifest_regex = Baseline(
        jotunn=_extract_one(
            manifest_text,
            _MANIFEST_PATTERNS["jotunn"],
            "BOOTSTRAP_MANIFEST.json Jötunn",
        ),
        bepinex=_extract_one(
            manifest_text,
            _MANIFEST_PATTERNS["bepinex"],
            "BOOTSTRAP_MANIFEST.json BepInEx",
        ),
        netfx=_extract_one(
            manifest_text,
            _MANIFEST_PATTERNS["netfx"],
            "BOOTSTRAP_MANIFEST.json .NET Framework reference assemblies",
        ),
    )

    try:
        manifest = json.loads(manifest_text)
        dependency_baseline = manifest["dependencyBaseline"]
        manifest_json = Baseline(
            jotunn=dependency_baseline["Jotunn"],
            bepinex=dependency_baseline["BepInExPack_Valheim"],
            netfx=dependency_baseline["Microsoft.NETFramework.ReferenceAssemblies"],
        )
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise BaselineUpdateError(
            f"BOOTSTRAP_MANIFEST.json has invalid dependencyBaseline metadata: {exc}"
        ) from exc

    if manifest_regex != manifest_json:
        raise BaselineUpdateError(
            "BOOTSTRAP_MANIFEST.json textual baseline entries do not match its parsed metadata"
        )

    if model != manifest_json:
        raise BaselineUpdateError(
            "dependency baseline authorities disagree before mutation: "
            f"bootstrap/model.py has Jötunn {model.jotunn}, BepInEx {model.bepinex}; "
            f"BOOTSTRAP_MANIFEST.json has Jötunn {manifest_json.jotunn}, "
            f"BepInEx {manifest_json.bepinex}, "
            f".NET Framework references {manifest_json.netfx}"
        )

    _validate_version(model.jotunn, "jotunnVersion")
    _validate_version(model.bepinex, "bepInExPackVersion")
    _validate_version(model.netfx, "netFrameworkReferenceAssembliesVersion")

    return model, model_text, manifest_text


def _atomic_write_text(path: Path, content: str) -> None:
    if path.is_symlink():
        raise BaselineUpdateError(f"refusing to replace symlink: {path.relative_to(ROOT)}")

    mode = path.stat().st_mode & 0o777
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())

        os.chmod(temp_name, mode)
        os.replace(temp_name, path)

        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _restore(originals: dict[Path, str], attempted: list[Path]) -> None:
    failures: list[str] = []

    for path in reversed(attempted):
        try:
            _atomic_write_text(path, originals[path])
        except BaseException as exc:
            failures.append(f"{path.relative_to(ROOT)}: {exc}")

    if failures:
        raise BaselineUpdateError(
            "baseline update rollback was incomplete: " + "; ".join(failures)
        )


def update_baseline(*, jotunn: str | None, bepinex: str | None) -> Baseline:
    current, model_text, manifest_text = _load_authorities()

    target = Baseline(
        jotunn=current.jotunn if jotunn is None else _validate_version(jotunn, "jotunnVersion"),
        bepinex=current.bepinex
        if bepinex is None
        else _validate_version(bepinex, "bepInExPackVersion"),
        netfx=current.netfx,
    )

    if target == current:
        return current

    new_model = model_text
    new_manifest = manifest_text

    if target.jotunn != current.jotunn:
        new_model = _replace_one(
            new_model,
            _MODEL_PATTERNS["jotunn"],
            current.jotunn,
            target.jotunn,
            "bootstrap/model.py Jötunn",
        )
        new_manifest = _replace_one(
            new_manifest,
            _MANIFEST_PATTERNS["jotunn"],
            current.jotunn,
            target.jotunn,
            "BOOTSTRAP_MANIFEST.json Jötunn",
        )

    if target.bepinex != current.bepinex:
        new_model = _replace_one(
            new_model,
            _MODEL_PATTERNS["bepinex"],
            current.bepinex,
            target.bepinex,
            "bootstrap/model.py BepInEx",
        )
        new_manifest = _replace_one(
            new_manifest,
            _MANIFEST_PATTERNS["bepinex"],
            current.bepinex,
            target.bepinex,
            "BOOTSTRAP_MANIFEST.json BepInEx",
        )

    originals = {
        MODEL_PATH: model_text,
        MANIFEST_PATH: manifest_text,
    }
    attempted: list[Path] = []

    try:
        if new_model != model_text:
            attempted.append(MODEL_PATH)
            _atomic_write_text(MODEL_PATH, new_model)

        if new_manifest != manifest_text:
            attempted.append(MANIFEST_PATH)
            _atomic_write_text(MANIFEST_PATH, new_manifest)

        verified, _model_text, _manifest_text = _load_authorities()
        if verified != target:
            raise BaselineUpdateError(
                f"post-update verification failed: expected {target}, found {verified}"
            )
    except BaseException as exc:
        try:
            _restore(originals, attempted)
        except BaselineUpdateError as rollback_exc:
            raise rollback_exc from exc
        raise

    return target


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    try:
        before, _model_text, _manifest_text = _load_authorities()
        after = update_baseline(jotunn=args.jotunn, bepinex=args.bepinex)
    except (BaselineUpdateError, OSError) as exc:
        print(f"baseline update error: {exc}", file=sys.stderr)
        return 2

    if before == after:
        print(
            f"dependency baseline already matches: "
            f"Jötunn {after.jotunn}, BepInExPack Valheim {after.bepinex}"
        )
        return 0

    print(
        f"dependency baseline updated: "
        f"Jötunn {before.jotunn} -> {after.jotunn}; "
        f"BepInExPack Valheim {before.bepinex} -> {after.bepinex}"
    )
    print("updated bootstrap/model.py")
    print("updated BOOTSTRAP_MANIFEST.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
