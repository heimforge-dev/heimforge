"""Regression tests for the generated-project metadata/path-containment
issue: malformed `suite.config.json` values must never cause filesystem
writes outside the generated repository or unsafe archive-member paths.

Every test that can complete a real write uses a disposable temp copy of
`template/` (`copy_template_to_temp()`) or a fully generated temp project
(`generate_into_temp()`) -- never the live `template/` tree -- so a
pre-fix reproduction run can never contaminate this repository.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from unittest import mock
import zipfile
from pathlib import Path

from bootstrap.model import ProjectParams, build_model, suite_config_dict
from tests.fixtures._helpers import copy_template_to_temp, generate_into_temp
from tests.fixtures._helpers import import_scripts_from as _import_scripts_from


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )


def _load_cfg(project_dir: Path) -> dict:
    return json.loads((project_dir / "suite.config.json").read_text(encoding="utf-8"))


def _save_cfg(project_dir: Path, cfg: dict) -> None:
    (project_dir / "suite.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _add_sln_entries(output_dir: Path, root_namespace: str, projects: list[str]) -> None:
    """Append well-formed `Project(...)"`/`EndProject` entries for
    `projects` under `src/` to the generated `<root_namespace>.sln`,
    matching bootstrap/model.py's solution_text() line shape closely
    enough for suite_metadata.py's solution parser to recognize them."""
    sln_path = output_dir / f"{root_namespace}.sln"
    lines = sln_path.read_text(encoding="utf-8").splitlines()
    insert_at = next(i for i, line in enumerate(lines) if line.strip() == "Global")
    new_lines = []
    for project in projects:
        guid = "{" + str(uuid.uuid4()).upper() + "}"
        new_lines += [
            f'Project("{{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}}") = "{project}", '
            f'"src\\{project}\\{project}.csproj", "{guid}"',
            "EndProject",
        ]
    lines[insert_at:insert_at] = new_lines
    sln_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _snapshot(paths: list[Path]) -> dict:
    return {path: (path.read_bytes() if path.is_file() else None) for path in paths}


def _replace_temp_entry(parent, temp, external: Path) -> None:
    """Simulate an attacker unlinking a securely-created temp directory
    entry and replacing it with a symlink to `external`."""
    os.unlink(temp.name, dir_fd=parent.directory_fd)
    os.symlink(external, temp.name, dir_fd=parent.directory_fd)


@contextlib.contextmanager
def _substitute_verified_temp_entries(metadata, external_by_call: dict):
    """Let `_verify_temporary_output()` run its real check on every call --
    confirming the temp entry is still exactly what the writer created --
    then substitute it immediately afterward on the specific 1-indexed
    call numbers named in `external_by_call`. A call is only counted once
    its real check has passed, so a call whose entry was already
    corrupted elsewhere (and therefore raises) never consumes a slot."""
    original = metadata._verify_temporary_output
    calls = {"count": 0}

    def substitute(parent, temp, **kwargs):
        original(parent, temp, **kwargs)
        calls["count"] += 1
        external = external_by_call.get(calls["count"])
        if external is not None:
            _replace_temp_entry(parent, temp, external)

    with mock.patch.object(metadata, "_verify_temporary_output", side_effect=substitute):
        yield


@contextlib.contextmanager
def _substitute_created_temp_entries(metadata, external_by_call: dict):
    """Substitute a temp entry immediately after `create_temp_file()`
    creates it -- before it is ever written to or verified -- on the
    named 1-indexed call numbers."""
    original = metadata.create_temp_file
    calls = {"count": 0}

    def substitute(parent, final_name, **kwargs):
        temp = original(parent, final_name, **kwargs)
        calls["count"] += 1
        external = external_by_call.get(calls["count"])
        if external is not None:
            _replace_temp_entry(parent, temp, external)
        return temp

    with mock.patch.object(metadata, "create_temp_file", side_effect=substitute):
        yield


def _inject_after_verify(metadata, external: Path):
    """One-shot: substitute only the *first* temp entry verified --
    reproducing a single race against the primary write, at the precise
    boundary between verification and the FD-relative `os.replace()`
    promotion call."""
    return _substitute_verified_temp_entries(metadata, {1: external})


@contextlib.contextmanager
def _force_primary_then_recovery_once(metadata, primary_external: Path, recovery_external: Path, *, at: str):
    """Force the primary promotion to fail by substituting its temp entry
    right after its own verification succeeds (call #1), then substitute
    the *first* recovery attempt's temp entry exactly once, at the
    requested boundary (`"creation"` -- before recovery even writes to or
    verifies it -- or `"verify"` -- immediately after recovery's own
    verification succeeds). This is one race against the primary write
    plus one race against recovery, not a sustained attacker; the bounded
    retry that follows must see an unmolested temp entry on its next
    attempt and fully restore the original output."""
    assert at in ("creation", "verify")
    verify_targets = {1: primary_external}
    create_targets: dict = {}
    if at == "verify":
        verify_targets[2] = recovery_external
    else:
        create_targets[2] = recovery_external
    with _substitute_verified_temp_entries(metadata, verify_targets), _substitute_created_temp_entries(
        metadata, create_targets
    ):
        yield


@contextlib.contextmanager
def _substitute_every_verified_temp_entry(metadata, external: Path):
    """Substitute *every* verified temp entry -- the primary write and
    every recovery attempt -- reproducing a persistent attacker who wins
    every race. Recovery must still exhaust its bounded retries and
    finish in a safe, absent state rather than installing anything of the
    attacker's."""
    original = metadata._verify_temporary_output

    def substitute(parent, temp, **kwargs):
        original(parent, temp, **kwargs)
        _replace_temp_entry(parent, temp, external)

    with mock.patch.object(metadata, "_verify_temporary_output", side_effect=substitute):
        yield


@contextlib.contextmanager
def _fail_create_temp_file_at(metadata, call_number: int, message: str = "simulated allocation failure"):
    """Make the Nth (1-indexed) call to `create_temp_file()` raise the
    writer's own controlled error instead of allocating a temp file --
    reproducing a failure that occurs *between* recovery attempts rather
    than within one."""
    original = metadata.create_temp_file
    calls = {"count": 0}

    def raise_on_call(parent, final_name, **kwargs):
        calls["count"] += 1
        if calls["count"] == call_number:
            raise kwargs["error_cls"](message)
        return original(parent, final_name, **kwargs)

    with mock.patch.object(metadata, "create_temp_file", side_effect=raise_on_call):
        yield


@contextlib.contextmanager
def _force_recovery_allocation_failure(metadata, primary_external: Path, recovery_external: Path):
    """Force the primary promotion to fail (call #1), defeat the *first*
    recovery attempt at its own verify boundary (call #2) so a mismatched
    entry is installed at `final_name`, then make the *second* recovery
    attempt's temp allocation itself raise -- reproducing a failure that
    occurs between recovery attempts, which must still leave `final_name`
    safe rather than letting the exception escape past cleanup."""
    verify_targets = {1: primary_external, 2: recovery_external}
    with _substitute_verified_temp_entries(metadata, verify_targets), _fail_create_temp_file_at(metadata, 3):
        yield


@contextlib.contextmanager
def _fail_final_cleanup_unlink(final_name: str, occurrence: int, message: str = "simulated cleanup failure"):
    """Make the Nth (1-indexed) `os.unlink()` call that targets the bare
    `final_name` fail, reproducing a filesystem that cannot confirm a safe
    final state during cleanup itself."""
    real_unlink = os.unlink
    calls = {"count": 0}

    def failing_unlink(path, *args, **kwargs):
        if path == final_name:
            calls["count"] += 1
            if calls["count"] == occurrence:
                raise PermissionError(message)
        return real_unlink(path, *args, **kwargs)

    with mock.patch("os.unlink", side_effect=failing_unlink):
        yield



def _make_cfg(**overrides) -> dict:
    params = ProjectParams(
        suite_name="TestSuite",
        root_namespace="TestSuite",
        plugin_guid_root="com.example.testsuite",
        author="A",
        thunderstore_namespace="NS",
        **overrides,
    )
    return suite_config_dict(build_model(params))


