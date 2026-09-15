"""Regression tests for deployment stale-cleanup ownership: `scripts/deploy.py`
must delete only entries this suite previously recorded, via its own
deployment manifest, as its own deployed outputs. A filename sharing the
suite's namespace prefix must never be treated as owned by that fact alone.

Every test deploys into a disposable clone of a fully generated and validated
temp project with fake build artifacts, never the live `template/` tree.
Symlinked-*destination-DLL* write safety is covered in
test_deploy_symlink_safety.py; this file covers ownership tracking
(the deployment manifest) and destination-directory policy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from bootstrap.validate_generated import NO_BYTECODE_ENV
from tests.fixtures._helpers import DeployFixtureTestCase, import_deploy_from, run_deploy, write_dev_json


class OriginalPrefixDeletionRegressionTests(DeployFixtureTestCase):
    """Exact reproduction of the reported issue: a destination containing an
    unrelated `Auditheim.ThirdParty.dll` that merely shares the suite's
    namespace prefix must never be deleted by cleanup -- prefix alone must
    never grant ownership."""

    generate_overrides = {
        "suite_name": "Auditheim",
        "root_namespace": "Auditheim",
        "plugin_guid_root": "org.example-tests.auditheim",
    }

    def test_auditheim_third_party_dll_survives_deployment(self):
        dest_dir = self._dest_dir()
        victim = dest_dir / "Auditheim.ThirdParty.dll"
        victim_bytes = b"THIRD-PARTY-UNRELATED-BYTES"
        victim.write_bytes(victim_bytes)

        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual(victim_bytes, victim.read_bytes())

    def test_auditheim_third_party_dll_survives_redeploy_too(self):
        """Not just the first deploy -- the manifest never claims ownership
        of a file it never deployed, so a second deployment to the same
        destination still leaves it alone."""
        dest_dir = self._dest_dir()
        victim = dest_dir / "Auditheim.ThirdParty.dll"
        victim_bytes = b"THIRD-PARTY-UNRELATED-BYTES"
        victim.write_bytes(victim_bytes)

        run_deploy(self.output_dir, "server", dest_dir)
        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual(victim_bytes, victim.read_bytes())


class FirstDeployWithoutManifestTests(DeployFixtureTestCase):
    def test_unrelated_prefix_matching_dll_survives_first_deploy(self):
        dest_dir = self._dest_dir()
        prefix = f"{self.cfg['rootNamespace']}."
        unrelated = dest_dir / f"{prefix}OldModule.dll"
        unrelated.write_bytes(b"PRE-EXISTING-UNRELATED")

        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual(b"PRE-EXISTING-UNRELATED", unrelated.read_bytes())

    def test_manifest_records_exact_deployed_set_on_first_deploy(self):
        dest_dir = self._dest_dir()
        deploy = import_deploy_from(self.output_dir / "scripts")

        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)

        manifest = json.loads((dest_dir / deploy.manifest_name(self.cfg)).read_text())
        self.assertEqual(1, manifest["version"])
        self.assertEqual(sorted(f"{m}.dll" for m in self.server_modules), sorted(manifest["files"]))


class ManifestEvolutionTests(DeployFixtureTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.deploy = import_deploy_from(self.output_dir / "scripts")
        self.dest_dir = self._dest_dir()
        self.other_dll = self.dest_dir / "Other.Unrelated.dll"
        self.other_dll.write_bytes(b"UNRELATED")
        self.server_core = self.cfg["packages"]["serverModules"][0]
        self.shared_diag = self.cfg["packages"]["optionalClientModules"][0]

    def _deploy_with_modules(self, modules: list[str]) -> int:
        argv = ["deploy.py", "--target", "server", "--configuration", "Debug", "--destination", str(self.dest_dir)]
        with mock.patch.object(self.deploy, "modules_for", return_value=modules), mock.patch.object(sys, "argv", argv):
            return self.deploy.main()

    def _manifest_files(self) -> list[str]:
        manifest_path = self.dest_dir / self.deploy.manifest_name(self.cfg)
        return json.loads(manifest_path.read_text())["files"]

    def test_first_deploy_no_manifest_records_desired_set_and_keeps_unrelated_dll(self):
        rc = self._deploy_with_modules([self.common, self.server_core])
        self.assertEqual(0, rc)
        self.assertTrue((self.dest_dir / f"{self.common}.dll").exists())
        self.assertTrue((self.dest_dir / f"{self.server_core}.dll").exists())
        self.assertEqual(b"UNRELATED", self.other_dll.read_bytes())
        self.assertEqual(sorted([f"{self.common}.dll", f"{self.server_core}.dll"]), sorted(self._manifest_files()))

    def test_module_removed_becomes_stale_and_is_removed(self):
        self._deploy_with_modules([self.common, self.server_core])
        rc = self._deploy_with_modules([self.common])
        self.assertEqual(0, rc)
        self.assertFalse((self.dest_dir / f"{self.server_core}.dll").exists())
        self.assertTrue((self.dest_dir / f"{self.common}.dll").exists())
        self.assertEqual(b"UNRELATED", self.other_dll.read_bytes())
        self.assertEqual([f"{self.common}.dll"], self._manifest_files())

    def test_newly_added_module_deployed_without_unrelated_deletion(self):
        self._deploy_with_modules([self.common])
        rc = self._deploy_with_modules([self.common, self.shared_diag])
        self.assertEqual(0, rc)
        self.assertTrue((self.dest_dir / f"{self.common}.dll").exists())
        self.assertTrue((self.dest_dir / f"{self.shared_diag}.dll").exists())
        self.assertEqual(b"UNRELATED", self.other_dll.read_bytes())
        self.assertEqual(sorted([f"{self.common}.dll", f"{self.shared_diag}.dll"]), sorted(self._manifest_files()))


class StaleSymlinkEntryTests(DeployFixtureTestCase):
    def test_stale_manifest_entry_that_is_now_a_symlink_is_unlinked_not_followed(self):
        dest_dir = self._dest_dir()
        deploy = import_deploy_from(self.output_dir / "scripts")

        r1 = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, r1.returncode, r1.stdout)

        server_core = self.cfg["packages"]["serverModules"][0]
        server_core_dll = dest_dir / f"{server_core}.dll"

        victim_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-deploy-victim-"))
        victim = victim_dir / "victim.dll"
        victim.write_bytes(b"SENTINEL-DO-NOT-TOUCH")
        server_core_dll.unlink()
        os.symlink(victim, server_core_dll)

        argv = ["deploy.py", "--target", "server", "--configuration", "Debug", "--destination", str(dest_dir)]
        with mock.patch.object(deploy, "modules_for", return_value=[self.common]), mock.patch.object(sys, "argv", argv):
            rc = deploy.main()

        self.assertEqual(0, rc)
        self.assertFalse(server_core_dll.is_symlink())
        self.assertFalse(os.path.lexists(server_core_dll))
        self.assertEqual(b"SENTINEL-DO-NOT-TOUCH", victim.read_bytes())


class MalformedManifestTests(DeployFixtureTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.deploy = import_deploy_from(self.output_dir / "scripts")

    def _seed_manifest(self, dest_dir: Path, text: str) -> None:
        (dest_dir / self.deploy.manifest_name(self.cfg)).write_text(text, encoding="utf-8")

    def _assert_rejected(self, dest_dir: Path) -> None:
        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)
        # a malformed manifest aborts before any DLL is deployed
        self.assertFalse(any(name.endswith(".dll") for name in os.listdir(dest_dir)))

    def test_invalid_json_rejected(self):
        dest_dir = self._dest_dir()
        self._seed_manifest(dest_dir, "{not valid json")
        self._assert_rejected(dest_dir)

    def test_wrong_version_rejected(self):
        dest_dir = self._dest_dir()
        self._seed_manifest(dest_dir, json.dumps({"version": 2, "files": []}))
        self._assert_rejected(dest_dir)

    def test_missing_version_rejected(self):
        dest_dir = self._dest_dir()
        self._seed_manifest(dest_dir, json.dumps({"files": []}))
        self._assert_rejected(dest_dir)

    def test_non_list_files_rejected(self):
        dest_dir = self._dest_dir()
        self._seed_manifest(dest_dir, json.dumps({"version": 1, "files": "Common.dll"}))
        self._assert_rejected(dest_dir)

    def test_non_string_entry_rejected(self):
        dest_dir = self._dest_dir()
        self._seed_manifest(dest_dir, json.dumps({"version": 1, "files": [1, 2]}))
        self._assert_rejected(dest_dir)

    def test_duplicate_entries_rejected(self):
        dest_dir = self._dest_dir()
        self._seed_manifest(dest_dir, json.dumps({"version": 1, "files": ["Common.dll", "Common.dll"]}))
        self._assert_rejected(dest_dir)

    def test_unsafe_filename_components_rejected(self):
        for bad in ("../escape.dll", "sub/dir.dll", "..", ".", "bad\x00name.dll", "/etc/absolute.dll", "back\\slash.dll"):
            with self.subTest(bad=bad):
                dest_dir = self._dest_dir()
                self._seed_manifest(dest_dir, json.dumps({"version": 1, "files": [bad]}))
                self._assert_rejected(dest_dir)

    def test_directory_in_place_of_manifest_rejected(self):
        dest_dir = self._dest_dir()
        (dest_dir / self.deploy.manifest_name(self.cfg)).mkdir()
        self._assert_rejected(dest_dir)

    def test_fifo_in_place_of_manifest_rejected(self):
        dest_dir = self._dest_dir()
        os.mkfifo(dest_dir / self.deploy.manifest_name(self.cfg))
        self._assert_rejected(dest_dir)


class ManifestSymlinkSafetyTests(DeployFixtureTestCase):
    def test_manifest_symlink_rejected_without_touching_external_target(self):
        dest_dir = self._dest_dir()
        deploy = import_deploy_from(self.output_dir / "scripts")
        manifest_filename = deploy.manifest_name(self.cfg)

        victim_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-deploy-victim-"))
        victim = victim_dir / "external-manifest.json"
        original = json.dumps({"version": 1, "files": ["should-not-be-read.dll"]})
        victim.write_text(original, encoding="utf-8")
        os.symlink(victim, dest_dir / manifest_filename)

        result = run_deploy(self.output_dir, "server", dest_dir)

        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)
        self.assertEqual(original, victim.read_text(encoding="utf-8"))
        self.assertTrue((dest_dir / manifest_filename).is_symlink())
        self.assertFalse(any(name.endswith(".dll") for name in os.listdir(dest_dir)))


class FailedDeploymentManifestTests(DeployFixtureTestCase):
    def test_failed_copy_does_not_advance_manifest_or_remove_stale(self):
        dest_dir = self._dest_dir()
        deploy = import_deploy_from(self.output_dir / "scripts")
        server_core = self.cfg["packages"]["serverModules"][0]

        argv1 = ["deploy.py", "--target", "server", "--configuration", "Debug", "--destination", str(dest_dir)]
        with mock.patch.object(deploy, "modules_for", return_value=[self.common, server_core]), mock.patch.object(sys, "argv", argv1):
            rc1 = deploy.main()
        self.assertEqual(0, rc1)

        manifest_path = dest_dir / deploy.manifest_name(self.cfg)
        manifest_before = manifest_path.read_bytes()

        def _boom(_src, _dst):
            raise OSError("simulated write failure")

        argv2 = ["deploy.py", "--target", "server", "--configuration", "Debug", "--destination", str(dest_dir)]
        with mock.patch.object(deploy, "modules_for", return_value=[self.common]), \
             mock.patch.object(deploy.shutil, "copyfileobj", side_effect=_boom), \
             mock.patch.object(sys, "argv", argv2):
            rc2 = deploy.main()

        self.assertEqual(2, rc2)
        # the manifest still describes the last successful deployment
        self.assertEqual(manifest_before, manifest_path.read_bytes())
        # ServerCore was never removed as stale, since the redeploy never completed
        self.assertTrue((dest_dir / f"{server_core}.dll").exists())


class ClientServerIndependenceTests(DeployFixtureTestCase):
    def test_server_and_client_manifests_are_independent(self):
        server_dest = self._dest_dir()
        client_dest = self._dest_dir()

        r1 = run_deploy(self.output_dir, "server", server_dest)
        self.assertEqual(0, r1.returncode, r1.stdout)
        r2 = run_deploy(self.output_dir, "client", client_dest)
        self.assertEqual(0, r2.returncode, r2.stdout)

        deploy = import_deploy_from(self.output_dir / "scripts")
        manifest_filename = deploy.manifest_name(self.cfg)
        server_files = json.loads((server_dest / manifest_filename).read_text())["files"]
        client_files = json.loads((client_dest / manifest_filename).read_text())["files"]

        expected_server = sorted(f"{m}.dll" for m in deploy.modules_for(self.cfg, "server"))
        expected_client = sorted(f"{m}.dll" for m in deploy.modules_for(self.cfg, "client"))

        self.assertEqual(expected_server, sorted(server_files))
        self.assertEqual(expected_client, sorted(client_files))
        self.assertNotEqual(sorted(server_files), sorted(client_files))


class DestinationPolicyTests(DeployFixtureTestCase):
    def test_bare_bepinex_plugins_root_destination_rejected(self):
        parent = self._dest_dir()
        bepinex_plugins = parent / "BepInEx" / "plugins"
        bepinex_plugins.mkdir(parents=True)

        result = run_deploy(self.output_dir, "server", bepinex_plugins)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)
        self.assertEqual([], os.listdir(bepinex_plugins))

    def test_suite_specific_subdirectory_under_bepinex_plugins_allowed(self):
        parent = self._dest_dir()
        suite_dir = parent / "BepInEx" / "plugins" / self.cfg["suiteName"]

        result = run_deploy(self.output_dir, "server", suite_dir)
        self.assertEqual(0, result.returncode, result.stdout)
        for module in self.server_modules:
            self.assertTrue((suite_dir / f"{module}.dll").exists())


class SameDestinationRejectionTests(DeployFixtureTestCase):
    """Item 2: client and server plugin directories must never resolve to
    the same effective directory -- otherwise one role's deploy treats the
    other role's DLLs as stale and deletes them."""

    def test_exact_same_configured_path_rejected(self):
        shared = self._dest_dir()
        write_dev_json(self.output_dir, client_plugin_dir=str(shared), server_plugin_dir=str(shared))

        result = run_deploy(self.output_dir, "server")
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)
        self.assertEqual([], os.listdir(shared))

    def test_syntactically_different_paths_resolving_to_same_directory_rejected(self):
        shared = self._dest_dir()
        write_dev_json(
            self.output_dir,
            client_plugin_dir=str(shared),
            server_plugin_dir=str(shared / "sub" / ".."),
        )

        result = run_deploy(self.output_dir, "client")
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)

    def test_symlink_alias_of_configured_destination_rejected(self):
        real_dir = self._dest_dir()
        alias = self._dest_dir() / "alias"
        os.symlink(real_dir, alias)
        write_dev_json(self.output_dir, client_plugin_dir=str(real_dir), server_plugin_dir=str(alias))

        result = run_deploy(self.output_dir, "server")
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)

    def test_explicit_destination_override_colliding_with_other_role_rejected(self):
        shared = self._dest_dir()
        write_dev_json(self.output_dir, server_plugin_dir=str(shared))

        result = run_deploy(self.output_dir, "client", shared)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)
        self.assertEqual([], os.listdir(shared))

    def test_distinct_client_and_server_directories_remain_valid(self):
        client_dir = self._dest_dir()
        server_dir = self._dest_dir()
        write_dev_json(self.output_dir, client_plugin_dir=str(client_dir), server_plugin_dir=str(server_dir))

        result = run_deploy(self.output_dir, "server")
        self.assertEqual(0, result.returncode, result.stdout)
        for module in self.server_modules:
            self.assertTrue((server_dir / f"{module}.dll").exists())


