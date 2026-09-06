"""Regression tests for the deployment-write symlink issue: an existing
destination DLL pathname that is a symlink must never be followed by
`scripts/deploy.py`. Every test deploys into a disposable temp directory,
built from a fully generated temp project (`generate_into_temp()`) with
fake build artifacts -- never the live `template/` tree.
"""

from __future__ import annotations

import importlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap.validate_generated import NO_BYTECODE_ENV
from tests.fixtures._helpers import generate_into_temp


def _write_dev_json(output_dir: Path) -> None:
    dev_dir = output_dir / ".valheim"
    dev_dir.mkdir(parents=True, exist_ok=True)
    (dev_dir / "dev.json").write_text(
        json.dumps({"schemaVersion": 1, "developmentOnly": True}), encoding="utf-8"
    )


def _write_fake_artifacts(output_dir: Path, cfg: dict, configuration: str = "Debug") -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    for project, item in cfg["projects"].items():
        payload = f"{project}-build-output".encode()
        dll = output_dir / "src" / project / "bin" / configuration / item["targetFramework"] / f"{project}.dll"
        dll.parent.mkdir(parents=True, exist_ok=True)
        dll.write_bytes(payload)
        contents[project] = payload
    return contents


def _deploy(output_dir: Path, target: str, destination: Path, configuration: str = "Debug") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", "scripts/deploy.py", "--target", target, "--configuration", configuration, "--destination", str(destination)],
        cwd=output_dir,
        env=NO_BYTECODE_ENV,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _import_deploy_from(scripts_dir: Path):
    """Import a fresh `deploy` module from `scripts_dir`, so `ROOT` inside
    resolves to the disposable generated project, never the live template."""
    sys.path.insert(0, str(scripts_dir))
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        sys.modules.pop("deploy", None)
        sys.modules.pop("suite_metadata", None)
        import deploy as dm

        importlib.reload(dm)
        return dm
    finally:
        sys.dont_write_bytecode = previous
        sys.path.remove(str(scripts_dir))


class _DeployFixtureTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.params, self.output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = json.loads((self.output_dir / "suite.config.json").read_text(encoding="utf-8"))
        _write_dev_json(self.output_dir)
        self.artifact_bytes = _write_fake_artifacts(self.output_dir, self.cfg)
        self.common = self.cfg["packages"]["commonModule"]
        self.server_modules = [self.common] + self.cfg["packages"]["serverModules"]

    def _dest_dir(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="valheimsuite-deploy-dest-"))


class ExternalSymlinkVictimTests(_DeployFixtureTestCase):
    def test_existing_destination_symlink_is_replaced_not_followed(self):
        dest_dir = self._dest_dir()
        victim_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-deploy-victim-"))
        victim = victim_dir / "victim.txt"
        victim.write_bytes(b"SENTINEL-DO-NOT-TOUCH")
        os.chmod(victim, 0o640)
        victim_mode_before = victim.stat().st_mode

        dll_name = f"{self.common}.dll"
        os.symlink(victim, dest_dir / dll_name)

        result = _deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)

        # external victim is completely untouched
        self.assertEqual(b"SENTINEL-DO-NOT-TOUCH", victim.read_bytes())
        self.assertEqual(victim_mode_before, victim.stat().st_mode)

        deployed = dest_dir / dll_name
        self.assertFalse(deployed.is_symlink())
        self.assertTrue(deployed.is_file())
        self.assertEqual(self.artifact_bytes[self.common], deployed.read_bytes())

        # sibling server artifacts also deployed normally
        for project in self.server_modules:
            path = dest_dir / f"{project}.dll"
            self.assertFalse(path.is_symlink())
            self.assertEqual(self.artifact_bytes[project], path.read_bytes())


class ExistingRegularDllTests(_DeployFixtureTestCase):
    def test_existing_regular_dll_is_replaced_on_redeploy(self):
        dest_dir = self._dest_dir()
        dll_name = f"{self.common}.dll"
        (dest_dir / dll_name).write_bytes(b"OLD STALE BYTES")

        result = _deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)

        deployed = dest_dir / dll_name
        self.assertTrue(deployed.is_file())
        self.assertFalse(deployed.is_symlink())
        self.assertEqual(self.artifact_bytes[self.common], deployed.read_bytes())


class DestinationAbsentTests(_DeployFixtureTestCase):
    def test_first_deployment_with_absent_destination_succeeds(self):
        dest_dir = self._dest_dir() / "plugins"
        self.assertFalse(dest_dir.exists())

        result = _deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)
        for project in self.server_modules:
            self.assertEqual(self.artifact_bytes[project], (dest_dir / f"{project}.dll").read_bytes())


class NonRegularFinalTargetTests(_DeployFixtureTestCase):
    def test_existing_directory_target_fails_safely(self):
        dest_dir = self._dest_dir()
        dll_name = f"{self.common}.dll"
        (dest_dir / dll_name).mkdir()

        result = _deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)
        self.assertTrue((dest_dir / dll_name).is_dir())
        self.assertEqual([dll_name], os.listdir(dest_dir))

    def test_existing_fifo_target_fails_safely(self):
        dest_dir = self._dest_dir()
        dll_name = f"{self.common}.dll"
        os.mkfifo(dest_dir / dll_name)

        result = _deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)
        self.assertTrue(stat.S_ISFIFO((dest_dir / dll_name).lstat().st_mode))
        self.assertEqual([dll_name], os.listdir(dest_dir))


class StagingCopyFailureTests(_DeployFixtureTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.deploy = _import_deploy_from(self.output_dir / "scripts")

    def test_copy_failure_leaves_no_partial_dll_and_preserves_existing(self):
        dest_dir = self._dest_dir()
        dll_name = f"{self.common}.dll"
        (dest_dir / dll_name).write_bytes(b"EXISTING VALID BYTES")

        def _boom(_src, _dst):
            raise OSError("simulated write failure")

        argv = ["deploy.py", "--target", "server", "--configuration", "Debug", "--destination", str(dest_dir)]
        with mock.patch.object(self.deploy.shutil, "copyfileobj", side_effect=_boom), mock.patch.object(sys, "argv", argv):
            rc = self.deploy.main()

        self.assertEqual(2, rc)
        # failure occurred before promotion: the existing valid destination is untouched
        self.assertEqual(b"EXISTING VALID BYTES", (dest_dir / dll_name).read_bytes())
        # no stray temporary file left behind
        self.assertEqual([dll_name], os.listdir(dest_dir))


class StaleCleanupTests(_DeployFixtureTestCase):
    def test_stale_prefixed_dll_removed_unrelated_dll_kept(self):
        dest_dir = self._dest_dir()
        prefix = f"{self.cfg['rootNamespace']}."
        stale_name = f"{prefix}OldModule.dll"
        other_name = "Other.Unrelated.dll"
        (dest_dir / stale_name).write_bytes(b"STALE")
        (dest_dir / other_name).write_bytes(b"UNRELATED")

        result = _deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertIn("removed stale suite DLLs", result.stdout)
        self.assertFalse((dest_dir / stale_name).exists())
        self.assertTrue((dest_dir / other_name).exists())


if __name__ == "__main__":
    unittest.main()