class ContainmentHelperTests(unittest.TestCase):
    """Direct unit coverage for `suite_metadata.contain()`: grammar
    validation should already make an escape impossible for every field
    that uses it, but `contain()` is the structural, last-line defense and
    must reject/accept correctly on its own terms."""

    def setUp(self):
        scripts_dir = copy_template_to_temp() / "scripts"
        self.metadata, _pkg = _import_scripts_from(scripts_dir)

    def test_rejects_path_outside_root(self):
        root = Path(tempfile.mkdtemp(prefix="valheimsuite-root-"))
        outside = Path(tempfile.mkdtemp(prefix="valheimsuite-outside-")) / "file.txt"
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.contain(outside, root)
        self.assertFalse(outside.exists())

    def test_accepts_path_inside_root(self):
        root = Path(tempfile.mkdtemp(prefix="valheimsuite-root-"))
        target = root / "sub" / "file.txt"
        self.assertEqual(target.resolve(), self.metadata.contain(target, root))


class ProjectNameGrammarTests(unittest.TestCase):
    """Item 3/9: representative invalid project values must be rejected;
    ordinary generated project names must keep working."""

    def setUp(self):
        scripts_dir = copy_template_to_temp() / "scripts"
        self.metadata, _pkg = _import_scripts_from(scripts_dir)

    def test_rejects_traversal_separator_and_reserved_values(self):
        for bad in ("../escaped", "foo/bar", "foo\\bar", ".", "..", "", "   ", "CON", "com9", "Foo ", " Foo", "Foo\n"):
            with self.subTest(bad=bad):
                with self.assertRaises(self.metadata.MetadataError):
                    self.metadata.validate_path_component(bad, "project name")

    def test_rejects_absolute_paths(self):
        for bad in ("/etc/passwd", "/tmp/evil"):
            with self.subTest(bad=bad):
                with self.assertRaises(self.metadata.MetadataError):
                    self.metadata.validate_path_component(bad, "project name")

    def test_accepts_ordinary_generated_project_names(self):
        for good in ("TestSuite.Common", "TestSuite-ServerCore", "A"):
            self.assertEqual(good, self.metadata.validate_path_component(good, "project name"))


class NamespaceValidationTests(unittest.TestCase):
    """Item 2/9: rootNamespace must be a dot-separated sequence of valid,
    unescaped C# identifiers."""

    def setUp(self):
        scripts_dir = copy_template_to_temp() / "scripts"
        self.metadata, _pkg = _import_scripts_from(scripts_dir)

    def test_accepts_valid_dotted_namespace(self):
        self.metadata.validate_namespace("ExampleCompany.Vibeheim", "rootNamespace")

    def test_rejects_invalid_namespaces(self):
        cases = [
            ".Vibeheim",  # leading dot
            "Vibeheim.",  # trailing dot
            "Vibeheim..Common",  # doubled dot / empty segment
            "Vibeheim/Common",  # path separator
            "Vibeheim\\Common",  # path separator
            "Vibe heim",  # whitespace
            "Vibe\nheim",  # control character
            "1Vibeheim",  # identifier can't start with a digit
            "class",  # reserved C# keyword
            "namespace.Tools",  # reserved keyword as first segment
            "Foo.class",  # reserved keyword segment
            "",
        ]
        for bad in cases:
            with self.subTest(bad=bad):
                with self.assertRaises(self.metadata.MetadataError):
                    self.metadata.validate_namespace(bad, "rootNamespace")


class SyncCollisionTests(unittest.TestCase):
    """Item 7: `add_bytes()` is the single choke point for every archive
    write; duplicate archive members must be rejected rather than silently
    overwriting each other in the produced ZIP."""

    def test_add_bytes_rejects_duplicate_arcname(self):
        scripts_dir = copy_template_to_temp() / "scripts"
        _sm, pkg = _import_scripts_from(scripts_dir)
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "t.zip"
            seen: set[str] = set()
            with zipfile.ZipFile(zpath, "w") as zf:
                pkg.add_bytes(zf, "a.txt", b"1", seen)
                with self.assertRaises(pkg.PackageError):
                    pkg.add_bytes(zf, "a.txt", b"2", seen)


class ZipMemberSafetyTests(unittest.TestCase):
    """Item 6/9: archive member paths are validated independently of any
    config-derived grammar, using explicit POSIX semantics."""

    def setUp(self):
        scripts_dir = copy_template_to_temp() / "scripts"
        _sm, self.pkg = _import_scripts_from(scripts_dir)

    def test_rejects_unsafe_member_paths(self):
        for bad in (
            "/etc/passwd",
            "C:/evil.txt",
            "a/../b",
            "a/./b",
            "a//b",
            "a/b/",
            "a\\b",
            "..",
            "",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(self.pkg.PackageError):
                    self.pkg.validate_arcname(bad)

    def test_accepts_ordinary_relative_paths(self):
        self.assertEqual("BepInEx/plugins/Suite/Foo.dll", self.pkg.validate_arcname("BepInEx/plugins/Suite/Foo.dll"))

    def test_rejects_member_escaping_its_logical_directory(self):
        plugin_root = "BepInEx/plugins/Suite"
        escaped = "BepInEx/plugins/../escaped/Auditheim.Common.dll"
        with self.assertRaises(self.pkg.PackageError):
            self.pkg.validate_arcname(escaped)
        # Even if a future change relaxed `validate_arcname`, the
        # prefix-containment check must still catch an escape.
        with self.assertRaises(self.pkg.PackageError):
            self.pkg._require_arcname_under("BepInEx/plugins/OtherSuite/x.dll", plugin_root)


class PackageOutputContainmentTests(unittest.TestCase):
    """Items 5/9: `package.py` must fail safely when invoked directly
    (`create_package()`), independent of whether `suite_metadata.validate()`
    ever ran, and packages must never escape `artifacts/packages/`."""

    def _artifact(self, root: Path, project: str, tfm: str) -> Path:
        dll = root / "src" / project / "bin" / "Release" / tfm / f"{project}.dll"
        dll.parent.mkdir(parents=True, exist_ok=True)
        dll.write_bytes(b"fake-dll")
        return dll

    def test_direct_create_package_call_rejects_traversal_output_name(self):
        root = copy_template_to_temp()
        _sm, pkg = _import_scripts_from(root / "scripts")
        cfg = _make_cfg()
        common = cfg["packages"]["commonModule"]
        self._artifact(root, common, cfg["projects"][common]["targetFramework"])

        out_before = sorted(pkg.OUT.glob("**/*")) if pkg.OUT.exists() else []
        with self.assertRaises(pkg.PackageError):
            pkg.create_package("../escaped", cfg["suiteVersion"], [common], cfg, "test-kind")

        out_after = sorted(pkg.OUT.glob("**/*")) if pkg.OUT.exists() else []
        self.assertEqual(out_before, out_after)
        self.assertFalse((root / "artifacts" / "escaped.zip").exists())
        self.assertFalse((root / "escaped.zip").exists())

    def test_direct_create_package_call_rejects_traversal_suite_name(self):
        """Reproduces the reported `BepInEx/plugins/../escaped/...` member:
        `suiteName` must be rejected before any ZIP is opened at all, since
        it also seeds the plugin arcname prefix."""
        root = copy_template_to_temp()
        _sm, pkg = _import_scripts_from(root / "scripts")
        cfg = _make_cfg()
        cfg["suiteName"] = "../escaped"
        common = cfg["packages"]["commonModule"]
        self._artifact(root, common, cfg["projects"][common]["targetFramework"])

        with self.assertRaises(pkg.PackageError):
            pkg.create_package(f"{cfg['suiteName']}-Test", cfg["suiteVersion"], [common], cfg, "test-kind")

        self.assertFalse((root / "artifacts" / "packages").exists())
        self.assertFalse((root / "escaped").exists())
        self.assertFalse((root / "artifacts" / "escaped").exists())


class AbsoluteProjectPathTests(unittest.TestCase):
    """Item 9: an absolute `commonModule` project name must fail metadata
    validation, and `sync()` must never write outside the generated repo."""

    def test_absolute_common_module_cannot_escape_repository_on_sync(self):
        _params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)

        cfg = _load_cfg(output_dir)
        common = cfg["packages"]["commonModule"]
        common_item = cfg["projects"][common]

        escape_root = Path(tempfile.mkdtemp(prefix="valheimsuite-escape-"))
        abs_name = str(escape_root / "evil")
        # Forge the sibling `.csproj` that `validate()`'s (legitimate)
        # existence/content check inspects, so validation actually reaches
        # the vulnerable code path -- deriving `generated_cs` from the
        # unvalidated absolute project name -- instead of failing for an
        # unrelated, coincidental reason.
        Path(f"{abs_name}.csproj").write_text(
            "<Project><PropertyGroup>"
            f"<TargetFramework>{common_item['targetFramework']}</TargetFramework>"
            f"<AssemblyName>{abs_name}</AssemblyName>"
            "</PropertyGroup></Project>",
            encoding="utf-8",
        )

        cfg["projects"][abs_name] = cfg["projects"].pop(common)
        cfg["packages"]["commonModule"] = abs_name
        _save_cfg(output_dir, cfg)

        outside_write = Path(abs_name) / "SuiteConstants.Generated.cs"
        generated_snapshot = _snapshot(
            [output_dir / "build" / "Suite.Generated.props", output_dir / "packaging" / "profile-lock.json"]
        )

        proc = _run(["scripts/suite_metadata.py", "sync"], output_dir)

        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertFalse(outside_write.exists(), "sync() must never write outside the generated repository")
        self.assertFalse(escape_root.joinpath("evil").exists())
        for path, before in generated_snapshot.items():
            self.assertEqual(before, path.read_bytes() if path.is_file() else None, f"{path} changed unexpectedly")