class PartialStaleRemovalFailureTests(DeployFixtureTestCase):
    """Item 1/6: the new desired-ownership manifest is published before
    stale cleanup starts, so a stale removal that fails partway through
    never leaves the manifest still authorizing deletion of a filename
    whose suite-owned entry may already be gone."""

    def test_partial_stale_removal_failure_does_not_leave_stale_authorization(self):
        dest_dir = self._dest_dir()
        deploy = import_deploy_from(self.output_dir / "scripts")
        manifest_filename = deploy.manifest_name(self.cfg)

        # old manifest owns Common, ServerCore, Shared.Diagnostics
        r1 = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, r1.returncode, r1.stdout)

        server_core = self.cfg["packages"]["serverModules"][0]
        shared_diag = self.cfg["packages"]["serverModules"][1]
        server_core_dll = f"{server_core}.dll"
        shared_diag_dll = f"{shared_diag}.dll"

        real_unlink = os.unlink

        def _boom_unlink(path, *args, **kwargs):
            if path == shared_diag_dll:
                raise OSError("simulated stale-removal failure")
            return real_unlink(path, *args, **kwargs)

        argv = ["deploy.py", "--target", "server", "--configuration", "Debug", "--destination", str(dest_dir)]
        with mock.patch.object(deploy, "modules_for", return_value=[self.common]), \
             mock.patch.object(deploy.os, "unlink", side_effect=_boom_unlink), \
             mock.patch.object(sys, "argv", argv):
            rc = deploy.main()

        # ServerCore (sorts first) was removed; Shared.Diagnostics removal
        # failed and the run reports failure
        self.assertEqual(2, rc)
        self.assertFalse((dest_dir / server_core_dll).exists())
        self.assertTrue((dest_dir / shared_diag_dll).exists())

        # the manifest was already published with the new desired set
        # BEFORE stale cleanup started, so it now owns only Common -- it no
        # longer authorizes deleting ServerCore or Shared.Diagnostics
        manifest = json.loads((dest_dir / manifest_filename).read_text())
        self.assertEqual([f"{self.common}.dll"], manifest["files"])

        # place unrelated bytes at the orphaned Shared.Diagnostics filename
        # and retry (unpatched): the manifest no longer authorizes deleting
        # that name, so the unrelated bytes must survive
        (dest_dir / shared_diag_dll).write_bytes(b"UNRELATED-REPLACEMENT-BYTES")
        argv2 = ["deploy.py", "--target", "server", "--configuration", "Debug", "--destination", str(dest_dir)]
        with mock.patch.object(deploy, "modules_for", return_value=[self.common]), mock.patch.object(sys, "argv", argv2):
            rc2 = deploy.main()

        self.assertEqual(0, rc2)
        self.assertEqual(b"UNRELATED-REPLACEMENT-BYTES", (dest_dir / shared_diag_dll).read_bytes())
        manifest2 = json.loads((dest_dir / manifest_filename).read_text())
        self.assertEqual([f"{self.common}.dll"], manifest2["files"])


