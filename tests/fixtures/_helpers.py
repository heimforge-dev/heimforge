"""Shared fixture-generation helper for tests/fixtures/*.

Every fixture renders into a system temp directory (tempfile.mkdtemp), never
under this repository, so no bootstrapper .gitignore handling is needed and
independence from the bootstrapper is proven by construction.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bootstrap.create_project import generate
from bootstrap.model import ProjectParams
from bootstrap.render import TEMPLATE_DIR
from bootstrap.validate_generated import NO_BYTECODE_ENV, ValidationResult


def make_params(**overrides) -> ProjectParams:
    defaults = dict(
        suite_name="Sampleheim",
        root_namespace="Sampleheim",
        plugin_guid_root="org.example-tests.sampleheim",
        author="Sample Author",
        thunderstore_namespace="SampleNS",
        suite_version="0.1.0",
    )
    defaults.update(overrides)
    return ProjectParams(**defaults)


def copy_template_to_temp() -> Path:
    """A private, disposable copy of the real `template/` tree that a test
    can freely mutate (inject/delete files) without touching the
    bootstrapper's own template or leaking state to other tests.
    """
    dest = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-template-copy-"))
    shutil.copytree(TEMPLATE_DIR, dest, dirs_exist_ok=True)
    return dest


def import_scripts_from(scripts_dir: Path):
    """Import fresh `suite_metadata`/`package` modules from `scripts_dir`,
    so `ROOT = Path(__file__).resolve().parents[1]` inside each resolves
    to `scripts_dir.parent` -- a disposable copy or generated project,
    never the live `template/`."""
    sys.path.insert(0, str(scripts_dir))
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        sys.modules.pop("suite_metadata", None)
        sys.modules.pop("package", None)
        import suite_metadata as sm
        import package as pkg

        importlib.reload(sm)
        importlib.reload(pkg)
        return sm, pkg
    finally:
        sys.dont_write_bytecode = previous
        sys.path.remove(str(scripts_dir))


def generate_into_temp(*, template_dir: Path | None = None, **overrides) -> tuple[ProjectParams, Path, ValidationResult]:
    params = make_params(**overrides)
    output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
    result = generate(params, output_dir, template_dir=template_dir)
    return params, output_dir, result


def expected_relpaths(
    root_namespace: str, *, server_core: bool = True, client: bool = True, shared_diagnostics: bool = True
) -> set[str]:
    """The exact set of files a successful `generate()` must produce:
    every manifest-approved path (post `__ROOT_NAMESPACE__` substitution,
    filtered to the included optional modules) plus the handful of paths
    `generate()`/`suite_metadata.py sync` write programmatically. Shared
    by every test asserting an exact output surface so there is one
    definition of "the expected output" instead of several that could
    silently drift apart.
    """
    from bootstrap.template_manifest import OPTIONAL_TEMPLATE_FILES, REQUIRED_TEMPLATE_FILES

    expected = {rel.replace("__ROOT_NAMESPACE__", root_namespace) for rel in REQUIRED_TEMPLATE_FILES}
    has_server_package = server_core or shared_diagnostics
    has_client_package = client or shared_diagnostics
    for included, group in (
        (server_core, "server_core"),
        (client, "client"),
        (shared_diagnostics, "shared_diagnostics"),
        (has_server_package, "server_package_docs"),
        (has_client_package, "client_package_docs"),
    ):
        if included:
            expected |= {rel.replace("__ROOT_NAMESPACE__", root_namespace) for rel in OPTIONAL_TEMPLATE_FILES[group]}
    expected |= {
        "suite.config.json",
        "suite.identity.lock.json",
        f"{root_namespace}.sln",
        "build/Suite.Generated.props",
        f"src/{root_namespace}.Common/SuiteConstants.Generated.cs",
        "packaging/profile-lock.json",
    }
    return expected


def write_dev_json(output_dir: Path, *, client_plugin_dir: str | None = None, server_plugin_dir: str | None = None) -> None:
    dev_dir = output_dir / ".valheim"
    dev_dir.mkdir(parents=True, exist_ok=True)
    payload = {"schemaVersion": 1, "developmentOnly": True}
    if client_plugin_dir is not None:
        payload["clientPluginDir"] = client_plugin_dir
    if server_plugin_dir is not None:
        payload["serverPluginDir"] = server_plugin_dir
    (dev_dir / "dev.json").write_text(json.dumps(payload), encoding="utf-8")


def write_fake_artifacts(output_dir: Path, cfg: dict, configuration: str = "Debug") -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    for project, item in cfg["projects"].items():
        payload = f"{project}-build-output".encode()
        dll = output_dir / "src" / project / "bin" / configuration / item["targetFramework"] / f"{project}.dll"
        dll.parent.mkdir(parents=True, exist_ok=True)
        dll.write_bytes(payload)
        contents[project] = payload
    return contents


def run_deploy(output_dir: Path, target: str, destination: Path | None = None, configuration: str = "Debug") -> subprocess.CompletedProcess:
    argv = ["python3", "scripts/deploy.py", "--target", target, "--configuration", configuration]
    if destination is not None:
        argv += ["--destination", str(destination)]
    return subprocess.run(
        argv,
        cwd=output_dir,
        env=NO_BYTECODE_ENV,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def import_deploy_from(scripts_dir: Path):
    """Import a fresh `deploy` module from `scripts_dir`, so `ROOT` inside
    resolves to the disposable generated project, never the live template."""
    sys.path.insert(0, str(scripts_dir))
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        for name in ("deploy", "dev_config", "remote_deploy", "suite_metadata"):
            sys.modules.pop(name, None)
        import deploy as dm

        importlib.reload(dm)
        return dm
    finally:
        sys.dont_write_bytecode = previous
        sys.path.remove(str(scripts_dir))


class DeployFixtureTestCase(unittest.TestCase):
    """Base fixture for deploy.py tests: a fully generated temp project with
    fake build artifacts, ready to deploy into a disposable destination.
    Subclasses needing a non-default suite identity (e.g. reproducing an
    issue tied to a specific namespace) set `generate_overrides`."""

    generate_overrides: dict = {}

    def setUp(self) -> None:
        self.params, self.output_dir, result = generate_into_temp(**self.generate_overrides)
        self.assertTrue(result.ok, result.errors)
        self.cfg = json.loads((self.output_dir / "suite.config.json").read_text(encoding="utf-8"))
        write_dev_json(self.output_dir)
        self.artifact_bytes = write_fake_artifacts(self.output_dir, self.cfg)
        self.common = self.cfg["packages"]["commonModule"]
        self.server_modules = [self.common] + self.cfg["packages"]["serverModules"]

    def _dest_dir(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="valheimsuite-deploy-dest-"))