class SuiteNameTraversalTests(unittest.TestCase):
    """Item 9: `suiteName="../escaped"` must be rejected by `sync()` and,
    independently, by packaging -- with no package ever escaping
    `artifacts/packages/`."""

    def test_sync_rejects_suite_name_traversal_without_writing(self):
        _params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)

        cfg = _load_cfg(output_dir)
        cfg["suiteName"] = "../escaped"
        _save_cfg(output_dir, cfg)

        generated_snapshot = _snapshot(
            [output_dir / "build" / "Suite.Generated.props", output_dir / "packaging" / "profile-lock.json"]
        )
        proc = _run(["scripts/suite_metadata.py", "sync"], output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        for path, before in generated_snapshot.items():
            self.assertEqual(before, path.read_bytes() if path.is_file() else None, f"{path} changed unexpectedly")

    def test_packaging_rejects_suite_name_traversal_independently_of_sync(self):
        _params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)

        cfg = _load_cfg(output_dir)
        cfg["suiteName"] = "../escaped"
        _save_cfg(output_dir, cfg)

        proc = _run(["scripts/package.py"], output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertFalse((output_dir / "artifacts" / "packages").exists())
        self.assertFalse((output_dir.parent / "escaped").exists())
        self.assertFalse((output_dir / "artifacts" / "escaped").exists())


class ValidMetadataRemainsValidTests(unittest.TestCase):
    """Item 9/11: normal generated projects must keep working end to end."""

    def test_sync_check_and_package_succeed_for_a_normal_generated_project(self):
        params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)

        check_proc = _run(["scripts/suite_metadata.py", "check"], output_dir)
        self.assertEqual(0, check_proc.returncode, check_proc.stdout)

        cfg = _load_cfg(output_dir)
        for project, item in cfg["projects"].items():
            dll = output_dir / "src" / project / "bin" / "Release" / item["targetFramework"] / f"{project}.dll"
            dll.parent.mkdir(parents=True, exist_ok=True)
            dll.write_bytes(b"fake-dll")

        pkg_proc = _run(["scripts/package.py"], output_dir)
        self.assertEqual(0, pkg_proc.returncode, pkg_proc.stdout)

        packages_dir = output_dir / "artifacts" / "packages"
        zips = sorted(packages_dir.glob("*.zip"))
        self.assertTrue(zips)
        for zip_path in zips:
            with zipfile.ZipFile(zip_path) as zf:
                for member in zf.namelist():
                    self.assertFalse(member.startswith("/"), member)
                    self.assertNotIn("..", member.split("/"), member)
                    if member.startswith("BepInEx/plugins/"):
                        self.assertTrue(
                            member.startswith(f"BepInEx/plugins/{cfg['suiteName']}/"), member
                        )



class SyncSymlinkSafetyTests(unittest.TestCase):
    """A redirected generated-output path must fail before sync touches it."""

    def _generated_project(self) -> Path:
        _params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        return output_dir

    def _assert_sync_rejected(self, output_dir: Path) -> None:
        proc = _run(["scripts/suite_metadata.py", "sync"], output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)

    def test_symlinked_generated_roots_leave_external_sentinels_unchanged(self):
        for root_name in ("src", "build", "packaging"):
            with self.subTest(root_name=root_name):
                output_dir = self._generated_project()
                common = _load_cfg(output_dir)["packages"]["commonModule"]
                sentinel_rel = {
                    "src": Path(common) / "SuiteConstants.Generated.cs",
                    "build": Path("Suite.Generated.props"),
                    "packaging": Path("profile-lock.json"),
                }[root_name]
                external_root = Path(tempfile.mkdtemp(prefix="valheimsuite-external-root-"))
                moved_root = external_root / root_name
                shutil.move(str(output_dir / root_name), moved_root)
                sentinel = moved_root / sentinel_rel
                sentinel.write_bytes(b"external sentinel")
                (output_dir / root_name).symlink_to(moved_root, target_is_directory=True)

                untouched = _snapshot(
                    [
                        output_dir / "build" / "Suite.Generated.props",
                        output_dir / "src" / common / "SuiteConstants.Generated.cs",
                        output_dir / "packaging" / "profile-lock.json",
                    ]
                )
                self._assert_sync_rejected(output_dir)

                self.assertEqual(b"external sentinel", sentinel.read_bytes())
                for path, before in untouched.items():
                    if path == output_dir / root_name / sentinel_rel:
                        continue
                    self.assertEqual(before, path.read_bytes() if path.is_file() else None, f"{path} changed unexpectedly")

    def test_symlinked_fixed_outputs_leave_external_sentinels_unchanged(self):
        for relpath in ("build/Suite.Generated.props", "packaging/profile-lock.json"):
            with self.subTest(relpath=relpath):
                output_dir = self._generated_project()
                common = _load_cfg(output_dir)["packages"]["commonModule"]
                target = output_dir / relpath
                external = Path(tempfile.mkdtemp(prefix="valheimsuite-external-file-")) / target.name
                external.write_bytes(b"external sentinel")
                target.unlink()
                target.symlink_to(external)

                untouched = _snapshot(
                    [
                        output_dir / "build" / "Suite.Generated.props",
                        output_dir / "src" / common / "SuiteConstants.Generated.cs",
                        output_dir / "packaging" / "profile-lock.json",
                    ]
                )
                self._assert_sync_rejected(output_dir)

                self.assertEqual(b"external sentinel", external.read_bytes())
                for path, before in untouched.items():
                    if path == target:
                        continue
                    self.assertEqual(before, path.read_bytes() if path.is_file() else None, f"{path} changed unexpectedly")

    def test_symlinked_generated_constant_leaves_external_sentinel_unchanged(self):
        output_dir = self._generated_project()
        common = _load_cfg(output_dir)["packages"]["commonModule"]
        target = output_dir / "src" / common / "SuiteConstants.Generated.cs"
        external = Path(tempfile.mkdtemp(prefix="valheimsuite-external-constant-")) / target.name
        external.write_bytes(b"external sentinel")
        target.unlink()
        target.symlink_to(external)

        untouched = _snapshot(
            [output_dir / "build" / "Suite.Generated.props", output_dir / "packaging" / "profile-lock.json"]
        )
        self._assert_sync_rejected(output_dir)

        self.assertEqual(b"external sentinel", external.read_bytes())
        for path, before in untouched.items():
            self.assertEqual(before, path.read_bytes() if path.is_file() else None, f"{path} changed unexpectedly")