class ManifestPublicationFailureTests(DeployFixtureTestCase):
    """Item 1/6: if publishing the new manifest fails, stale cleanup must
    never run, and the old manifest must remain byte-identical."""

    def test_manifest_write_failure_happens_before_stale_deletion(self):
        dest_dir = self._dest_dir()
        deploy = import_deploy_from(self.output_dir / "scripts")
        manifest_filename = deploy.manifest_name(self.cfg)

        r1 = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, r1.returncode, r1.stdout)
        manifest_path = dest_dir / manifest_filename
        manifest_before = manifest_path.read_bytes()
        server_core = self.cfg["packages"]["serverModules"][0]
        shared_diag = self.cfg["packages"]["serverModules"][1]
        server_core_before = (dest_dir / f"{server_core}.dll").read_bytes()
        shared_diag_before = (dest_dir / f"{shared_diag}.dll").read_bytes()

        real_replace = os.replace

        def _boom_replace(src, dst, *args, **kwargs):
            if dst == manifest_filename:
                raise OSError("simulated manifest publish failure")
            return real_replace(src, dst, *args, **kwargs)

        argv = ["deploy.py", "--target", "server", "--configuration", "Debug", "--destination", str(dest_dir)]
        with mock.patch.object(deploy, "modules_for", return_value=[self.common]), \
             mock.patch.object(deploy.os, "replace", side_effect=_boom_replace), \
             mock.patch.object(sys, "argv", argv):
            rc = deploy.main()

        self.assertEqual(2, rc)
        # old manifest remains authoritative and byte-identical
        self.assertEqual(manifest_before, manifest_path.read_bytes())
        # stale entries were never touched -- cleanup never started
        self.assertEqual(server_core_before, (dest_dir / f"{server_core}.dll").read_bytes())
        self.assertEqual(shared_diag_before, (dest_dir / f"{shared_diag}.dll").read_bytes())


