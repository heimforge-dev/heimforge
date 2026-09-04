"""CLI orchestration: render a template into a fresh standalone project,
generate its identity-dependent metadata, and validate the result.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
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


def _safe_output_dir(raw: str) -> Path:
    output_dir = Path(raw).expanduser().resolve()
    if output_dir == Path("/") or output_dir == Path.home().resolve():
        raise GenerationError(f"refusing unsafe output directory: {output_dir}")
    if output_dir == BOOTSTRAPPER_ROOT or BOOTSTRAPPER_ROOT.is_relative_to(output_dir):
        raise GenerationError(
            f"refusing output directory that is, or is an ancestor of, the bootstrapper repository: {output_dir}"
        )
    return output_dir


def generate(params: ProjectParams, output_dir: Path, force: bool = False) -> ValidationResult:
    validate_params(params)

    if output_dir.exists() and any(output_dir.iterdir()):
        if not force:
            raise GenerationError(f"output directory is not empty: {output_dir}; pass --force to overwrite")
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    model: ProjectModel = build_model(params)
    render_tree(model, output_dir)

    (output_dir / "suite.config.json").write_text(
        json.dumps(suite_config_dict(model), indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / f"{params.root_namespace}.sln").write_text(solution_text(model), encoding="utf-8")

    sync = subprocess.run(
        ["python3", "scripts/suite_metadata.py", "sync"], cwd=output_dir, text=True, capture_output=True
    )
    if sync.returncode != 0:
        raise GenerationError(f"suite_metadata.py sync failed: {sync.stdout}{sync.stderr}")

    return validate_generated(output_dir, params)


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
