"""Regression coverage for Critical Finding #2: rendering must only ever
consume the explicit `bootstrap/template_manifest.py` surface, never an
unrestricted walk of `template/`'s filesystem contents.

Every injection test below mutates a private `copy_template_to_temp()`
copy, never the bootstrapper's own `template/` directory.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap import render, template_manifest
from bootstrap.render import validate_template
from bootstrap.template_manifest import OPTIONAL_TEMPLATE_FILES, REQUIRED_TEMPLATE_FILES, all_template_files, validate_manifest_structure
from bootstrap.validate_generated import NO_BYTECODE_ENV
from tests.fixtures._helpers import copy_template_to_temp, generate_into_temp


class TemplateManifestCompletenessTests(unittest.TestCase):
    def test_every_manifest_file_exists_in_the_real_template(self):
        self.assertEqual([], validate_template())

    def test_deleting_a_required_file_fails_validation(self):
        template_dir = copy_template_to_temp()
        (template_dir / "AGENTS.md").unlink()

        errors = validate_template(template_dir)

        self.assertTrue(
            any("missing required template file: AGENTS.md" in e for e in errors), errors
        )

    def test_renaming_a_required_file_fails_validation(self):
        template_dir = copy_template_to_temp()
        (template_dir / "README.md").rename(template_dir / "README.renamed.md")

        errors = validate_template(template_dir)

        self.assertTrue(any("missing required template file: README.md" in e for e in errors), errors)
        self.assertTrue(
            any("unexpected file not listed in the template manifest: README.renamed.md" in e for e in errors),
            errors,
        )


class UnexpectedTemplateFileTests(unittest.TestCase):
    def test_arbitrary_unexpected_file_fails_validation(self):
        """The manifest is the authority, not a blacklist: an innocuous file
        with no dangerous name must still fail validation for the sole
        reason that it isn't in the manifest."""
        template_dir = copy_template_to_temp()
        (template_dir / "unexpected.txt").write_text("not part of the template\n", encoding="utf-8")

        errors = validate_template(template_dir)

        self.assertTrue(
            any(e == "unexpected file not listed in the template manifest: unexpected.txt" for e in errors), errors
        )

    def test_ignored_python_cache_fails_validation(self):
        template_dir = copy_template_to_temp()
        cache_dir = template_dir / "scripts" / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "example.pyc").write_bytes(b"\x00\x01\x02")

        errors = validate_template(template_dir)

        self.assertTrue(
            any(
                "template must not contain a Python bytecode cache directory: scripts/__pycache__/example.pyc" in e
                for e in errors
            ),
            errors,
        )

    def test_dot_env_fails_validation(self):
        template_dir = copy_template_to_temp()
        (template_dir / ".env").write_text("SECRET_TOKEN=abc123\n", encoding="utf-8")

        errors = validate_template(template_dir)

        self.assertTrue(any("template must not contain a local .env file: .env" in e for e in errors), errors)

    def test_local_environment_props_fails_validation(self):
        template_dir = copy_template_to_temp()
        (template_dir / "Environment.props").write_text(
            '<Project><PropertyGroup><ValheimPath>C:\\local\\path</ValheimPath></PropertyGroup></Project>\n',
            encoding="utf-8",
        )

        errors = validate_template(template_dir)

        self.assertTrue(
            any(
                "template must not contain local Valheim/Jotunn developer configuration: Environment.props" in e
                for e in errors
            ),
            errors,
        )

    def test_local_dev_json_fails_validation(self):
        template_dir = copy_template_to_temp()
        local_config = template_dir / ".valheim" / "dev.json"
        local_config.write_text(
            '{"valheimPath": "/local/valheim"}\n',
            encoding="utf-8",
        )

        errors = validate_template(template_dir)

        self.assertTrue(
            any(
                "template must not contain local Valheim/Jotunn developer configuration: .valheim/dev.json" in e
                for e in errors
            ),
            errors,
        )

    def test_build_output_fails_validation(self):
        for relative in ("bin/Debug/Plugin.dll", "obj/Debug/Plugin.deps.json", "artifacts/publish/Plugin.dll"):
            with self.subTest(relative=relative):
                template_dir = copy_template_to_temp()
                target = template_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"fake build output")

                errors = validate_template(template_dir)

                self.assertTrue(
                    any("template must not contain a build output directory" in e and relative in e for e in errors),
                    errors,
                )

    def test_game_runtime_dll_fails_validation(self):
        template_dir = copy_template_to_temp()
        (template_dir / "ValheimSuite.Common.dll").write_bytes(b"MZ\x90\x00fake pe header")

        errors = validate_template(template_dir)

        self.assertTrue(
            any(
                "template must not contain a game/publicized assembly or runtime binary: ValheimSuite.Common.dll" in e
                for e in errors
            ),
            errors,
        )