class PackageWriteBoundaryTests(unittest.TestCase):
    def _generated_project_with_artifacts(self) -> tuple[Path, dict]:
        _params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        cfg = _load_cfg(output_dir)
        for project, item in cfg["projects"].items():
            dll = output_dir / "src" / project / "bin" / "Release" / item["targetFramework"] / f"{project}.dll"
            dll.parent.mkdir(parents=True, exist_ok=True)
            dll.write_bytes(project.encode())
        return output_dir, cfg

    def test_symlinked_package_root_is_rejected_before_any_external_write(self):
        output_dir, _cfg = self._generated_project_with_artifacts()
        external = Path(tempfile.mkdtemp(prefix="valheimsuite-external-packages-"))
        sentinel = external / "sentinel"
        sentinel.write_bytes(b"external sentinel")
        (output_dir / "artifacts").mkdir()
        (output_dir / "artifacts" / "packages").symlink_to(external, target_is_directory=True)

        proc = _run(["scripts/package.py"], output_dir)

        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertEqual(b"external sentinel", sentinel.read_bytes())
        self.assertEqual([sentinel], sorted(external.iterdir()))

    def test_symlinked_checksum_target_is_rejected_before_any_external_write(self):
        output_dir, _cfg = self._generated_project_with_artifacts()
        packages = output_dir / "artifacts" / "packages"
        packages.mkdir(parents=True)
        external = Path(tempfile.mkdtemp(prefix="valheimsuite-external-checksum-")) / "SHA256SUMS"
        external.write_bytes(b"external sentinel")
        (packages / "SHA256SUMS").symlink_to(external)

        proc = _run(["scripts/package.py"], output_dir)

        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertEqual(b"external sentinel", external.read_bytes())
        self.assertEqual([], list(packages.glob("*.zip")))

    def test_symlinked_final_package_target_is_rejected_before_any_external_write(self):
        output_dir, cfg = self._generated_project_with_artifacts()
        packages = output_dir / "artifacts" / "packages"
        packages.mkdir(parents=True)
        name, _modules, _kind = _import_scripts_from(output_dir / "scripts")[1].package_definitions(cfg)[0]
        target = packages / f"{name}-{cfg['suiteVersion']}.zip"
        external = Path(tempfile.mkdtemp(prefix="valheimsuite-external-package-")) / target.name
        external.write_bytes(b"external sentinel")
        target.symlink_to(external)

        proc = _run(["scripts/package.py"], output_dir)

        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertEqual(b"external sentinel", external.read_bytes())
        self.assertEqual([target], list(packages.iterdir()))

    def test_duplicate_portable_outputs_fail_before_cleaning_existing_outputs(self):
        output_dir, cfg = self._generated_project_with_artifacts()
        for project in ("Foo.Bar", "foo-bar"):
            cfg["projects"][project] = {"scope": "sharedOptional", "targetFramework": "net48"}
            cfg["packages"]["serverModules"].append(project)
            cfg["packages"]["optionalClientModules"].append(project)
            project_dir = output_dir / "src" / project
            project_dir.mkdir()
            (project_dir / f"{project}.csproj").write_text(
                "<Project><PropertyGroup><TargetFramework>net48</TargetFramework>"
                f"<AssemblyName>{project}</AssemblyName></PropertyGroup></Project>",
                encoding="utf-8",
            )
            dll = project_dir / "bin" / "Release" / "net48" / f"{project}.dll"
            dll.parent.mkdir(parents=True)
            dll.write_bytes(project.encode())
        _add_sln_entries(output_dir, cfg["rootNamespace"], ["Foo.Bar", "foo-bar"])
        _save_cfg(output_dir, cfg)
        sync = _run(["scripts/suite_metadata.py", "sync"], output_dir)
        self.assertEqual(0, sync.returncode, sync.stdout)

        packages = output_dir / "artifacts" / "packages"
        packages.mkdir(parents=True)
        old_zip = packages / "old.zip"
        checksum = packages / "SHA256SUMS"
        old_zip.write_bytes(b"old archive")
        checksum.write_bytes(b"old checksums")

        proc = _run(["scripts/package.py", "--clean"], output_dir)

        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertEqual(b"old archive", old_zip.read_bytes())
        self.assertEqual(b"old checksums", checksum.read_bytes())


class PackagePlanSafetyTests(unittest.TestCase):
    def _package_setup(self) -> tuple[Path, object, dict, str]:
        root = copy_template_to_temp()
        _metadata, pkg = _import_scripts_from(root / "scripts")
        cfg = _make_cfg()
        common = cfg["packages"]["commonModule"]
        module = next(project for project in cfg["projects"] if project != common)
        for project in (common, module):
            tfm = cfg["projects"][project]["targetFramework"]
            dll = root / "src" / project / "bin" / "Release" / tfm / f"{project}.dll"
            dll.parent.mkdir(parents=True, exist_ok=True)
            dll.write_bytes(project.encode())
        return root, pkg, cfg, module

    def test_member_plan_failure_never_creates_or_overwrites_final_zip(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                _root, pkg, cfg, module = self._package_setup()
                target = pkg.OUT / "Transactional-0.1.0.zip"
                target.parent.mkdir(parents=True)
                if existing:
                    target.write_bytes(b"existing archive")

                with self.assertRaises(pkg.PackageError):
                    pkg.create_package("Transactional", "0.1.0", [module, module], cfg, "test")

                if existing:
                    self.assertEqual(b"existing archive", target.read_bytes())
                else:
                    self.assertFalse(target.exists())

    def test_archive_writer_rejects_control_and_case_colliding_members_before_writing(self):
        _root, pkg, _cfg, _module = self._package_setup()
        with tempfile.TemporaryDirectory() as tmp:
            control_zip = Path(tmp) / "control.zip"
            with zipfile.ZipFile(control_zip, "w") as zf:
                for unsafe in ("safe.txt\0hidden", "safe.txt\x1fhidden", "safe.txt\x85hidden"):
                    with self.subTest(unsafe=unsafe):
                        with self.assertRaises(pkg.PackageError):
                            pkg.add_bytes(zf, unsafe, b"payload", set())
                self.assertEqual([], zf.namelist())

            case_zip = Path(tmp) / "case.zip"
            with zipfile.ZipFile(case_zip, "w") as zf:
                seen: set[str] = set()
                pkg.add_bytes(zf, "Dir/Foo.dll", b"first", seen)
                with self.assertRaises(pkg.PackageError):
                    pkg.add_bytes(zf, "dir/foo.dll", b"second", seen)
                self.assertEqual(["Dir/Foo.dll"], zf.namelist())


class BootstrapGrammarAlignmentTests(unittest.TestCase):
    def _run_cli(self, output_dir: Path, *extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "bootstrap.create_project",
                *extra,
                "--guid",
                "com.example.testsuite",
                "--author",
                "Author",
                "--thunderstore-namespace",
                "Namespace",
                "--output",
                str(output_dir),
            ],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            capture_output=True,
        )

    def test_cli_rejects_inputs_that_generated_metadata_would_reject(self):
        cases = (
            (("--name", "My Suite", "--namespace", "TestSuite"), "suiteName"),
            (("--name", "TestSuite", "--namespace", "class"), "rootNamespace"),
            (("--name", "TestSuite", "--namespace", "TestSuite", "--version", "01.2.3"), "suiteVersion"),
        )
        for extra, field in cases:
            with self.subTest(extra=extra):
                output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-invalid-bootstrap-"))
                result = self._run_cli(output_dir, *extra)
                self.assertNotEqual(0, result.returncode)
                self.assertIn(field, result.stderr)
                self.assertFalse(any(output_dir.iterdir()))


class MalformedPackageListTests(unittest.TestCase):
    def test_non_string_package_members_raise_metadata_error(self):
        _params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        metadata, _pkg = _import_scripts_from(output_dir / "scripts")
        cfg = _load_cfg(output_dir)
        cfg["packages"]["serverModules"] = [["not-a-project"]]

        with self.assertRaises(metadata.MetadataError):
            metadata.validate(cfg)


class GeneratedGrammarAlignmentTests(unittest.TestCase):
    def test_leading_underscore_namespace_generates_and_synchronizes(self):
        _params, output_dir, result = generate_into_temp(root_namespace="_Private")
        self.assertTrue(result.ok, result.errors)
        check = _run(["scripts/suite_metadata.py", "check"], output_dir)
        self.assertEqual(0, check.returncode, check.stdout)


class SyncFinalTargetPreflightTests(unittest.TestCase):
    def test_non_regular_final_targets_fail_before_any_sync_write(self):
        for relpath in (
            "build/Suite.Generated.props",
            "src/TestSuite.Common/SuiteConstants.Generated.cs",
            "packaging/profile-lock.json",
        ):
            with self.subTest(relpath=relpath):
                _params, output_dir, result = generate_into_temp()
                self.assertTrue(result.ok, result.errors)
                cfg = _load_cfg(output_dir)
                common = cfg["packages"]["commonModule"]
                targets = [
                    output_dir / "build" / "Suite.Generated.props",
                    output_dir / "src" / common / "SuiteConstants.Generated.cs",
                    output_dir / "packaging" / "profile-lock.json",
                ]
                snapshots = _snapshot(targets)
                cfg["suiteVersion"] = "0.1.1"
                _save_cfg(output_dir, cfg)
                target = output_dir / relpath.replace("TestSuite.Common", common)
                target.unlink()
                target.mkdir()

                proc = _run(["scripts/suite_metadata.py", "sync"], output_dir)

                self.assertNotEqual(0, proc.returncode, proc.stdout)
                self.assertTrue(target.is_dir())
                for other in targets:
                    if other != target:
                        self.assertEqual(snapshots[other], other.read_bytes(), f"{other} changed unexpectedly")


