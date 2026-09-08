import copy
import fcntl
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap import naming
from bootstrap.create_project import generate
from bootstrap.model import validate_params
from bootstrap.render import validate_template
from bootstrap.validate_generated import NO_BYTECODE_ENV
from tests.fixtures._helpers import (
    copy_template_to_temp, generate_into_temp, import_deploy_from, import_scripts_from,
    make_params, run_deploy, write_dev_json, write_fake_artifacts,
)
from tests.template.test_solution_membership import _add_sln_entry, _write_csproj


class ReauditContractsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.params, cls.base, result = generate_into_temp()
        if not result.ok:
            raise AssertionError(result.errors)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(self.base, self.root)
        self.metadata, self.package = import_scripts_from(self.root / "scripts")
        self.cfg = json.loads((self.root / "suite.config.json").read_text())
        self.sln = self.root / (self.cfg["rootNamespace"] + ".sln")

    def save(self):
        (self.root / "suite.config.json").write_text(json.dumps(self.cfg))

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, *args], cwd=self.root, env=NO_BYTECODE_ENV,
            text=True, capture_output=True,
        )

    def add_project(self, name, scope, tfm=None):
        tfm = tfm or ("netstandard2.0" if scope == "common" else "net48")
        self.cfg["projects"][name] = {"scope": scope, "targetFramework": tfm}
        for group in self.metadata.SCOPE_PACKAGE_GROUPS[scope]:
            self.cfg["packages"][group].append(name)
        _write_csproj(self.root, name, tfm)
        _add_sln_entry(self.root, self.cfg, name)

    @unittest.skipUnless(shutil.which("dotnet"), "dotnet unavailable for solution participation regression")
    def test_dotnet_build_skip_is_rejected_by_metadata(self):
        original = self.sln.read_text()
        projects = [
            match for line in original.splitlines()
            if (match := self.metadata.SOLUTION_PROJECT_LINE.fullmatch(line))
        ]
        for project in projects:
            path = self.root / project["path"].replace("\\", "/")
            # Real MSBuild Build targets record participation without game assemblies.
            path.write_text(
                '<Project><Target Name="Build"><WriteLinesToFile '
                'File="$(MSBuildThisFileDirectory)participated-$(Configuration)" '
                'Lines="$(MSBuildProjectName)" Overwrite="true" /></Target></Project>'
            )
        server = next(project for project in projects if project["name"] == "Sampleheim.ServerCore")
        for configuration in ("Debug", "Release"):
            mapping = f'\t\t{server["project_guid"]}.{configuration}|Any CPU.Build.0 = {configuration}|Any CPU\n'
            self.sln.write_text(original.replace(mapping, ""))
            command = ["dotnet", "msbuild", str(self.sln), "-t:Build", "-nologo", "-p:Configuration=" + configuration]
            result = subprocess.run(command, cwd=self.root, env=NO_BYTECODE_ENV, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertFalse((self.root / "src/Sampleheim.ServerCore" / ("participated-" + configuration)).exists())
            with self.assertRaises(self.metadata.MetadataError):
                self.metadata.validate_solution_membership(self.cfg)
            self.sln.write_text(original)
            self.metadata.validate_solution_membership(self.cfg)
            result = subprocess.run(command, cwd=self.root, env=NO_BYTECODE_ENV, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            for project in projects:
                marker = (self.root / project["path"].replace("\\", "/")).parent / ("participated-" + configuration)
                self.assertEqual(project["name"], marker.read_text().strip())

    def test_solution_mapping_mutations_rejected(self):
        original = self.sln.read_text()
        header = next(line for line in original.splitlines() if '"Sampleheim.ServerCore"' in line)
        guid = self.metadata.SOLUTION_PROJECT_LINE.fullmatch(header)["project_guid"]
        for cfg in ("Debug", "Release"):
            for mapping in ("ActiveCfg", "Build.0"):
                line = f"\t\t{guid}.{cfg}|Any CPU.{mapping} = {cfg}|Any CPU\n"
                for label, text in (
                    ("missing", original.replace(line, "")),
                    ("duplicate", original.replace(line, line + line)),
                    ("wrong target", original.replace(line, line.replace(f"= {cfg}|", "= Other|"))),
                    ("malformed", original.replace(line, line.replace(" = ", " : "))),
                ):
                    with self.subTest(cfg=cfg, mapping=mapping, mutation=label):
                        self.sln.write_text(text)
                        with self.assertRaises(self.metadata.MetadataError):
                            self.metadata.validate_solution_membership(self.cfg)
        for text in (
            original.replace("Debug|Any CPU = Debug|Any CPU", "Debug|x64 = Debug|x64"),
            original.replace("\tEndGlobalSection", "", 1),
            original.replace("GlobalSection(SolutionConfigurationPlatforms)", "GlobalSection(Other)"),
        ):
            self.sln.write_text(text)
            with self.assertRaises(self.metadata.MetadataError):
                self.metadata.validate_solution_membership(self.cfg)

    def test_duplicate_project_guid_rejected(self):
        text = self.sln.read_text()
        headers = [self.metadata.SOLUTION_PROJECT_LINE.fullmatch(line) for line in text.splitlines()]
        guids = [match["project_guid"] for match in headers if match]
        self.sln.write_text(text.replace(guids[1], guids[0]))
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate_solution_membership(self.cfg)

    def test_missing_server_debug_build_blocks_all_workflows_before_mutation(self):
        text = self.sln.read_text()
        guid = next(self.metadata.SOLUTION_PROJECT_LINE.fullmatch(line)["project_guid"]
                    for line in text.splitlines() if '"Sampleheim.ServerCore"' in line)
        self.sln.write_text(text.replace(f"\t\t{guid}.Debug|Any CPU.Build.0 = Debug|Any CPU\n", ""))
        write_dev_json(self.root)
        write_fake_artifacts(self.root, self.cfg, "Release")
        dest = Path(self.temp.name) / "destination"
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        for args in (
            ["scripts/suite_metadata.py", "sync"], ["scripts/suite_metadata.py", "check"],
            ["scripts/package.py", "--clean"],
            ["scripts/deploy.py", "--target", "server", "--destination", str(dest)],
        ):
            result = self.run_script(*args)
            self.assertNotEqual(0, result.returncode, args)
            self.assertNotIn("Traceback", result.stderr)
        for script in ("build.sh", "test.sh", "preflight.sh"):
            result = subprocess.run(["bash", "scripts/" + script], cwd=self.root, env=NO_BYTECODE_ENV,
                                    capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode, script)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(dest.exists())

    def test_scope_framework_contract(self):
        for project, tfm in (("Sampleheim.ServerCore", "net8.0"), ("Sampleheim.ServerCore", "net9.0"),
                             ("Sampleheim.Common", "net48")):
            with self.subTest(project=project, tfm=tfm):
                cfg = copy.deepcopy(self.cfg)
                cfg["projects"][project]["targetFramework"] = tfm
                _write_csproj(self.root, project, tfm)
                with self.assertRaises(self.metadata.MetadataError):
                    self.metadata.validate(cfg)
                _write_csproj(self.root, project, self.cfg["projects"][project]["targetFramework"])

    def test_exactly_one_common(self):
        self.add_project("Another.Common", "common")
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)
        del self.cfg["projects"]["Another.Common"]
        common = self.cfg["packages"]["commonModule"]
        del self.cfg["projects"][common]
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)
        self.cfg["packages"]["commonModule"] = "Sampleheim.ServerCore"
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)

    def test_case_colliding_projects_rejected_before_source_lookup(self):
        self.add_project("Mod", "serverOnly")
        self.add_project("mod", "serverOnly")
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)

    def test_path_only_collision_and_assembly_collision_rejected(self):
        self.add_project("Mod", "serverOnly")
        self.add_project("Distinct", "serverOnly")
        text = self.sln.read_text()
        self.sln.write_text(text.replace("src\\Distinct\\Distinct.csproj", "src\\mod\\mod.csproj"))
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate_solution_membership(self.cfg)
        self.sln.write_text(text)
        path = self.root / "src/Distinct/Distinct.csproj"
        path.write_text(path.read_text().replace("<AssemblyName>Distinct", "<AssemblyName>mod"))
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)

    def test_package_names_collide_after_dot_normalization_and_with_bundle(self):
        self.add_project("Feature.Mod", "sharedRequired")
        self.add_project("feature-mod", "sharedOptional")
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)
        self.cfg = json.loads((self.root / "suite.config.json").read_text())
        self.add_project("Sampleheim.ServerPack", "sharedOptional")
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)

    def test_custom_net48_projects_certify_package_and_deploy(self):
        for scope in ("serverOnly", "clientOnly", "sharedRequired", "sharedOptional"):
            self.add_project("Custom." + scope, scope)
        self.save()
        result = self.run_script("scripts/suite_metadata.py", "sync")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        write_dev_json(self.root)
        write_fake_artifacts(self.root, self.cfg, "Release")
        result = self.run_script("scripts/package.py")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        for side in ("server", "client"):
            dest = Path(self.temp.name) / side
            result = run_deploy(self.root, side, dest, "Release")
            self.assertEqual(0, result.returncode, result.stdout)
            deploy = import_deploy_from(self.root / "scripts")
            self.assertEqual({p + ".dll" for p in deploy.modules_for(self.cfg, side)}, {p.name for p in dest.glob("*.dll")})

    def test_stale_wrong_framework_artifact_never_deploys_or_packages(self):
        write_dev_json(self.root)
        write_fake_artifacts(self.root, self.cfg, "Release")
        project = "Sampleheim.ServerCore"
        exact = self.root / "src" / project / "bin/Release/net48" / (project + ".dll")
        stale = exact.parent.parent / "net9.0" / exact.name
        stale.parent.mkdir()
        exact.rename(stale)
        dest = Path(self.temp.name) / "destination"
        result = run_deploy(self.root, "server", dest, "Release")
        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertFalse(dest.exists())
        result = self.run_script("scripts/package.py")
        self.assertNotEqual(0, result.returncode)
        self.assertFalse((self.root / "artifacts/packages").exists())
        exact.write_bytes(b"EXACT NET48")
        result = run_deploy(self.root, "server", dest, "Release")
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual(b"EXACT NET48", (dest / exact.name).read_bytes())

    def test_package_version_byte_boundary_before_mutation(self):
        names = [name for name, _, _ in self.metadata.package_definitions(self.cfg)]
        overhead = max(len(f"{name}-.zip".encode()) for name in names)
        limit = 255 - overhead
        self.cfg["suiteVersion"] = "1.0.0+" + "a" * (limit - 6)
        self.metadata.validate(self.cfg)
        self.save()
        result = self.run_script("scripts/suite_metadata.py", "sync")
        self.assertEqual(0, result.returncode, result.stderr)
        write_fake_artifacts(self.root, self.cfg, "Release")
        result = self.run_script("scripts/package.py")
        self.assertEqual(0, result.returncode, result.stderr)
        outputs = {p.name: p.read_bytes() for p in (self.root / "artifacts/packages").iterdir()}
        self.cfg["suiteVersion"] += "a"
        self.save()
        result = self.run_script("scripts/package.py", "--clean")
        self.assertNotEqual(0, result.returncode)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(outputs, {p.name: p.read_bytes() for p in (self.root / "artifacts/packages").iterdir()})

    def test_final_directory_fsync_occurs_after_unlink_under_lock_and_failure_is_controlled(self):
        write_dev_json(self.root)
        write_fake_artifacts(self.root, self.cfg)
        deploy = import_deploy_from(self.root / "scripts")
        for fail in (False, True):
            with self.subTest(fail=fail):
                dest = Path(self.temp.name) / str(fail)
                dest.mkdir()
                stale = dest / "Old.dll"
                stale.write_bytes(b"old")
                manifest = dest / deploy.manifest_name(self.cfg)
                manifest.write_text(json.dumps({"version": 1, "files": [stale.name]}))
                events = []
                real_fsync, real_unlink, real_flock = os.fsync, os.unlink, fcntl.flock
                def fsync(fd):
                    if not stale.exists():
                        events.append("final fsync")
                        self.assertNotIn("unlock", events)
                        self.assertNotIn(stale.name, json.loads(manifest.read_text())["files"])
                        if fail:
                            raise OSError("injected post-unlink fsync failure")
                    return real_fsync(fd)
                def unlink(name, **kwargs):
                    if name == stale.name:
                        self.assertNotIn(stale.name, json.loads(manifest.read_text())["files"])
                        events.append("unlink")
                    return real_unlink(name, **kwargs)
                def flock(fd, operation):
                    if operation == fcntl.LOCK_UN:
                        events.append("unlock")
                    return real_flock(fd, operation)
                argv = ["deploy.py", "--target", "server", "--destination", str(dest)]
                with mock.patch.object(sys, "argv", argv), mock.patch.object(os, "fsync", side_effect=fsync), \
                     mock.patch.object(os, "unlink", side_effect=unlink), mock.patch.object(fcntl, "flock", side_effect=flock):
                    rc = deploy.main()
                self.assertEqual(2 if fail else 0, rc)
                self.assertEqual(["unlink", "final fsync", "unlock"], events)
                self.assertFalse(stale.exists())

    def _assert_stale_cleanup_durability(self, *, fail_unlink=None, fail_fsync=False, absent=False):
        write_dev_json(self.root)
        write_fake_artifacts(self.root, self.cfg)
        deploy = import_deploy_from(self.root / "scripts")
        dest = Path(self.temp.name) / "deployment"
        result = run_deploy(self.root, "server", dest)
        self.assertEqual(0, result.returncode, result.stdout)
        stale = sorted(f"{module}.dll" for module in self.cfg["packages"]["serverModules"])
        self.assertEqual(2, len(stale))
        unrelated = dest / "Sampleheim.ThirdParty.dll"
        unrelated.write_bytes(b"unrelated")
        manifest = dest / deploy.manifest_name(self.cfg)
        if absent:
            for name in stale:
                (dest / name).unlink()
        events = []
        removed = []
        real_unlink, real_fsync, real_flock = os.unlink, os.fsync, fcntl.flock
        probe_fd = os.open(dest, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, probe_fd)

        def assert_locked():
            try:
                real_flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            real_flock(probe_fd, fcntl.LOCK_UN)
            self.fail("deployment directory lock released before durability bookkeeping")

        def fsync(fd):
            if os.fstat(fd).st_ino == os.fstat(probe_fd).st_ino:
                assert_locked()
                events.append("post-unlink-fsync" if removed else "manifest-fsync")
                self.assertEqual([self.cfg["packages"]["commonModule"] + ".dll"],
                                 json.loads(manifest.read_text())["files"])
                if removed and fail_fsync:
                    raise OSError("injected durability failure")
            return real_fsync(fd)

        def unlink(name, **kwargs):
            if name in stale:
                assert_locked()
                events.append("unlink:" + name)
                if name == fail_unlink:
                    raise OSError("injected stale removal failure")
                real_unlink(name, **kwargs)
                removed.append(name)
                return
            return real_unlink(name, **kwargs)

        def flock(fd, operation):
            if operation == fcntl.LOCK_UN:
                assert_locked()
                events.append("unlock")
            return real_flock(fd, operation)

        stderr = io.StringIO()
        argv = ["deploy.py", "--target", "server", "--destination", str(dest)]
        with mock.patch.object(deploy, "modules_for", return_value=[self.cfg["packages"]["commonModule"]]), \
             mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stderr", stderr), \
             mock.patch.object(os, "unlink", side_effect=unlink), \
             mock.patch.object(os, "fsync", side_effect=fsync), \
             mock.patch.object(fcntl, "flock", side_effect=flock):
            rc = deploy.main()
        attempts = [] if absent else stale[:stale.index(fail_unlink) + 1] if fail_unlink else stale
        expected_removed = [name for name in attempts if name != fail_unlink]
        self.assertEqual(expected_removed, removed)
        self.assertEqual(
            ["manifest-fsync"] + ["unlink:" + name for name in attempts]
            + (["post-unlink-fsync"] if removed else []) + ["unlock"], events,
        )
        self.assertEqual(2 if fail_unlink or fail_fsync else 0, rc)
        error = stderr.getvalue()
        self.assertNotIn("Traceback", error)
        if fail_unlink:
            self.assertTrue(error.startswith(f"deploy error: cannot remove stale deployment entry {fail_unlink}:"),
                            error)
            self.assertIn("injected stale removal failure", error)
        if fail_fsync:
            self.assertIn("cannot durably commit stale deployment removals: injected durability failure", error)
        for name in stale:
            self.assertEqual(not absent and name not in removed, (dest / name).exists())
        self.assertEqual([self.cfg["packages"]["commonModule"] + ".dll"], json.loads(manifest.read_text())["files"])
        self.assertEqual(b"unrelated", unrelated.read_bytes())
        real_flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        real_flock(probe_fd, fcntl.LOCK_UN)

    def test_partial_stale_unlink_failure_still_fsyncs_before_unlock(self):
        self._assert_stale_cleanup_durability(fail_unlink="Sampleheim.Shared.Diagnostics.dll")

    def test_partial_stale_unlink_and_fsync_failure_preserves_primary_error(self):
        self._assert_stale_cleanup_durability(fail_unlink="Sampleheim.Shared.Diagnostics.dll", fail_fsync=True)

    def test_first_stale_unlink_failure_does_not_fsync_unchanged_directory(self):
        self._assert_stale_cleanup_durability(fail_unlink="Sampleheim.ServerCore.dll")

    def test_absent_stale_entries_do_not_require_extra_fsync(self):
        self._assert_stale_cleanup_durability(absent=True)

    def test_multiple_stale_unlinks_share_one_final_fsync(self):
        self._assert_stale_cleanup_durability()

    def test_multiple_stale_unlinks_then_fsync_failure_keep_new_manifest(self):
        self._assert_stale_cleanup_durability(fail_fsync=True)