class TemplateManifestOptionalModuleTests(unittest.TestCase):
    def test_all_template_files_is_the_union_of_required_and_optional(self):
        from bootstrap.template_manifest import OPTIONAL_TEMPLATE_FILES

        expected = set(REQUIRED_TEMPLATE_FILES)
        for paths in OPTIONAL_TEMPLATE_FILES.values():
            expected |= paths
        self.assertEqual(expected, all_template_files())



class SymlinkSourceSafetyTests(unittest.TestCase):
    """`validate_template()` must not rely on `Path.is_file()` for an
    approved path: it follows symlinks, so a symlink substituted for an
    approved file (or one of its parent directories) would otherwise pass
    as if it were the real, physically-contained file."""

    def test_approved_file_replaced_by_symlink_fails_validation(self):
        template_dir = copy_template_to_temp()
        external = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-external-")) / "external.md"
        external.write_text("external sentinel content\n", encoding="utf-8")
        readme = template_dir / "README.md"
        readme.unlink()
        readme.symlink_to(external)

        errors = validate_template(template_dir)

        self.assertTrue(any("README.md" in e for e in errors), errors)
        # Must not be reported as merely missing -- it physically exists,
        # it just isn't a plain file contained beneath the template root.
        self.assertFalse(any("missing required template file: README.md" in e for e in errors), errors)

    def test_approved_file_beneath_symlinked_directory_fails_validation(self):
        template_dir = copy_template_to_temp()
        external_root = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-external-"))
        shutil.copytree(template_dir / "src", external_root / "src")
        real_src = template_dir / "src"
        shutil.rmtree(real_src)
        real_src.symlink_to(external_root / "src")

        errors = validate_template(template_dir)

        self.assertTrue(any(e.startswith("template source path is not a plain file") and "src/" in e for e in errors), errors)


class ManifestStructuralValidationTests(unittest.TestCase):
    """Production validation must enforce manifest path syntax itself,
    not merely trust that the checked-in manifest happens to be correct."""

    def test_real_manifest_has_no_structural_errors(self):
        self.assertEqual([], validate_manifest_structure())

    def test_parent_traversal_is_rejected(self):
        with mock.patch.object(template_manifest, "REQUIRED_TEMPLATE_FILES", frozenset({"../outside.txt"})):
            errors = validate_manifest_structure()
        self.assertTrue(any("../outside.txt" in e for e in errors), errors)

    def test_absolute_path_is_rejected(self):
        with mock.patch.object(template_manifest, "REQUIRED_TEMPLATE_FILES", frozenset({"/etc/passwd"})):
            errors = validate_manifest_structure()
        self.assertTrue(any("/etc/passwd" in e for e in errors), errors)

    def test_dot_component_is_rejected(self):
        with mock.patch.object(template_manifest, "REQUIRED_TEMPLATE_FILES", frozenset({"./foo.txt"})):
            errors = validate_manifest_structure()
        self.assertTrue(any("foo.txt" in e for e in errors), errors)

    def test_backslash_path_is_rejected(self):
        with mock.patch.object(template_manifest, "REQUIRED_TEMPLATE_FILES", frozenset({"src\\Foo.cs"})):
            errors = validate_manifest_structure()
        self.assertTrue(any("Foo.cs" in e for e in errors), errors)

    def test_required_optional_overlap_is_rejected(self):
        with mock.patch.object(
            template_manifest, "REQUIRED_TEMPLATE_FILES", frozenset({"AGENTS.md"})
        ), mock.patch.object(template_manifest, "OPTIONAL_TEMPLATE_FILES", {"server_core": frozenset({"AGENTS.md"})}):
            errors = validate_manifest_structure()
        self.assertTrue(any("AGENTS.md" in e for e in errors), errors)

    def test_cross_optional_overlap_is_rejected(self):
        with mock.patch.object(
            template_manifest,
            "OPTIONAL_TEMPLATE_FILES",
            {"server_core": frozenset({"shared.cs"}), "client": frozenset({"shared.cs"})},
        ):
            errors = validate_manifest_structure()
        self.assertTrue(any("shared.cs" in e for e in errors), errors)

    def test_structural_errors_surface_through_validate_template(self):
        with mock.patch.object(template_manifest, "REQUIRED_TEMPLATE_FILES", frozenset({"../outside.txt"})):
            errors = validate_template()
        self.assertTrue(any("../outside.txt" in e for e in errors), errors)