class PackageFinalTargetPreflightTests(unittest.TestCase):
    def _setup(self) -> tuple[Path, dict, Path]:
        _params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        cfg = _load_cfg(output_dir)
        for project, item in cfg["projects"].items():
            dll = output_dir / "src" / project / "bin" / "Release" / item["targetFramework"] / f"{project}.dll"
            dll.parent.mkdir(parents=True, exist_ok=True)
            dll.write_bytes(project.encode())
        packages = output_dir / "artifacts" / "packages"
        packages.mkdir(parents=True)
        return output_dir, cfg, packages

    def test_planned_zip_directory_rejects_before_cleaning(self):
        output_dir, cfg, packages = self._setup()
        _metadata, pkg = _import_scripts_from(output_dir / "scripts")
        name, _modules, _kind = pkg.package_definitions(cfg)[0]
        (packages / f"{name}-{cfg['suiteVersion']}.zip").mkdir()
        old_zip = packages / "old.zip"
        checksum = packages / "SHA256SUMS"
        old_zip.write_bytes(b"old archive")
        checksum.write_bytes(b"old checksums")

        proc = _run(["scripts/package.py", "--clean"], output_dir)

        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertIn("package error:", proc.stdout)
        self.assertEqual(b"old archive", old_zip.read_bytes())
        self.assertEqual(b"old checksums", checksum.read_bytes())

    def test_non_regular_checksum_rejects_before_cleaning(self):
        output_dir, _cfg, packages = self._setup()
        old_zip = packages / "old.zip"
        checksum = packages / "SHA256SUMS"
        old_zip.write_bytes(b"old archive")
        checksum.mkdir()

        proc = _run(["scripts/package.py", "--clean"], output_dir)

        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertIn("package error:", proc.stdout)
        self.assertEqual(b"old archive", old_zip.read_bytes())
        self.assertTrue(checksum.is_dir())

    def test_non_regular_cleanup_entry_uses_controlled_failure(self):
        output_dir, _cfg, packages = self._setup()
        (packages / "old.zip").mkdir()
        checksum = packages / "SHA256SUMS"
        checksum.write_bytes(b"old checksums")

        proc = _run(["scripts/package.py", "--clean"], output_dir)

        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertIn("package error:", proc.stdout)
        self.assertTrue((packages / "old.zip").is_dir())