class ManifestVersionValidationTests(DeployFixtureTestCase):
    """Item 3: only the exact JSON integer 1 is accepted; `true`/`false`
    (`True == 1` in Python) and other numeric-ish values must be rejected."""

    def setUp(self) -> None:
        super().setUp()
        self.deploy = import_deploy_from(self.output_dir / "scripts")

    def _assert_version_rejected(self, version) -> None:
        dest_dir = self._dest_dir()
        (dest_dir / self.deploy.manifest_name(self.cfg)).write_text(
            json.dumps({"version": version, "files": []}), encoding="utf-8"
        )
        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("deploy error", result.stdout)

    def test_version_true_rejected(self):
        self._assert_version_rejected(True)

    def test_version_false_rejected(self):
        self._assert_version_rejected(False)

    def test_version_float_rejected(self):
        self._assert_version_rejected(1.0)

    def test_version_string_rejected(self):
        self._assert_version_rejected("1")

    def test_version_null_rejected(self):
        self._assert_version_rejected(None)

    def test_version_exact_int_one_accepted(self):
        dest_dir = self._dest_dir()
        (dest_dir / self.deploy.manifest_name(self.cfg)).write_text(
            json.dumps({"version": 1, "files": []}), encoding="utf-8"
        )
        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)


class ManifestEntryPortableNameValidationTests(DeployFixtureTestCase):
    """Item 4: manifest entries must go through the complete portable
    single-component contract (`validate_path_component`), not just the
    bare charset regex -- including reserved Windows device names."""

    def setUp(self) -> None:
        super().setUp()
        self.deploy = import_deploy_from(self.output_dir / "scripts")

    def test_reserved_device_name_entries_rejected(self):
        for bad in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT1", "con.dll", "Nul.DLL"):
            with self.subTest(bad=bad):
                dest_dir = self._dest_dir()
                (dest_dir / self.deploy.manifest_name(self.cfg)).write_text(
                    json.dumps({"version": 1, "files": [bad]}), encoding="utf-8"
                )
                result = run_deploy(self.output_dir, "server", dest_dir)
                self.assertEqual(2, result.returncode, result.stdout)
                self.assertIn("deploy error", result.stdout)


