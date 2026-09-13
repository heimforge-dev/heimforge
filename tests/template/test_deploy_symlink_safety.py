"""Regression tests for the deployment-write symlink issue: an existing
destination DLL pathname that is a symlink must never be followed by
`scripts/deploy.py`. Every test deploys into a disposable clone of a fully
generated and validated temp project with fake build artifacts, never the
live `template/` tree.

Manifest-based stale-ownership coverage lives in test_deploy_manifest.py.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures._helpers import DeployFixtureTestCase, import_deploy_from, run_deploy


class ExternalSymlinkVictimTests(DeployFixtureTestCase):
    def test_existing_destination_symlink_is_replaced_not_followed(self):
        dest_dir = self._dest_dir()
        victim_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-deploy-victim-"))
        victim = victim_dir / "victim.txt"
        victim.write_bytes(b"SENTINEL-DO-NOT-TOUCH")
        os.chmod(victim, 0o640)
        victim_mode_before = victim.stat().st_mode

        dll_name = f"{self.common}.dll"
        os.symlink(victim, dest_dir / dll_name)

        result = run_deploy(self.output_dir, "server", dest_dir)
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


class ExistingRegularDllTests(DeployFixtureTestCase):
    def test_existing_regular_dll_is_replaced_on_redeploy(self):
        dest_dir = self._dest_dir()
        dll_name = f"{self.common}.dll"
        (dest_dir / dll_name).write_bytes(b"OLD STALE BYTES")

        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)

        deployed = dest_dir / dll_name
        self.assertTrue(deployed.is_file())
        self.assertFalse(deployed.is_symlink())
        self.assertEqual(self.artifact_bytes[self.common], deployed.read_bytes())


class DestinationAbsentTests(DeployFixtureTestCase):
    def test_first_deployment_with_absent_destination_succeeds(self):
        dest_dir = self._dest_dir() / "plugins"
        self.assertFalse(dest_dir.exists())

        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)
        for project in self.server_modules:
            self.assertEqual(self.artifact_bytes[project], (dest_dir / f"{project}.dll").read_bytes())


class NonRegularFinalTargetTests(DeployFixtureTestCase):
    def test_existing_directory_target_fails_safely(self):
        dest_dir = self._dest_dir()
        dll_name = f"{self.common}.dll"
        (dest_dir / dll_name).mkdir()

        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)
        self.assertTrue((dest_dir / dll_name).is_dir())
        self.assertEqual([dll_name], os.listdir(dest_dir))

    def test_existing_fifo_target_fails_safely(self):
        dest_dir = self._dest_dir()
        dll_name = f"{self.common}.dll"
        os.mkfifo(dest_dir / dll_name)

        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)
        self.assertTrue(stat.S_ISFIFO((dest_dir / dll_name).lstat().st_mode))
        self.assertEqual([dll_name], os.listdir(dest_dir))


class StagingCopyFailureTests(DeployFixtureTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.deploy = import_deploy_from(self.output_dir / "scripts")

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
        # no stray temporary file left behind, and no manifest was ever written
        self.assertEqual([dll_name], os.listdir(dest_dir))


if __name__ == "__main__":
    unittest.main()
