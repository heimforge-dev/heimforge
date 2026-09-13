"""Regression coverage: `scripts/deploy.py` must reject deployment to a
side with no runtime module targeting it, before any destination
mutation. Common alone is a shared library other plugins reference, not
itself a runtime BepInEx plugin -- deploying only `Common.dll` to a side
with nothing to load it would create a deployment-ownership manifest for
a plugin that does not exist.

This must hold both for the standard bootstrap-generated combinations
(module presence known at generation time) and for a suite whose
`projects`/`packages` were structurally edited after generation (custom
`serverOnly`/`clientOnly`/`sharedRequired`/`sharedOptional` project added),
since side availability is derived from current validated package
membership, not from bootstrap-time module identity.

Standard optional-module combinations use `generate_into_temp()` to exercise
real generation/certification. Downstream deployment scenarios use private
`clone_generated_temp()` fixtures from certified seeds. Every destination is
disposable; the live `template/` tree is never used.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from tests.fixtures._helpers import NO_BYTECODE_ENV, clone_generated_temp, generate_into_temp, run_deploy, write_dev_json, write_fake_artifacts

CSHARP_PROJECT_TYPE_GUID = "{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}"


def _run_sync(output_dir: Path) -> None:
    """Regenerate `build/Suite.Generated.props`/`SuiteConstants.Generated.cs`/
    `packaging/profile-lock.json` after a manual `suite.config.json` edit --
    the documented real workflow (see root `README.md`'s "Hardened metadata
    model") -- so `deploy.py`'s own staleness check doesn't mask the
    side-availability check under test."""
    result = subprocess.run(
        ["python3", "scripts/suite_metadata.py", "sync"],
        cwd=output_dir,
        env=NO_BYTECODE_ENV,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert result.returncode == 0, result.stdout


def _load_cfg(output_dir: Path) -> dict:
    return json.loads((output_dir / "suite.config.json").read_text(encoding="utf-8"))


def _save_cfg(output_dir: Path, cfg: dict) -> None:
    (output_dir / "suite.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _write_csproj(output_dir: Path, project: str, tfm: str) -> None:
    project_dir = output_dir / "src" / project
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / f"{project}.csproj").write_text(
        f'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>{tfm}</TargetFramework>'
        f"<AssemblyName>{project}</AssemblyName></PropertyGroup></Project>",
        encoding="utf-8",
    )


def _add_sln_entry(output_dir: Path, cfg: dict, project: str) -> None:
    sln_path = output_dir / f"{cfg['rootNamespace']}.sln"
    lines = sln_path.read_text(encoding="utf-8").splitlines()
    insert_at = next(i for i, line in enumerate(lines) if line.strip() == "Global")
    guid = "{" + str(uuid.uuid4()).upper() + "}"
    lines[insert_at:insert_at] = [
        f'Project("{CSHARP_PROJECT_TYPE_GUID}") = "{project}", "src\\{project}\\{project}.csproj", "{guid}"',
        "EndProject",
    ]
    section = next(i for i, line in enumerate(lines) if "GlobalSection(ProjectConfigurationPlatforms)" in line)
    lines[section + 1:section + 1] = [
        f"\t\t{guid}.{configuration}|Any CPU.{mapping} = {configuration}|Any CPU"
        for configuration in ("Debug", "Release") for mapping in ("ActiveCfg", "Build.0")
    ]
    sln_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _add_custom_project(output_dir: Path, cfg: dict, project: str, scope: str, groups: set[str], tfm: str = "net48") -> None:
    """Register a metadata-valid custom project with `project`, matching
    `.sln` entry, and stub `.csproj`/DLL -- a supported post-generation
    structural edit."""
    cfg["projects"][project] = {"scope": scope, "targetFramework": tfm}
    for group in ("serverModules", "requiredClientModules", "optionalClientModules", "clientOnlyModules"):
        if group in groups:
            cfg["packages"][group].append(project)
    _write_csproj(output_dir, project, tfm)
    _add_sln_entry(output_dir, cfg, project)


def _generate_with_artifacts(**overrides) -> Path:
    _params, output_dir, result = generate_into_temp(**overrides)
    assert result.ok, result.errors
    cfg = _load_cfg(output_dir)
    write_dev_json(output_dir)
    write_fake_artifacts(output_dir, cfg)
    return output_dir


def _clone_with_artifacts(**overrides) -> Path:
    _params, output_dir, result = clone_generated_temp(**overrides)
    assert result.ok, result.errors
    cfg = _load_cfg(output_dir)
    write_dev_json(output_dir)
    write_fake_artifacts(output_dir, cfg)
    return output_dir


class StandardCombinationSideAvailabilityTests(unittest.TestCase):
    """Section 3/4/14: the standard bootstrap-generated combinations
    accept/reject exactly the sides `has_server_package`/
    `has_client_package` predict."""

    def test_server_core_only_accepts_server_and_rejects_client(self):
        output_dir = _generate_with_artifacts(include_client=False, include_shared_diagnostics=False)

        rejected_dest = Path(tempfile.mkdtemp(prefix="valheimsuite-absent-side-"))
        shutil.rmtree(rejected_dest)
        rejected = run_deploy(output_dir, "client", rejected_dest)
        self.assertNotEqual(0, rejected.returncode, rejected.stdout)
        self.assertIn("no runtime module targets the client side", rejected.stdout)
        self.assertFalse(rejected_dest.exists())

        accepted_dest = Path(tempfile.mkdtemp(prefix="valheimsuite-available-side-"))
        accepted = run_deploy(output_dir, "server", accepted_dest)
        self.assertEqual(0, accepted.returncode, accepted.stdout)

    def test_client_only_accepts_client_and_rejects_server(self):
        output_dir = _generate_with_artifacts(include_server_core=False, include_shared_diagnostics=False)

        rejected_dest = Path(tempfile.mkdtemp(prefix="valheimsuite-absent-side-"))
        shutil.rmtree(rejected_dest)
        rejected = run_deploy(output_dir, "server", rejected_dest)
        self.assertNotEqual(0, rejected.returncode, rejected.stdout)
        self.assertIn("no runtime module targets the server side", rejected.stdout)
        self.assertFalse(rejected_dest.exists())

        accepted_dest = Path(tempfile.mkdtemp(prefix="valheimsuite-available-side-"))
        accepted = run_deploy(output_dir, "client", accepted_dest)
        self.assertEqual(0, accepted.returncode, accepted.stdout)

    def test_shared_diagnostics_only_accepts_both_sides(self):
        output_dir = _generate_with_artifacts(include_server_core=False, include_client=False)

        server = run_deploy(output_dir, "server", Path(tempfile.mkdtemp(prefix="valheimsuite-both-side-")))
        self.assertEqual(0, server.returncode, server.stdout)
        client = run_deploy(output_dir, "client", Path(tempfile.mkdtemp(prefix="valheimsuite-both-side-")))
        self.assertEqual(0, client.returncode, client.stdout)

    def test_server_core_and_client_accepts_both_sides(self):
        output_dir = _generate_with_artifacts(include_shared_diagnostics=False)

        server = run_deploy(output_dir, "server", Path(tempfile.mkdtemp(prefix="valheimsuite-both-side-")))
        self.assertEqual(0, server.returncode, server.stdout)
        client = run_deploy(output_dir, "client", Path(tempfile.mkdtemp(prefix="valheimsuite-both-side-")))
        self.assertEqual(0, client.returncode, client.stdout)


class PreMutationRejectionTests(unittest.TestCase):
    """Section 5: rejecting an absent-side deploy must happen before any
    destination mutation -- no directory created, no manifest written, no
    DLL copied -- and an existing destination must come out byte-identical."""

    def setUp(self) -> None:
        self.output_dir = _clone_with_artifacts(include_client=False, include_shared_diagnostics=False)
        self.cfg = _load_cfg(self.output_dir)

    def test_absent_destination_remains_absent(self) -> None:
        destination = Path(tempfile.mkdtemp(prefix="valheimsuite-absent-side-noexist-"))
        shutil.rmtree(destination)
        result = run_deploy(self.output_dir, "client", destination)
        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertFalse(destination.exists())

    def test_existing_destination_is_byte_identical_afterward(self) -> None:
        destination = Path(tempfile.mkdtemp(prefix="valheimsuite-absent-side-existing-"))
        sentinel = destination / "sentinel.txt"
        sentinel.write_bytes(b"PRE-EXISTING-CONTENT")
        before = {p.name: p.read_bytes() for p in destination.iterdir()}

        result = run_deploy(self.output_dir, "client", destination)

        self.assertNotEqual(0, result.returncode, result.stdout)
        after = {p.name: p.read_bytes() for p in destination.iterdir()}
        self.assertEqual(before, after)

    def test_no_deployment_manifest_or_common_dll_is_written(self) -> None:
        destination = Path(tempfile.mkdtemp(prefix="valheimsuite-absent-side-manifest-"))
        result = run_deploy(self.output_dir, "client", destination)

        self.assertNotEqual(0, result.returncode, result.stdout)
        manifest = destination / f".{self.cfg['suiteName']}.deploy-manifest.json"
        self.assertFalse(manifest.exists())
        common = self.cfg["packages"]["commonModule"]
        self.assertFalse((destination / f"{common}.dll").exists())
        self.assertEqual([], list(destination.iterdir()))


class CustomProjectSideAvailabilityTests(unittest.TestCase):
    """Section 6/15: side availability must derive from current validated
    package membership, not bootstrap-time standard-module identity, so a
    supported post-generation structural edit is reflected correctly."""

    def _generate_common_only_base(self) -> tuple[Path, dict]:
        """A minimal generated suite (ServerCore only, so generation itself
        stays valid) with ServerCore then removed from config/packages/`.sln`,
        leaving a bare base to add exactly one custom project onto -- so the
        only runtime module present is the custom one under test."""
        output_dir = _clone_with_artifacts(include_client=False, include_shared_diagnostics=False)
        cfg = _load_cfg(output_dir)
        common = cfg["packages"]["commonModule"]
        server_core = next(p for p in cfg["projects"] if p != common)

        sln_path = output_dir / f"{cfg['rootNamespace']}.sln"
        lines = sln_path.read_text(encoding="utf-8").splitlines()
        start = next(i for i, line in enumerate(lines) if line.strip().startswith("Project(") and f'"{server_core}"' in line)
        end = next(i for i in range(start, len(lines)) if lines[i].strip() == "EndProject")
        guid = lines[start].rsplit('"', 2)[1]
        del lines[start : end + 1]
        lines = [line for line in lines if not line.strip().startswith(guid + ".")]
        sln_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        del cfg["projects"][server_core]
        cfg["packages"]["serverModules"] = []
        return output_dir, cfg

    def test_custom_server_only_project_is_server_valid_client_rejected(self) -> None:
        output_dir, cfg = self._generate_common_only_base()
        _add_custom_project(output_dir, cfg, f"{cfg['rootNamespace']}.CustomServer", "serverOnly", {"serverModules"})
        _save_cfg(output_dir, cfg)
        _run_sync(output_dir)
        write_fake_artifacts(output_dir, cfg)

        server = run_deploy(output_dir, "server", Path(tempfile.mkdtemp(prefix="valheimsuite-custom-")))
        self.assertEqual(0, server.returncode, server.stdout)
        client = run_deploy(output_dir, "client", Path(tempfile.mkdtemp(prefix="valheimsuite-custom-")))
        self.assertNotEqual(0, client.returncode, client.stdout)
        self.assertIn("no runtime module targets the client side", client.stdout)

    def test_custom_client_only_project_is_client_valid_server_rejected(self) -> None:
        output_dir, cfg = self._generate_common_only_base()
        _add_custom_project(output_dir, cfg, f"{cfg['rootNamespace']}.CustomClient", "clientOnly", {"clientOnlyModules"})
        _save_cfg(output_dir, cfg)
        _run_sync(output_dir)
        write_fake_artifacts(output_dir, cfg)

        client = run_deploy(output_dir, "client", Path(tempfile.mkdtemp(prefix="valheimsuite-custom-")))
        self.assertEqual(0, client.returncode, client.stdout)
        server = run_deploy(output_dir, "server", Path(tempfile.mkdtemp(prefix="valheimsuite-custom-")))
        self.assertNotEqual(0, server.returncode, server.stdout)
        self.assertIn("no runtime module targets the server side", server.stdout)

    def test_custom_shared_required_project_is_valid_on_both_sides(self) -> None:
        output_dir, cfg = self._generate_common_only_base()
        _add_custom_project(
            output_dir, cfg, f"{cfg['rootNamespace']}.CustomShared", "sharedRequired",
            {"serverModules", "requiredClientModules"},
        )
        _save_cfg(output_dir, cfg)
        _run_sync(output_dir)
        write_fake_artifacts(output_dir, cfg)

        server = run_deploy(output_dir, "server", Path(tempfile.mkdtemp(prefix="valheimsuite-custom-")))
        self.assertEqual(0, server.returncode, server.stdout)
        client = run_deploy(output_dir, "client", Path(tempfile.mkdtemp(prefix="valheimsuite-custom-")))
        self.assertEqual(0, client.returncode, client.stdout)

    def test_custom_shared_optional_project_is_valid_on_both_sides(self) -> None:
        output_dir, cfg = self._generate_common_only_base()
        _add_custom_project(
            output_dir, cfg, f"{cfg['rootNamespace']}.CustomShared", "sharedOptional",
            {"serverModules", "optionalClientModules"},
        )
        _save_cfg(output_dir, cfg)
        _run_sync(output_dir)
        write_fake_artifacts(output_dir, cfg)

        server = run_deploy(output_dir, "server", Path(tempfile.mkdtemp(prefix="valheimsuite-custom-")))
        self.assertEqual(0, server.returncode, server.stdout)
        client = run_deploy(output_dir, "client", Path(tempfile.mkdtemp(prefix="valheimsuite-custom-")))
        self.assertEqual(0, client.returncode, client.stdout)


if __name__ == "__main__":
    unittest.main()