class SuiteNameManifestBoundaryTests(DeployFixtureTestCase):
    """Item 5: a suite name at the accepted maximum must deploy and write
    its manifest with no raw ENAMETOOLONG -- the bounded, name-independent
    temp-file pattern must never embed the (possibly long) final name."""

    generate_overrides = {"suite_name": "S" * 233}

    def test_manifest_write_succeeds_at_max_suite_name_length(self):
        deploy = import_deploy_from(self.output_dir / "scripts")
        manifest_filename = deploy.manifest_name(self.cfg)
        self.assertEqual(255, len(manifest_filename))

        dest_dir = self._dest_dir()
        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertNotIn("ENAMETOOLONG", result.stdout)
        self.assertTrue((dest_dir / manifest_filename).is_file())


class ManifestDirectoryFsyncOrderingTests(DeployFixtureTestCase):
    """Item 1: after the manifest rename, `write_manifest` must fsync the
    destination directory before `main()` begins stale cleanup -- a file
    fsync alone does not durably commit a directory-entry replacement."""

    def setUp(self) -> None:
        super().setUp()
        self.deploy = import_deploy_from(self.output_dir / "scripts")

    def test_directory_fsync_happens_after_manifest_replace_and_before_stale_deletion(self):
        dest_dir = self._dest_dir()
        r1 = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, r1.returncode, r1.stdout)
        manifest_filename = self.deploy.manifest_name(self.cfg)

        events: list[str] = []
        dir_fd_holder: dict[str, int] = {}
        real_open_dir = self.deploy.open_deployment_dir
        real_fsync = os.fsync
        real_replace = os.replace
        real_unlink = os.unlink

        def _open_dir(destination):
            fd = real_open_dir(destination)
            dir_fd_holder["dir_fd"] = fd
            return fd

        def _fsync(fd):
            events.append("dir_fsync" if fd == dir_fd_holder.get("dir_fd") else "file_fsync")
            return real_fsync(fd)

        def _replace(src, dst, *args, **kwargs):
            if dst == manifest_filename:
                events.append("manifest_replace")
            return real_replace(src, dst, *args, **kwargs)

        def _unlink(path, *args, **kwargs):
            if kwargs.get("dir_fd") == dir_fd_holder.get("dir_fd"):
                events.append(f"unlink:{path}")
            return real_unlink(path, *args, **kwargs)

        argv = ["deploy.py", "--target", "server", "--configuration", "Debug", "--destination", str(dest_dir)]
        with mock.patch.object(self.deploy, "modules_for", return_value=[self.common]), \
             mock.patch.object(self.deploy, "open_deployment_dir", side_effect=_open_dir), \
             mock.patch.object(self.deploy.os, "fsync", side_effect=_fsync), \
             mock.patch.object(self.deploy.os, "replace", side_effect=_replace), \
             mock.patch.object(self.deploy.os, "unlink", side_effect=_unlink), \
             mock.patch.object(sys, "argv", argv):
            rc = self.deploy.main()

        self.assertEqual(0, rc)
        replace_index = events.index("manifest_replace")
        dir_fsync_indices = [i for i, e in enumerate(events) if e == "dir_fsync"]
        unlink_indices = [i for i, e in enumerate(events) if e.startswith("unlink:")]
        self.assertTrue(dir_fsync_indices, f"no directory fsync observed: {events}")
        self.assertTrue(unlink_indices, f"no stale unlink observed: {events}")
        self.assertGreater(dir_fsync_indices[0], replace_index, events)
        self.assertGreater(min(unlink_indices), dir_fsync_indices[0], events)