class UnexpectedDirectoryTests(unittest.TestCase):
    def test_unexpected_empty_directory_fails_validation(self):
        template_dir = copy_template_to_temp()
        (template_dir / "empty_rogue_dir").mkdir()

        errors = validate_template(template_dir)

        self.assertTrue(any("empty_rogue_dir" in e for e in errors), errors)


@unittest.skipUnless(shutil.which("git"), "git required to verify generated ignore behavior")
class GeneratedScaffoldLocalConfigTests(unittest.TestCase):
    def test_ignored_local_configuration_passes_and_tracked_configuration_fails(self):
        _params, project, result = generate_into_temp()
        self.addCleanup(shutil.rmtree, project)
        self.assertTrue(result.ok, result.errors)

        environment_props = project / "Environment.props"
        environment_props.write_text("<Project />\n", encoding="utf-8")
        dev_config = project / ".valheim" / "dev.json"
        dev_config.parent.mkdir(exist_ok=True)
        dev_config.write_text("{}\n", encoding="utf-8")

        initialized = subprocess.run(
            ["git", "init", "--quiet"],
            cwd=project,
            env=NO_BYTECODE_ENV,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)

        scaffold = [sys.executable, "-m", "unittest", "discover", "-s", "tests/scaffold", "-p", "test_*.py"]
        ignored = subprocess.run(
            scaffold,
            cwd=project,
            env=NO_BYTECODE_ENV,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, ignored.returncode, ignored.stdout + ignored.stderr)

        tracked = subprocess.run(
            ["git", "add", "--force", "--", "Environment.props", ".valheim/dev.json"],
            cwd=project,
            env=NO_BYTECODE_ENV,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, tracked.returncode, tracked.stdout + tracked.stderr)

        rejected = subprocess.run(
            scaffold,
            cwd=project,
            env=NO_BYTECODE_ENV,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("must not be tracked", rejected.stdout + rejected.stderr)


class ManifestIndependentSanityTests(unittest.TestCase):
    """These paths are hand-curated here, independent of
    `bootstrap/template_manifest.py`'s own source, so a change that
    accidentally deletes a legitimate path from both the manifest and
    `template/` at once doesn't automatically make every other test agree
    with itself. Update this list deliberately when the manifest changes.
    """

    _CURATED_REQUIRED_PATHS = frozenset(
        {
            "AGENTS.md",
            "README.md",
            "CHANGELOG.md",
            ".gitignore",
            ".editorconfig",
            "Directory.Build.props",
            "Directory.Packages.props",
            "scripts/suite_metadata.py",
            "scripts/preflight.py",
            "scripts/package.py",
            "scripts/dev_config.py",
            "scripts/remote_deploy.py",
            "scripts/server_runtime.py",
            "scripts/refresh-references.sh",
            "scripts/update-game-stack.py",
            "tests/scaffold/test_scaffold.py",
            "src/__ROOT_NAMESPACE__.Common/__ROOT_NAMESPACE__.Common.csproj",
            "tests/__ROOT_NAMESPACE__.Common.Tests/__ROOT_NAMESPACE__.Common.Tests.csproj",
        }
    )
    _CURATED_OPTIONAL_PATHS = {
        "server_core": frozenset({"src/__ROOT_NAMESPACE__.ServerCore/Plugin.cs"}),
        "client": frozenset({"src/__ROOT_NAMESPACE__.Client/Plugin.cs"}),
        "shared_diagnostics": frozenset({"src/__ROOT_NAMESPACE__.Shared.Diagnostics/Plugin.cs"}),
        "server_package_docs": frozenset({"packaging/server/README.md"}),
        "client_package_docs": frozenset({"packaging/client/README.md"}),
    }

    def test_curated_required_paths_are_present_in_manifest_and_on_disk(self):
        for path in self._CURATED_REQUIRED_PATHS:
            self.assertIn(path, REQUIRED_TEMPLATE_FILES, f"{path} missing from REQUIRED_TEMPLATE_FILES")
            self.assertTrue((render.TEMPLATE_DIR / path).is_file(), f"{path} missing on disk")

    def test_curated_optional_paths_are_present_in_manifest_and_on_disk(self):
        for module, paths in self._CURATED_OPTIONAL_PATHS.items():
            for path in paths:
                self.assertIn(path, OPTIONAL_TEMPLATE_FILES[module], f"{path} missing from OPTIONAL_TEMPLATE_FILES[{module}]")
                self.assertTrue((render.TEMPLATE_DIR / path).is_file(), f"{path} missing on disk")


if __name__ == "__main__":
    unittest.main()