class InputPurityTests(unittest.TestCase):
    def test_overlong_namespace_rejected_without_destination_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "destination"
            with self.assertRaises(naming.NamingError):
                generate(make_params(root_namespace="N" * 240), dest)
            self.assertEqual([], list(Path(temp).iterdir()))

    def test_component_limit_counts_utf8_bytes(self):
        root = copy_template_to_temp()
        self.addCleanup(shutil.rmtree, root)
        metadata, _ = import_scripts_from(root / "scripts")
        for validator, error in ((naming.validate_component_length, naming.NamingError),
                                 (metadata.validate_component_length, metadata.MetadataError)):
            validator("é" * 127 + "x", "component")
            with self.assertRaises(error):
                validator("é" * 128, "component")
        validate_params(make_params(root_namespace="N" * 194))
        with self.assertRaises(naming.NamingError):
            validate_params(make_params(root_namespace="N" * 195))

    def test_fifo_at_manifest_path_is_rejected_without_blocking(self):
        root = copy_template_to_temp()
        self.addCleanup(shutil.rmtree, root)
        (root / "README.md").unlink()
        os.mkfifo(root / "README.md")
        result = subprocess.run(
            [sys.executable, "-c",
             "from pathlib import Path; from bootstrap.render import validate_template; "
             "import sys; assert any('README.md' in e for e in validate_template(Path(sys.argv[1])))",
             str(root)],
            cwd=Path(__file__).resolve().parents[2], env=NO_BYTECODE_ENV,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_special_template_entries_rejected_without_following(self):
        root = copy_template_to_temp()
        self.addCleanup(shutil.rmtree, root)
        self.assertEqual([], validate_template(root))
        for kind in ("file", "symlink", "broken symlink", "fifo", "socket"):
            with self.subTest(kind=kind):
                entry = root / "surprise"
                sock = None
                if kind == "file":
                    entry.write_bytes(b"surprise")
                elif kind == "symlink":
                    entry.symlink_to(root / "scripts")
                elif kind == "broken symlink":
                    entry.symlink_to(root / "absent")
                elif kind == "fifo":
                    os.mkfifo(entry)
                else:
                    import socket
                    sock = socket.socket(socket.AF_UNIX)
                    sock.bind(str(entry))
                try:
                    self.assertTrue(any("surprise" in error for error in validate_template(root)))
                finally:
                    if sock:
                        sock.close()
                    entry.unlink()