class ManifestDirectoryFsyncFailureTests(DeployFixtureTestCase):
    """Item 1: a directory-fsync failure must raise a controlled
    `DeployError` and stale cleanup must never run."""

    def test_directory_fsync_failure_prevents_stale_deletion(self):
        dest_dir = self._dest_dir()
        deploy = import_deploy_from(self.output_dir / "scripts")
        server_core = self.cfg["packages"]["serverModules"][0]

        r1 = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, r1.returncode, r1.stdout)
        server_core_before = (dest_dir / f"{server_core}.dll").read_bytes()

        dir_fd_holder: dict[str, int] = {}
        real_open_dir = deploy.open_deployment_dir
        real_fsync = os.fsync
        unlink_calls: list[str] = []
        real_unlink = os.unlink

        def _open_dir(destination):
            fd = real_open_dir(destination)
            dir_fd_holder["dir_fd"] = fd
            return fd

        def _boom_fsync(fd):
            if fd == dir_fd_holder.get("dir_fd"):
                raise OSError("simulated directory fsync failure")
            return real_fsync(fd)

        def _unlink(path, *args, **kwargs):
            if kwargs.get("dir_fd") == dir_fd_holder.get("dir_fd"):
                unlink_calls.append(path)
            return real_unlink(path, *args, **kwargs)

        argv = ["deploy.py", "--target", "server", "--configuration", "Debug", "--destination", str(dest_dir)]
        with mock.patch.object(deploy, "modules_for", return_value=[self.common]), \
             mock.patch.object(deploy, "open_deployment_dir", side_effect=_open_dir), \
             mock.patch.object(deploy.os, "fsync", side_effect=_boom_fsync), \
             mock.patch.object(deploy.os, "unlink", side_effect=_unlink), \
             mock.patch.object(sys, "argv", argv):
            rc = deploy.main()

        self.assertEqual(2, rc)
        self.assertEqual([], unlink_calls)
        self.assertEqual(server_core_before, (dest_dir / f"{server_core}.dll").read_bytes())


class NoChildLockArtifactTests(DeployFixtureTestCase):
    """Item 11: locking is now purely `flock()` on the retained destination
    directory FD -- no child lock pathname is created, validated, or
    reused, so a deployment's output is exactly its DLLs plus the
    manifest."""

    def test_no_lock_file_artifact_created(self):
        dest_dir = self._dest_dir()
        deploy = import_deploy_from(self.output_dir / "scripts")
        result = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, result.returncode, result.stdout)
        expected = {f"{m}.dll" for m in self.server_modules} | {deploy.manifest_name(self.cfg)}
        self.assertEqual(expected, set(os.listdir(dest_dir)))


class LockReleaseOnExceptionTests(DeployFixtureTestCase):
    """Item 3/12: an exception anywhere in the ownership transaction must
    still release the directory flock. Proven by immediately reusing the
    same destination for a second, real `deploy.main()` call within the
    same process: `flock` is per open-file-description, not per-process,
    so the second call's freshly opened directory fd would deadlock on
    its own `LOCK_EX` if the first call's `finally` never ran `LOCK_UN`."""

    def test_exception_during_transaction_releases_directory_lock(self):
        dest_dir = self._dest_dir()
        deploy = import_deploy_from(self.output_dir / "scripts")

        def _boom(_src, _dst):
            raise OSError("simulated failure")

        argv = ["deploy.py", "--target", "server", "--configuration", "Debug", "--destination", str(dest_dir)]
        with mock.patch.object(deploy.shutil, "copyfileobj", side_effect=_boom), mock.patch.object(sys, "argv", argv):
            rc1 = deploy.main()
        self.assertEqual(2, rc1)

        with mock.patch.object(sys, "argv", argv):
            rc2 = deploy.main()
        self.assertEqual(0, rc2)


_LOCK_HARNESS = r"""
import sys, os, time, json, fcntl
sys.path.insert(0, "scripts")
import deploy

acquired_path, release_path, modules_json, dest, target = sys.argv[1:6]
modules = json.loads(modules_json)

_real_flock = deploy.fcntl.flock

def _paced_flock(fd, operation):
    _real_flock(fd, operation)
    if operation == fcntl.LOCK_EX:
        with open(acquired_path, "w") as f:
            f.write("1")
        while not os.path.exists(release_path):
            time.sleep(0.02)

deploy.fcntl.flock = _paced_flock
deploy.modules_for = lambda cfg, tgt: modules

sys.argv = ["deploy.py", "--target", target, "--configuration", "Debug", "--destination", dest]
sys.exit(deploy.main())
"""