class TemporaryEntrySubstitutionTests(unittest.TestCase):
    def _assert_external_unchanged(self, external: Path, mode: int) -> None:
        self.assertEqual(b"external sentinel", external.read_bytes())
        self.assertEqual(mode, stat.S_IMODE(external.stat().st_mode))

    def test_text_promotion_rejects_substituted_temp_entry(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "build" / "race.generated"
        target.parent.mkdir()
        target.write_bytes(b"existing generated text")
        external = Path(tempfile.mkdtemp(prefix="valheimsuite-temp-text-")) / "sentinel"
        external.write_bytes(b"external sentinel")
        external.chmod(0o640)
        external_mode = stat.S_IMODE(external.stat().st_mode)
        original = metadata.promote_temp_file

        def substitute(parent, temp, final_name, **kwargs):
            _replace_temp_entry(parent, temp, external)
            return original(parent, temp, final_name, **kwargs)

        with mock.patch.object(metadata, "promote_temp_file", side_effect=substitute):
            with self.assertRaises(metadata.MetadataError):
                metadata.atomic_write_text(target, "new generated text")

        self._assert_external_unchanged(external, external_mode)
        self.assertFalse(target.is_symlink())
        self.assertEqual(b"existing generated text", target.read_bytes())

    def test_zip_promotion_rejects_substituted_temp_entry(self):
        root = copy_template_to_temp()
        metadata, pkg = _import_scripts_from(root / "scripts")
        target = pkg.OUT / "race.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing archive")
        external = Path(tempfile.mkdtemp(prefix="valheimsuite-temp-zip-")) / "sentinel"
        external.write_bytes(b"external sentinel")
        external.chmod(0o640)
        external_mode = stat.S_IMODE(external.stat().st_mode)
        original = metadata.promote_temp_file

        def substitute(parent, temp, final_name, **kwargs):
            _replace_temp_entry(parent, temp, external)
            return original(parent, temp, final_name, **kwargs)

        with mock.patch.object(metadata, "promote_temp_file", side_effect=substitute):
            with self.assertRaises(pkg.PackageError):
                pkg._write_package(target, [("safe.txt", b"payload")])

        self._assert_external_unchanged(external, external_mode)
        self.assertFalse(target.is_symlink())
        self.assertEqual(b"existing archive", target.read_bytes())
        self.assertFalse(any(target.parent.glob(f".{target.name}.*.tmp")))

    def test_checksum_promotion_rejects_substituted_temp_entry(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "artifacts" / "packages" / "SHA256SUMS"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing checksums")
        external = Path(tempfile.mkdtemp(prefix="valheimsuite-temp-checksum-")) / "sentinel"
        external.write_bytes(b"external sentinel")
        external.chmod(0o640)
        external_mode = stat.S_IMODE(external.stat().st_mode)
        original = metadata.promote_temp_file

        def substitute(parent, temp, final_name, **kwargs):
            _replace_temp_entry(parent, temp, external)
            return original(parent, temp, final_name, **kwargs)

        with mock.patch.object(metadata, "promote_temp_file", side_effect=substitute):
            with self.assertRaises(metadata.MetadataError):
                metadata.atomic_write_text(target, "new checksums\n")

        self._assert_external_unchanged(external, external_mode)
        self.assertFalse(target.is_symlink())
        self.assertEqual(b"existing checksums", target.read_bytes())


class DirectoryFdParentRebindingTests(unittest.TestCase):
    def _rebind(self, parent: Path, external: Path) -> Path:
        authorized = parent.with_name(f"{parent.name}-authorized")
        parent.rename(authorized)
        parent.symlink_to(external, target_is_directory=True)
        return authorized

    def test_text_write_cannot_follow_parent_rebound_after_containment(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "build" / "race.generated"
        external = Path(tempfile.mkdtemp(prefix="valheimsuite-race-text-"))
        sentinel = external / "sentinel"
        sentinel.write_bytes(b"external sentinel")
        original = metadata.create_temp_file

        def rebind(parent, final_name, **kwargs):
            self._rebind(target.parent, external)
            return original(parent, final_name, **kwargs)

        with mock.patch.object(metadata, "create_temp_file", side_effect=rebind):
            with self.assertRaises(metadata.MetadataError):
                metadata.atomic_write_text(target, "generated")

        self.assertEqual(b"external sentinel", sentinel.read_bytes())
        self.assertFalse((external / target.name).exists())

    def test_zip_write_cannot_follow_parent_rebound_after_containment(self):
        root = copy_template_to_temp()
        metadata, pkg = _import_scripts_from(root / "scripts")
        target = pkg.OUT / "race.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing archive")
        external = Path(tempfile.mkdtemp(prefix="valheimsuite-race-zip-"))
        sentinel = external / "sentinel"
        sentinel.write_bytes(b"external sentinel")
        original = metadata.create_temp_file
        authorized: list[Path] = []

        def rebind(parent, final_name, **kwargs):
            authorized.append(self._rebind(target.parent, external))
            return original(parent, final_name, **kwargs)

        with mock.patch.object(metadata, "create_temp_file", side_effect=rebind):
            with self.assertRaises(pkg.PackageError):
                pkg._write_package(target, [("safe.txt", b"payload")])

        self.assertEqual(b"external sentinel", sentinel.read_bytes())
        self.assertFalse((external / target.name).exists())
        self.assertEqual(b"existing archive", (authorized[0] / target.name).read_bytes())

    def test_checksum_write_cannot_follow_parent_rebound_after_containment(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "artifacts" / "packages" / "SHA256SUMS"
        target.parent.mkdir(parents=True)
        external = Path(tempfile.mkdtemp(prefix="valheimsuite-race-checksum-"))
        sentinel = external / "sentinel"
        sentinel.write_bytes(b"external sentinel")
        original = metadata.create_temp_file

        def rebind(parent, final_name, **kwargs):
            self._rebind(target.parent, external)
            return original(parent, final_name, **kwargs)

        with mock.patch.object(metadata, "create_temp_file", side_effect=rebind):
            with self.assertRaises(metadata.MetadataError):
                metadata.atomic_write_text(target, "checksum\n")

        self.assertEqual(b"external sentinel", sentinel.read_bytes())
        self.assertFalse((external / target.name).exists())


class PostVerificationSubstitutionTests(unittest.TestCase):
    """The temp-entry substitution above (before verification) is already
    caught by `_verify_temporary_output()`. These reproduce the tighter
    residual: substitution injected immediately *after* that verification
    succeeds, right at the promotion boundary."""

    def _external_sentinel(self, prefix: str) -> tuple[Path, int]:
        external = Path(tempfile.mkdtemp(prefix=prefix)) / "sentinel"
        external.write_bytes(b"external sentinel")
        external.chmod(0o640)
        return external, stat.S_IMODE(external.stat().st_mode)

    def _assert_sentinel_untouched(self, external: Path, mode: int) -> None:
        self.assertEqual(b"external sentinel", external.read_bytes())
        self.assertEqual(mode, stat.S_IMODE(external.stat().st_mode))

    def test_text_promotion_restores_existing_final_after_post_verify_substitution(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "build" / "race.generated"
        target.parent.mkdir()
        target.write_bytes(b"existing generated text")
        target.chmod(0o640)
        original_mode = stat.S_IMODE(target.stat().st_mode)
        external, external_mode = self._external_sentinel("valheimsuite-postverify-text-")

        with _inject_after_verify(metadata, external):
            with self.assertRaises(metadata.MetadataError):
                metadata.atomic_write_text(target, "new generated text")

        self._assert_sentinel_untouched(external, external_mode)
        self.assertFalse(target.is_symlink())
        self.assertEqual(b"existing generated text", target.read_bytes())
        self.assertEqual(original_mode, stat.S_IMODE(target.stat().st_mode))
        self.assertEqual([], list(target.parent.glob(".race.generated.*")))

    def test_text_promotion_leaves_absent_final_absent_after_post_verify_substitution(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "build" / "race.generated"
        target.parent.mkdir()
        external, external_mode = self._external_sentinel("valheimsuite-postverify-text-absent-")

        with _inject_after_verify(metadata, external):
            with self.assertRaises(metadata.MetadataError):
                metadata.atomic_write_text(target, "new generated text")

        self._assert_sentinel_untouched(external, external_mode)
        self.assertFalse(target.exists())
        self.assertEqual([], list(target.parent.glob(".race.generated.*")))

    def test_zip_promotion_restores_existing_final_after_post_verify_substitution(self):
        root = copy_template_to_temp()
        metadata, pkg = _import_scripts_from(root / "scripts")
        target = pkg.OUT / "race.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing archive")
        target.chmod(0o640)
        original_mode = stat.S_IMODE(target.stat().st_mode)
        external, external_mode = self._external_sentinel("valheimsuite-postverify-zip-")

        with _inject_after_verify(metadata, external):
            with self.assertRaises(pkg.PackageError):
                pkg._write_package(target, [("safe.txt", b"payload")])

        self._assert_sentinel_untouched(external, external_mode)
        self.assertFalse(target.is_symlink())
        self.assertEqual(b"existing archive", target.read_bytes())
        self.assertEqual(original_mode, stat.S_IMODE(target.stat().st_mode))
        self.assertEqual([target], list(target.parent.iterdir()))

    def test_zip_promotion_leaves_absent_final_absent_after_post_verify_substitution(self):
        root = copy_template_to_temp()
        metadata, pkg = _import_scripts_from(root / "scripts")
        target = pkg.OUT / "race.zip"
        target.parent.mkdir(parents=True)
        external, external_mode = self._external_sentinel("valheimsuite-postverify-zip-absent-")

        with _inject_after_verify(metadata, external):
            with self.assertRaises(pkg.PackageError):
                pkg._write_package(target, [("safe.txt", b"payload")])

        self._assert_sentinel_untouched(external, external_mode)
        self.assertFalse(target.exists())
        self.assertEqual([], list(target.parent.iterdir()))

    def test_checksum_promotion_restores_existing_final_after_post_verify_substitution(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "artifacts" / "packages" / "SHA256SUMS"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing checksums")
        target.chmod(0o640)
        original_mode = stat.S_IMODE(target.stat().st_mode)
        external, external_mode = self._external_sentinel("valheimsuite-postverify-checksum-")

        with _inject_after_verify(metadata, external):
            with self.assertRaises(metadata.MetadataError):
                metadata.atomic_write_text(target, "new checksums\n")

        self._assert_sentinel_untouched(external, external_mode)
        self.assertFalse(target.is_symlink())
        self.assertEqual(b"existing checksums", target.read_bytes())
        self.assertEqual(original_mode, stat.S_IMODE(target.stat().st_mode))
        self.assertEqual([target], list(target.parent.iterdir()))

    def test_checksum_promotion_leaves_absent_final_absent_after_post_verify_substitution(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "artifacts" / "packages" / "SHA256SUMS"
        target.parent.mkdir(parents=True)
        external, external_mode = self._external_sentinel("valheimsuite-postverify-checksum-absent-")

        with _inject_after_verify(metadata, external):
            with self.assertRaises(metadata.MetadataError):
                metadata.atomic_write_text(target, "new checksums\n")

        self._assert_sentinel_untouched(external, external_mode)
        self.assertFalse(target.exists())
        self.assertEqual([], list(target.parent.iterdir()))


class RecoverySubstitutionTests(unittest.TestCase):
    """Recovery of an existing final output must never trust a
    directory-entry pathname (there is no `.bak` to substitute in the
    current design: recovery reconstructs from the FD retained at
    preflight time). These force the primary write to fail, then race the
    *first* recovery attempt's own temp entry exactly once, at each of the
    two boundaries a substitution could target. The bounded retry that
    follows must fully restore the original output regardless."""

    def _external_sentinel(self, prefix: str) -> tuple[Path, int]:
        external = Path(tempfile.mkdtemp(prefix=prefix)) / "sentinel"
        external.write_bytes(b"external sentinel")
        external.chmod(0o640)
        return external, stat.S_IMODE(external.stat().st_mode)

    def _assert_sentinel_untouched(self, external: Path, mode: int) -> None:
        self.assertEqual(b"external sentinel", external.read_bytes())
        self.assertEqual(mode, stat.S_IMODE(external.stat().st_mode))

    def _run_recovery_case(self, metadata, target: Path, at: str, write, error_cls) -> None:
        target.chmod(0o640)
        original_mode = stat.S_IMODE(target.stat().st_mode)
        original_bytes = target.read_bytes()
        primary_external, primary_mode = self._external_sentinel(f"valheimsuite-recovery-{at}-primary-")
        recovery_external, recovery_mode = self._external_sentinel(f"valheimsuite-recovery-{at}-recovery-")

        with _force_primary_then_recovery_once(metadata, primary_external, recovery_external, at=at):
            with self.assertRaises(error_cls):
                write()

        self._assert_sentinel_untouched(primary_external, primary_mode)
        self._assert_sentinel_untouched(recovery_external, recovery_mode)
        self.assertFalse(target.is_symlink())
        self.assertEqual(original_bytes, target.read_bytes())
        self.assertEqual(original_mode, stat.S_IMODE(target.stat().st_mode))

    def test_text_promotion_restores_original_when_recovery_entry_substituted_at_creation(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "build" / "race.generated"
        target.parent.mkdir()
        target.write_bytes(b"existing generated text")
        self._run_recovery_case(
            metadata,
            target,
            "creation",
            lambda: metadata.atomic_write_text(target, "new generated text"),
            metadata.MetadataError,
        )
        self.assertEqual([], list(target.parent.glob(".race.generated.*")))

    def test_text_promotion_restores_original_when_recovery_entry_substituted_before_swap(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "build" / "race.generated"
        target.parent.mkdir()
        target.write_bytes(b"existing generated text")
        self._run_recovery_case(
            metadata,
            target,
            "verify",
            lambda: metadata.atomic_write_text(target, "new generated text"),
            metadata.MetadataError,
        )
        self.assertEqual([], list(target.parent.glob(".race.generated.*")))

    def test_zip_promotion_restores_original_when_recovery_entry_substituted_at_creation(self):
        root = copy_template_to_temp()
        metadata, pkg = _import_scripts_from(root / "scripts")
        target = pkg.OUT / "race.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing archive")
        self._run_recovery_case(
            metadata,
            target,
            "creation",
            lambda: pkg._write_package(target, [("safe.txt", b"payload")]),
            pkg.PackageError,
        )
        self.assertEqual([target], list(target.parent.iterdir()))

    def test_zip_promotion_restores_original_when_recovery_entry_substituted_before_swap(self):
        root = copy_template_to_temp()
        metadata, pkg = _import_scripts_from(root / "scripts")
        target = pkg.OUT / "race.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing archive")
        self._run_recovery_case(
            metadata,
            target,
            "verify",
            lambda: pkg._write_package(target, [("safe.txt", b"payload")]),
            pkg.PackageError,
        )
        self.assertEqual([target], list(target.parent.iterdir()))

    def test_checksum_promotion_restores_original_when_recovery_entry_substituted_at_creation(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "artifacts" / "packages" / "SHA256SUMS"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing checksums")
        self._run_recovery_case(
            metadata,
            target,
            "creation",
            lambda: metadata.atomic_write_text(target, "new checksums\n"),
            metadata.MetadataError,
        )
        self.assertEqual([target], list(target.parent.iterdir()))

    def test_checksum_promotion_restores_original_when_recovery_entry_substituted_before_swap(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "artifacts" / "packages" / "SHA256SUMS"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing checksums")
        self._run_recovery_case(
            metadata,
            target,
            "verify",
            lambda: metadata.atomic_write_text(target, "new checksums\n"),
            metadata.MetadataError,
        )
        self.assertEqual([target], list(target.parent.iterdir()))


class RecoveryAllocationFailureTests(unittest.TestCase):
    """Sol's reproduction: a failure *between* recovery attempts (here,
    the next `create_temp_file()` call itself raising) must not bypass
    the outer fail-safe boundary and leave the mismatched entry installed
    by a defeated earlier recovery attempt sitting at `final_name`."""

    def _external_sentinel(self, prefix: str) -> tuple[Path, int]:
        external = Path(tempfile.mkdtemp(prefix=prefix)) / "sentinel"
        external.write_bytes(b"external sentinel")
        external.chmod(0o640)
        return external, stat.S_IMODE(external.stat().st_mode)

    def _assert_sentinel_untouched(self, external: Path, mode: int) -> None:
        self.assertEqual(b"external sentinel", external.read_bytes())
        self.assertEqual(mode, stat.S_IMODE(external.stat().st_mode))

    def _run_case(self, metadata, target: Path, write, error_cls) -> None:
        primary_external, primary_mode = self._external_sentinel("valheimsuite-alloc-fail-primary-")
        recovery_external, recovery_mode = self._external_sentinel("valheimsuite-alloc-fail-recovery-")

        with _force_recovery_allocation_failure(metadata, primary_external, recovery_external):
            with self.assertRaises(error_cls):
                write()

        self._assert_sentinel_untouched(primary_external, primary_mode)
        self._assert_sentinel_untouched(recovery_external, recovery_mode)
        self.assertFalse(target.is_symlink())
        self.assertFalse(target.exists())

    def test_text_promotion_fails_safe_when_allocation_fails_between_recovery_attempts(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "build" / "race.generated"
        target.parent.mkdir()
        target.write_bytes(b"existing generated text")
        self._run_case(
            metadata, target, lambda: metadata.atomic_write_text(target, "new generated text"), metadata.MetadataError
        )
        self.assertEqual([], list(target.parent.glob(".race.generated.*")))

    def test_zip_promotion_fails_safe_when_allocation_fails_between_recovery_attempts(self):
        root = copy_template_to_temp()
        metadata, pkg = _import_scripts_from(root / "scripts")
        target = pkg.OUT / "race.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing archive")
        self._run_case(
            metadata, target, lambda: pkg._write_package(target, [("safe.txt", b"payload")]), pkg.PackageError
        )
        self.assertEqual([], list(target.parent.iterdir()))

    def test_checksum_promotion_fails_safe_when_allocation_fails_between_recovery_attempts(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "artifacts" / "packages" / "SHA256SUMS"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing checksums")
        self._run_case(
            metadata, target, lambda: metadata.atomic_write_text(target, "new checksums\n"), metadata.MetadataError
        )
        self.assertEqual([], list(target.parent.iterdir()))


class RecoveryRetryExhaustionTests(unittest.TestCase):
    """A persistent attacker who wins every race must still be met with a
    bounded, safely-absent failure -- and if cleanup itself cannot
    confirm that safe state, the code must say so rather than pretend."""

    def _external_sentinel(self, prefix: str) -> tuple[Path, int]:
        external = Path(tempfile.mkdtemp(prefix=prefix)) / "sentinel"
        external.write_bytes(b"external sentinel")
        external.chmod(0o640)
        return external, stat.S_IMODE(external.stat().st_mode)

    def _assert_sentinel_untouched(self, external: Path, mode: int) -> None:
        self.assertEqual(b"external sentinel", external.read_bytes())
        self.assertEqual(mode, stat.S_IMODE(external.stat().st_mode))

    def test_text_exhausts_retries_and_leaves_final_safely_absent(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "build" / "race.generated"
        target.parent.mkdir()
        target.write_bytes(b"existing generated text")
        external, mode = self._external_sentinel("valheimsuite-exhausted-text-")

        with _substitute_every_verified_temp_entry(metadata, external):
            with self.assertRaises(metadata.MetadataError):
                metadata.atomic_write_text(target, "new generated text")

        self._assert_sentinel_untouched(external, mode)
        self.assertFalse(target.exists())
        self.assertEqual([], list(target.parent.glob(".race.generated.*")))

    def test_zip_exhausts_retries_and_leaves_final_safely_absent(self):
        root = copy_template_to_temp()
        metadata, pkg = _import_scripts_from(root / "scripts")
        target = pkg.OUT / "race.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing archive")
        external, mode = self._external_sentinel("valheimsuite-exhausted-zip-")

        with _substitute_every_verified_temp_entry(metadata, external):
            with self.assertRaises(pkg.PackageError):
                pkg._write_package(target, [("safe.txt", b"payload")])

        self._assert_sentinel_untouched(external, mode)
        self.assertFalse(target.exists())
        self.assertEqual([], list(target.parent.iterdir()))

    def test_checksum_exhausts_retries_and_leaves_final_safely_absent(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "artifacts" / "packages" / "SHA256SUMS"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing checksums")
        external, mode = self._external_sentinel("valheimsuite-exhausted-checksum-")

        with _substitute_every_verified_temp_entry(metadata, external):
            with self.assertRaises(metadata.MetadataError):
                metadata.atomic_write_text(target, "new checksums\n")

        self._assert_sentinel_untouched(external, mode)
        self.assertFalse(target.exists())
        self.assertEqual([], list(target.parent.iterdir()))

    def test_final_cleanup_failure_is_surfaced_not_suppressed(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "build" / "race.generated"
        target.parent.mkdir()
        target.write_bytes(b"existing generated text")
        external, mode = self._external_sentinel("valheimsuite-cleanup-fail-")

        with _substitute_every_verified_temp_entry(metadata, external), _fail_final_cleanup_unlink(
            target.name, occurrence=2
        ):
            with self.assertRaises(metadata.MetadataError) as ctx:
                metadata.atomic_write_text(target, "new generated text")

        self.assertNotIsInstance(ctx.exception, PermissionError)
        self._assert_sentinel_untouched(external, mode)


class RetainedFinalReadTests(unittest.TestCase):
    """`_copy_retained_final()` must read exactly the captured length from
    the retained FD -- a single `pread()` may legally return fewer bytes
    than requested -- and must never silently accept a short/truncated
    read as complete."""

    def _make_source_dest(self, content: bytes) -> tuple[Path, Path]:
        tmp = tempfile.mkdtemp(prefix="valheimsuite-retained-read-")
        source = Path(tmp) / "source"
        source.write_bytes(content)
        dest = Path(tmp) / "dest"
        dest.touch()
        return source, dest

    def test_short_first_read_completes_on_subsequent_reads(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        content = os.urandom(24347)
        source, dest = self._make_source_dest(content)
        real_pread = os.pread
        calls = {"count": 0}

        def short_first(fd, n, offset):
            calls["count"] += 1
            if calls["count"] == 1:
                return real_pread(fd, min(n, 12173), offset)
            return real_pread(fd, n, offset)

        source_fd = os.open(source, os.O_RDONLY)
        dest_fd = os.open(dest, os.O_WRONLY)
        try:
            with mock.patch("os.pread", side_effect=short_first):
                metadata._copy_retained_final(source_fd, dest_fd, len(content), error_cls=metadata.MetadataError)
        finally:
            os.close(source_fd)
            os.close(dest_fd)
        self.assertGreater(calls["count"], 1)
        self.assertEqual(content, dest.read_bytes())

    def test_premature_eof_raises_and_never_reports_success(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        content = os.urandom(4096)
        source, dest = self._make_source_dest(content)
        real_pread = os.pread
        calls = {"count": 0}

        def truncated(fd, n, offset):
            calls["count"] += 1
            if calls["count"] == 1:
                return real_pread(fd, min(n, 1024), offset)
            return b""

        source_fd = os.open(source, os.O_RDONLY)
        dest_fd = os.open(dest, os.O_WRONLY)
        try:
            with mock.patch("os.pread", side_effect=truncated):
                with self.assertRaises(metadata.MetadataError):
                    metadata._copy_retained_final(
                        source_fd, dest_fd, len(content), error_cls=metadata.MetadataError
                    )
        finally:
            os.close(source_fd)
            os.close(dest_fd)
        self.assertNotEqual(content, dest.read_bytes())

    def test_empty_file_restores_correctly(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        source, dest = self._make_source_dest(b"")
        source_fd = os.open(source, os.O_RDONLY)
        dest_fd = os.open(dest, os.O_WRONLY)
        try:
            metadata._copy_retained_final(source_fd, dest_fd, 0, error_cls=metadata.MetadataError)
        finally:
            os.close(source_fd)
            os.close(dest_fd)
        self.assertEqual(b"", dest.read_bytes())

    def test_large_file_copies_exactly_via_chunked_reads(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        content = os.urandom(3 * 1024 * 1024 + 17)
        source, dest = self._make_source_dest(content)
        source_fd = os.open(source, os.O_RDONLY)
        dest_fd = os.open(dest, os.O_WRONLY)
        try:
            metadata._copy_retained_final(source_fd, dest_fd, len(content), error_cls=metadata.MetadataError)
        finally:
            os.close(source_fd)
            os.close(dest_fd)
        self.assertEqual(content, dest.read_bytes())


class PackageCleanupOrderingTests(unittest.TestCase):
    def test_non_regular_candidate_rejected_before_deleting_other_candidates(self):
        root = copy_template_to_temp()
        metadata, pkg = _import_scripts_from(root / "scripts")
        pkg.OUT.mkdir(parents=True)
        old_zip = pkg.OUT / "old.zip"
        checksum = pkg.OUT / "SHA256SUMS"
        old_zip.write_bytes(b"old archive")
        checksum.write_bytes(b"old checksums")
        (pkg.OUT / "zzz-bad.zip").mkdir()

        parent, _name = metadata.open_confined_parent(checksum, error_cls=pkg.PackageError)
        real_scandir = os.scandir

        @contextlib.contextmanager
        def ordered_scandir(path):
            # Force the non-regular candidate to be discovered last, exactly
            # reproducing the report: a single-pass validate-then-delete
            # cleanup would already have removed the earlier, valid
            # candidates -- including SHA256SUMS -- before ever reaching it.
            with real_scandir(path) as it:
                yield sorted(it, key=lambda entry: entry.name)

        try:
            with mock.patch("os.scandir", side_effect=ordered_scandir):
                with self.assertRaises(pkg.PackageError):
                    pkg._clean_output_directory(parent)
        finally:
            parent.close()

        self.assertEqual(b"old archive", old_zip.read_bytes())
        self.assertEqual(b"old checksums", checksum.read_bytes())
        self.assertTrue((pkg.OUT / "zzz-bad.zip").is_dir())


class WriteAllTests(unittest.TestCase):
    """Direct coverage for `_write_all()`: a single `os.write()` may
    legally write fewer bytes than requested (handled by looping), but a
    non-positive return makes no progress and must fail closed rather
    than being retried forever."""

    def test_short_writes_produce_the_exact_buffer(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        content = os.urandom(50000)
        real_write = os.write

        def short_write(fd, data):
            return real_write(fd, bytes(data)[:997])

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "dest"
            dest.touch()
            dest_fd = os.open(dest, os.O_WRONLY)
            try:
                with mock.patch("os.write", side_effect=short_write):
                    metadata._write_all(dest_fd, content, error_cls=metadata.MetadataError)
            finally:
                os.close(dest_fd)
            self.assertEqual(content, dest.read_bytes())

    def test_zero_progress_write_raises_instead_of_looping_forever(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "dest"
            dest.touch()
            dest_fd = os.open(dest, os.O_WRONLY)
            try:
                with mock.patch("os.write", return_value=0):
                    with self.assertRaises(metadata.MetadataError):
                        metadata._write_all(dest_fd, b"some recovery data", error_cls=metadata.MetadataError)
            finally:
                os.close(dest_fd)


class RecoveryZeroProgressWriteTests(unittest.TestCase):
    """Sol's end-to-end reproduction: primary promotion is defeated, an
    earlier recovery attempt installs a mismatched final entry, and the
    *next* recovery attempt's `os.write()` repeatedly returns 0. The
    operation must terminate with a controlled error and a safe final
    state instead of livelocking with the mismatched entry left in
    place. Run off the main thread with a bounded join so a regression
    back to an unbounded loop fails this test instead of hanging the
    whole suite."""

    def _external_sentinel(self, prefix: str) -> tuple[Path, int]:
        external = Path(tempfile.mkdtemp(prefix=prefix)) / "sentinel"
        external.write_bytes(b"external sentinel")
        external.chmod(0o640)
        return external, stat.S_IMODE(external.stat().st_mode)

    def _assert_sentinel_untouched(self, external: Path, mode: int) -> None:
        self.assertEqual(b"external sentinel", external.read_bytes())
        self.assertEqual(mode, stat.S_IMODE(external.stat().st_mode))

    def _run_case(self, metadata, target: Path, write, error_cls) -> None:
        primary_external, primary_mode = self._external_sentinel("valheimsuite-zero-write-primary-")
        recovery_external, recovery_mode = self._external_sentinel("valheimsuite-zero-write-recovery-")
        verify_targets = {1: primary_external, 2: recovery_external}
        real_write = os.write
        calls = {"count": 0}

        def counting_write(fd, data):
            calls["count"] += 1
            if calls["count"] == 1:
                return real_write(fd, data)
            return 0

        result: dict = {}

        def run():
            try:
                with _substitute_verified_temp_entries(metadata, verify_targets), mock.patch(
                    "os.write", side_effect=counting_write
                ):
                    write()
            except BaseException as exc:
                result["exception"] = exc

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(timeout=15)
        self.assertFalse(thread.is_alive(), "recovery hung instead of failing safely on a zero-progress write")

        self.assertIn("exception", result, "operation completed without raising a controlled error")
        self.assertIsInstance(result["exception"], error_cls)
        self._assert_sentinel_untouched(primary_external, primary_mode)
        self._assert_sentinel_untouched(recovery_external, recovery_mode)
        self.assertFalse(target.is_symlink())
        self.assertFalse(target.exists())

    def test_text_promotion_fails_safe_on_zero_progress_write_during_recovery(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "build" / "race.generated"
        target.parent.mkdir()
        target.write_bytes(b"existing generated text")
        self._run_case(
            metadata, target, lambda: metadata.atomic_write_text(target, "new generated text"), metadata.MetadataError
        )
        self.assertEqual([], list(target.parent.glob(".race.generated.*")))

    def test_zip_promotion_fails_safe_on_zero_progress_write_during_recovery(self):
        root = copy_template_to_temp()
        metadata, pkg = _import_scripts_from(root / "scripts")
        target = pkg.OUT / "race.zip"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing archive")
        self._run_case(
            metadata, target, lambda: pkg._write_package(target, [("safe.txt", b"payload")]), pkg.PackageError
        )
        self.assertEqual([], list(target.parent.iterdir()))

    def test_checksum_promotion_fails_safe_on_zero_progress_write_during_recovery(self):
        root = copy_template_to_temp()
        metadata, _pkg = _import_scripts_from(root / "scripts")
        target = root / "artifacts" / "packages" / "SHA256SUMS"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing checksums")
        self._run_case(
            metadata, target, lambda: metadata.atomic_write_text(target, "new checksums\n"), metadata.MetadataError
        )
        self.assertEqual([], list(target.parent.iterdir()))


if __name__ == "__main__":
    unittest.main()