def _poll_until(predicate, timeout: float, interval: float = 0.02) -> bool:
    """Poll `predicate` until it returns truthy or `timeout` elapses. Used
    only to *detect* an already-deterministic outcome (a sentinel file a
    harness process writes at a specific point) -- never to *sequence* it;
    ordering is always driven by the sentinel files themselves."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _spawn_lock_harness(cwd, dest_path, acquired, release, modules, target="server"):
    proc = subprocess.Popen(
        [sys.executable, "-c", _LOCK_HARNESS, str(acquired), str(release), json.dumps(modules), str(dest_path), target],
        cwd=cwd,
        env=NO_BYTECODE_ENV,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc


class DeploymentLockConcurrencyTests(DeployFixtureTestCase):
    """Items 2/3/6: two real `deploy.py` processes targeting the same
    destination must serialize through `flock()` on the retained
    destination directory FD itself -- there is no separate lock pathname
    to open. The lock behavior here is real (independent OS processes and
    a real `flock`), never mocked away."""

    def _spawn(self, dest_dir, acquired, release, modules, target="server"):
        proc = _spawn_lock_harness(self.output_dir, dest_dir, acquired, release, modules, target)
        self.addCleanup(proc.stdout.close)
        return proc

    def test_second_deployment_blocks_until_first_releases_and_sees_current_manifest(self):
        dest_dir = self._dest_dir()
        # old manifest owns Common, ServerCore, Shared.Diagnostics
        r1 = run_deploy(self.output_dir, "server", dest_dir)
        self.assertEqual(0, r1.returncode, r1.stdout)
        server_core = self.cfg["packages"]["serverModules"][0]

        work = Path(tempfile.mkdtemp(prefix="valheimsuite-deploy-lock-"))
        a_acquired, a_release = work / "a.acquired", work / "a.release"
        b_acquired, b_release = work / "b.acquired", work / "b.release"
        b_release.write_text("1")  # B never needs pacing once it holds the lock

        proc_a = self._spawn(dest_dir, a_acquired, a_release, [self.common])
        self.addCleanup(proc_a.wait, timeout=10)
        self.assertTrue(_poll_until(a_acquired.exists, timeout=10), "A never acquired the lock")

        proc_b = self._spawn(dest_dir, b_acquired, b_release, [self.common])
        self.addCleanup(proc_b.wait, timeout=10)
        # B must not obtain its ownership snapshot while A still holds the lock --
        # A is paced right after LOCK_EX and does not release until the test
        # tells it to, so this also proves B stays blocked through A's entire
        # remaining transaction (deploy, manifest publish, directory fsync,
        # stale cleanup) once released, since A's own LOCK_UN only runs at
        # the very end of that transaction
        self.assertFalse(_poll_until(b_acquired.exists, timeout=1), "B acquired the lock while A still held it")

        a_release.write_text("1")
        self.assertEqual(0, proc_a.wait(timeout=10), proc_a.stdout.read())

        # an unrelated file appears at the just-vacated stale name, exactly
        # in the window after A relinquishes ownership and before B runs
        (dest_dir / f"{server_core}.dll").write_bytes(b"UNRELATED-REPLACEMENT-BYTES")

        self.assertTrue(_poll_until(b_acquired.exists, timeout=10), "B never acquired the lock after A released")
        self.assertEqual(0, proc_b.wait(timeout=10), proc_b.stdout.read())

        # B loaded the CURRENT manifest (already published by A, owning
        # only Common) -- it never authorizes deleting ServerCore, so the
        # unrelated replacement bytes survive
        self.assertEqual(b"UNRELATED-REPLACEMENT-BYTES", (dest_dir / f"{server_core}.dll").read_bytes())
        deploy = import_deploy_from(self.output_dir / "scripts")
        manifest = json.loads((dest_dir / deploy.manifest_name(self.cfg)).read_text())
        self.assertEqual([f"{self.common}.dll"], manifest["files"])

    def test_different_destinations_do_not_block_each_other(self):
        dest_a = self._dest_dir()
        dest_b = self._dest_dir()
        r1 = run_deploy(self.output_dir, "server", dest_a)
        self.assertEqual(0, r1.returncode, r1.stdout)
        r2 = run_deploy(self.output_dir, "server", dest_b)
        self.assertEqual(0, r2.returncode, r2.stdout)

        work = Path(tempfile.mkdtemp(prefix="valheimsuite-deploy-lock-"))
        a_acquired, a_release = work / "a.acquired", work / "a.release"
        b_acquired, b_release = work / "b.acquired", work / "b.release"
        b_release.write_text("1")

        proc_a = self._spawn(dest_a, a_acquired, a_release, [self.common])
        self.addCleanup(proc_a.wait, timeout=30)
        self.addCleanup(a_release.write_text, "1")
        self.assertTrue(_poll_until(a_acquired.exists, timeout=10), "A never acquired its lock")

        proc_b = self._spawn(dest_b, b_acquired, b_release, [self.common])
        self.addCleanup(proc_b.wait, timeout=30)
        self.addCleanup(proc_b.terminate)
        # A genuinely different destination inode must proceed despite A's hold.
        # Hosted CI can have materially slower process scheduling than the local
        # WSL development environment, so this budget detects blocking without
        # treating ordinary runner startup latency as lock contention.
        self.assertTrue(_poll_until(b_acquired.exists, timeout=15), "B blocked on an unrelated destination's lock")
        self.assertEqual(0, proc_b.wait(timeout=30), proc_b.stdout.read())

        a_release.write_text("1")
        self.assertEqual(0, proc_a.wait(timeout=30), proc_a.stdout.read())


class DestinationAliasSerializationTests(DeployFixtureTestCase):
    """Item 4: two deployments reaching the *same* directory inode through
    different pathname spellings (`..`-normalized or a symlink) must still
    contend on one `flock`. `safe_destination()` always resolves to the
    real path (`resolve(strict=False)`) before `open_deployment_dir()`
    opens it, so aliasing is already folded away before the lock is ever
    taken -- no extra alias-detection code is needed."""

    def _assert_aliases_serialize(self, canonical_dest, alias_dest):
        r1 = run_deploy(self.output_dir, "server", canonical_dest)
        self.assertEqual(0, r1.returncode, r1.stdout)

        work = Path(tempfile.mkdtemp(prefix="valheimsuite-deploy-lock-"))
        a_acquired, a_release = work / "a.acquired", work / "a.release"
        b_acquired, b_release = work / "b.acquired", work / "b.release"
        b_release.write_text("1")

        proc_a = _spawn_lock_harness(self.output_dir, canonical_dest, a_acquired, a_release, [self.common])
        self.addCleanup(proc_a.stdout.close)
        self.addCleanup(proc_a.wait, timeout=10)
        self.assertTrue(_poll_until(a_acquired.exists, timeout=10), "A never acquired the lock")

        proc_b = _spawn_lock_harness(self.output_dir, alias_dest, b_acquired, b_release, [self.common])
        self.addCleanup(proc_b.stdout.close)
        self.addCleanup(proc_b.wait, timeout=10)
        self.assertFalse(
            _poll_until(b_acquired.exists, timeout=1), "the alias acquired the lock while the canonical path still held it"
        )

        a_release.write_text("1")
        self.assertEqual(0, proc_a.wait(timeout=10), proc_a.stdout.read())
        self.assertTrue(_poll_until(b_acquired.exists, timeout=10), "the alias never acquired the lock after release")
        self.assertEqual(0, proc_b.wait(timeout=10), proc_b.stdout.read())

    def test_dotdot_normalized_alias_serializes(self):
        dest_dir = self._dest_dir()
        alias = dest_dir / "sub" / ".."
        self._assert_aliases_serialize(dest_dir, alias)

    def test_symlink_alias_serializes(self):
        dest_dir = self._dest_dir()
        alias_parent = Path(tempfile.mkdtemp(prefix="valheimsuite-deploy-alias-"))
        alias = alias_parent / "alias"
        os.symlink(dest_dir, alias)
        self._assert_aliases_serialize(dest_dir, alias)


class DestinationPathnameRebindingTests(DeployFixtureTestCase):
    """Item 4: renaming the destination directory out from under an
    already-locked deployment, then creating a fresh directory at the old
    pathname, must not let a second deployment split or steal A's lock --
    B (targeting the old pathname) opens a genuinely different inode and
    proceeds independently, while A's already-open FD-relative operations
    stay confined to the original (now-moved) directory."""

    def test_rebinding_the_destination_pathname_does_not_split_or_redirect_the_lock(self):
        orig_dest = self._dest_dir()
        r1 = run_deploy(self.output_dir, "server", orig_dest)
        self.assertEqual(0, r1.returncode, r1.stdout)

        work = Path(tempfile.mkdtemp(prefix="valheimsuite-deploy-lock-"))
        a_acquired, a_release = work / "a.acquired", work / "a.release"

        proc_a = _spawn_lock_harness(self.output_dir, orig_dest, a_acquired, a_release, [self.common])
        self.addCleanup(proc_a.stdout.close)
        self.addCleanup(proc_a.wait, timeout=10)
        self.assertTrue(_poll_until(a_acquired.exists, timeout=10), "A never acquired the lock")

        # rename the original (locked) directory elsewhere, then create a
        # brand-new, empty directory at the old pathname
        moved_dest = orig_dest.parent / (orig_dest.name + "-moved")
        orig_dest.rename(moved_dest)
        orig_dest.mkdir()

        # B, targeting the OLD pathname, is now a genuinely different
        # (empty) directory/inode -- it must proceed without blocking on A
        b_result = run_deploy(self.output_dir, "server", orig_dest)
        self.assertEqual(0, b_result.returncode, b_result.stdout)
        for module in self.server_modules:
            self.assertTrue((orig_dest / f"{module}.dll").exists())

        # release A: its FD-relative writes land in the MOVED original
        # directory, never in the new directory sitting at the old path
        a_release.write_text("1")
        self.assertEqual(0, proc_a.wait(timeout=10), proc_a.stdout.read())
        self.assertTrue((moved_dest / f"{self.common}.dll").exists())


if __name__ == "__main__":
    unittest.main()
