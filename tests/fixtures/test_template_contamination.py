"""End-to-end regression coverage for Critical Finding #2: a contaminated
source template must fail generation before any destination is touched,
and manifest-approved rendering must never let untracked/ignored/local/
symlinked template files -- or SDK build/validation artifacts -- reach
generated output.

Every test here renders from a private `copy_template_to_temp()` copy --
the bootstrapper's own `template/` directory is never mutated.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap import naming
from bootstrap.create_project import GenerationError, generate, main
from bootstrap.model import ModuleSpec, ProjectModel, ProjectParams, build_model
from bootstrap.render import REQUIRED_TEMPLATE_FILES, RenderError, render_tree
from tests.fixtures._helpers import copy_template_to_temp, expected_relpaths, generate_into_temp, make_params

EXTERNAL_SENTINEL = b"EXTERNAL SENTINEL CONTENT: must never appear in generated output\n"


def _generate_from_poisoned_template(output_dir: Path, template_dir: Path, *, force: bool = True):
    return generate(make_params(), output_dir, force=force, template_dir=template_dir)


class TemplateContaminationTests(unittest.TestCase):
    def test_ignored_python_cache_fails_generation_and_leaves_destination_untouched(self):
        template_dir = copy_template_to_temp()
        cache_dir = template_dir / "scripts" / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "example.pyc").write_bytes(b"\x00\x01\x02")

        # Non-empty destination + force=True: without force this would be
        # refused by output-directory authorization before ever reaching
        # template validation, which would prove nothing about the fix.
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        sentinel = output_dir / "pre-existing.txt"
        sentinel.write_bytes(b"do not touch")

        with self.assertRaises(GenerationError) as ctx:
            _generate_from_poisoned_template(output_dir, template_dir)

        self.assertIn("invalid template", str(ctx.exception))
        self.assertEqual(b"do not touch", sentinel.read_bytes())
        self.assertFalse((output_dir / "scripts" / "__pycache__").exists())

    def test_dot_env_never_reaches_generated_output(self):
        template_dir = copy_template_to_temp()
        (template_dir / ".env").write_text("SECRET_TOKEN=abc123\n", encoding="utf-8")

        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))

        with self.assertRaises(GenerationError) as ctx:
            _generate_from_poisoned_template(output_dir, template_dir)

        self.assertIn("invalid template", str(ctx.exception))
        self.assertFalse((output_dir / ".env").exists())
        self.assertEqual([], list(output_dir.iterdir()))

    def test_local_environment_props_rejected_before_rendering(self):
        template_dir = copy_template_to_temp()
        (template_dir / "Environment.props").write_text(
            '<Project><PropertyGroup><ValheimPath>C:\\local\\path</ValheimPath></PropertyGroup></Project>\n',
            encoding="utf-8",
        )

        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))

        with self.assertRaises(GenerationError) as ctx:
            _generate_from_poisoned_template(output_dir, template_dir)

        self.assertIn("invalid template", str(ctx.exception))
        self.assertFalse((output_dir / "Environment.props").exists())
        self.assertEqual([], list(output_dir.iterdir()))

    def test_build_output_rejected(self):
        template_dir = copy_template_to_temp()
        dll = template_dir / "bin" / "Debug" / "Plugin.dll"
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b"fake build output")

        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))

        with self.assertRaises(GenerationError) as ctx:
            _generate_from_poisoned_template(output_dir, template_dir)

        self.assertIn("invalid template", str(ctx.exception))
        self.assertEqual([], list(output_dir.iterdir()))

    def test_game_runtime_dll_never_reaches_generated_output(self):
        template_dir = copy_template_to_temp()
        (template_dir / "ValheimSuite.Common.dll").write_bytes(b"MZ\x90\x00fake pe header")

        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))

        with self.assertRaises(GenerationError) as ctx:
            _generate_from_poisoned_template(output_dir, template_dir)

        self.assertIn("invalid template", str(ctx.exception))
        self.assertFalse((output_dir / "ValheimSuite.Common.dll").exists())
        self.assertEqual([], list(output_dir.iterdir()))

    def test_unexpected_benign_file_is_rejected_not_silently_included(self):
        """The manifest is the authority, not a blacklist: a harmless file
        with no dangerous name must still block generation."""
        template_dir = copy_template_to_temp()
        (template_dir / "unexpected.txt").write_text("not part of the template\n", encoding="utf-8")

        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))

        with self.assertRaises(GenerationError) as ctx:
            _generate_from_poisoned_template(output_dir, template_dir)

        self.assertIn("invalid template", str(ctx.exception))
        self.assertEqual([], list(output_dir.iterdir()))

    def test_unexpected_empty_directory_is_rejected_not_silently_included(self):
        template_dir = copy_template_to_temp()
        (template_dir / "empty_rogue_dir").mkdir()

        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))

        with self.assertRaises(GenerationError) as ctx:
            _generate_from_poisoned_template(output_dir, template_dir)

        self.assertIn("invalid template", str(ctx.exception))
        self.assertEqual([], list(output_dir.iterdir()))


class TemplateSymlinkEscapeTests(unittest.TestCase):
    """A manifest-approved *name* is not enough: the physical file at that
    path must be a plain regular file contained beneath the template
    root. These prove a symlink substituted for an approved path -- or an
    approved path's parent directory -- cannot leak external content into
    a generated project."""

    def test_approved_file_replaced_by_external_symlink_never_leaks_content(self):
        template_dir = copy_template_to_temp()
        external_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-external-"))
        external = external_dir / "external.md"
        external.write_bytes(EXTERNAL_SENTINEL)
        readme = template_dir / "README.md"
        readme.unlink()
        readme.symlink_to(external)

        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))

        with self.assertRaises(GenerationError) as ctx:
            _generate_from_poisoned_template(output_dir, template_dir)

        self.assertIn("invalid template", str(ctx.exception))
        self.assertEqual([], list(output_dir.iterdir()))
        for f in output_dir.rglob("*"):
            if f.is_file():
                self.assertNotIn(EXTERNAL_SENTINEL, f.read_bytes())

    def test_approved_file_beneath_symlinked_directory_component_never_leaks_content(self):
        template_dir = copy_template_to_temp()
        external_root = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-external-"))
        shutil.copytree(template_dir / "src", external_root / "src")
        for csproj in external_root.rglob("*.csproj"):
            csproj.write_bytes(EXTERNAL_SENTINEL)
        real_src = template_dir / "src"
        shutil.rmtree(real_src)
        real_src.symlink_to(external_root / "src")

        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))

        with self.assertRaises(GenerationError) as ctx:
            _generate_from_poisoned_template(output_dir, template_dir)

        self.assertIn("invalid template", str(ctx.exception))
        self.assertEqual([], list(output_dir.iterdir()))
        for f in output_dir.rglob("*"):
            if f.is_file():
                self.assertNotIn(EXTERNAL_SENTINEL, f.read_bytes())


class RenderDestinationSafetyTests(unittest.TestCase):
    """`render_tree()` must refuse to write anything if the computed
    destination for a manifest source would escape the output root,
    collide with another source, or collide with a path `generate()`
    itself writes -- independent of whether `validate_params()` happened
    to run first."""

    def test_path_breaking_root_namespace_cannot_escape_the_output_root(self):
        params = ProjectParams(
            suite_name="Sampleheim",
            root_namespace="../../etc",
            plugin_guid_root="org.example-tests.sampleheim",
            author="A",
            thunderstore_namespace="NS",
        )
        model = ProjectModel(params, ModuleSpec("../../etc.Common", "common", "netstandard2.0", ""), None, None, None)
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))

        with self.assertRaises(RenderError):
            render_tree(model, output_dir)

        self.assertEqual([], list(output_dir.iterdir()))

    def test_duplicate_rendered_destination_is_rejected(self):
        params = make_params(root_namespace="Vibeheim", suite_name="Vibeheim")
        model = build_model(params)
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        colliding = frozenset({"src/Vibeheim.Common/Foo.cs", "src/__ROOT_NAMESPACE__.Common/Foo.cs"})

        with mock.patch("bootstrap.render.REQUIRED_TEMPLATE_FILES", colliding):
            with self.assertRaises(RenderError):
                render_tree(model, output_dir)

        self.assertEqual([], list(output_dir.iterdir()))

    def test_source_colliding_with_generated_suite_config_is_rejected(self):
        params = make_params()
        model = build_model(params)
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))

        with mock.patch("bootstrap.render.REQUIRED_TEMPLATE_FILES", frozenset({"suite.config.json"})):
            with self.assertRaises(RenderError):
                render_tree(model, output_dir)

        self.assertEqual([], list(output_dir.iterdir()))

    def test_source_colliding_with_generated_identity_lock_is_rejected(self):
        params = make_params()
        model = build_model(params)
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))

        with mock.patch("bootstrap.render.REQUIRED_TEMPLATE_FILES", frozenset({"suite.identity.lock.json"})):
            with self.assertRaises(RenderError):
                render_tree(model, output_dir)

        self.assertEqual([], list(output_dir.iterdir()))

    def test_real_manifest_never_triggers_the_render_plan_guards(self):
        """Sanity check that the guards above are defense-in-depth, not a
        false alarm against the actual shipped manifest."""
        for path in REQUIRED_TEMPLATE_FILES:
            self.assertNotIn("..", path.split("/"))


class DotnetStagingPurityTests(unittest.TestCase):
    """When a real .NET SDK is discoverable, `validate_generated()` runs
    `dotnet test`, which normally creates `bin/`/`obj/` wherever it's
    invoked. Those must never survive into the promoted project."""

    def test_exact_surface_generation_leaves_no_build_or_bytecode_artifacts_with_sdk_present(self):
        if shutil.which("dotnet") is None:
            self.skipTest("dotnet SDK not discoverable on PATH")

        params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)

        actual = {str(p.relative_to(output_dir)) for p in output_dir.rglob("*") if p.is_file()}
        self.assertEqual(expected_relpaths(params.root_namespace), actual)

        leaked_dirs = sorted(
            str(p.relative_to(output_dir))
            for p in output_dir.rglob("*")
            if p.is_dir() and p.name in ("bin", "obj", "__pycache__")
        )
        self.assertEqual([], leaked_dirs)
        self.assertEqual([], [str(p) for p in output_dir.rglob("*.pyc")])


class NormalGenerationSurfaceTests(unittest.TestCase):
    def test_default_generation_contains_exactly_the_expected_approved_files(self):
        params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)

        actual = {str(p.relative_to(output_dir)) for p in output_dir.rglob("*") if p.is_file()}
        self.assertEqual(expected_relpaths(params.root_namespace), actual)

    def test_all_seven_supported_optional_module_combinations_generate_the_correct_manifest_subset(self):
        for server_core in (True, False):
            for client in (True, False):
                for shared_diagnostics in (True, False):
                    if not (server_core or client or shared_diagnostics):
                        continue  # 000: no runtime module enabled -- rejected at bootstrap, covered separately.
                    with self.subTest(server_core=server_core, client=client, shared_diagnostics=shared_diagnostics):
                        params, output_dir, result = generate_into_temp(
                            include_server_core=server_core,
                            include_client=client,
                            include_shared_diagnostics=shared_diagnostics,
                        )
                        self.assertTrue(result.ok, result.errors)

                        actual = {str(p.relative_to(output_dir)) for p in output_dir.rglob("*") if p.is_file()}
                        expected = expected_relpaths(
                            params.root_namespace,
                            server_core=server_core,
                            client=client,
                            shared_diagnostics=shared_diagnostics,
                        )
                        self.assertEqual(expected, actual)


class EmptyRuntimeRejectionTests(unittest.TestCase):
    """Section 1/2: a bootstrap configuration with every optional runtime
    module disabled (000) must be rejected during model validation, before
    the output directory is ever created or mutated -- `--force` must not
    change that."""

    def test_all_modules_omitted_is_rejected_before_any_mutation(self):
        params = make_params(include_server_core=False, include_client=False, include_shared_diagnostics=False)
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-empty-runtime-"))
        shutil.rmtree(output_dir)

        with self.assertRaises(naming.NamingError) as ctx:
            generate(params, output_dir)
        self.assertIn("at least one runtime module", str(ctx.exception))
        self.assertFalse(output_dir.exists())

    def test_force_does_not_bypass_the_empty_runtime_rejection(self):
        params = make_params(include_server_core=False, include_client=False, include_shared_diagnostics=False)
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-empty-runtime-force-"))
        shutil.rmtree(output_dir)

        with self.assertRaises(naming.NamingError):
            generate(params, output_dir, force=True)
        self.assertFalse(output_dir.exists())

    def test_cli_rejects_all_modules_omitted_before_any_mutation(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-empty-runtime-cli-"))
        shutil.rmtree(output_dir)
        argv = [
            "--name", "Sampleheim",
            "--guid", "org.example-tests.sampleheim",
            "--author", "Sample Author",
            "--thunderstore-namespace", "SampleNS",
            "--output", str(output_dir),
            "--no-server-core",
            "--no-client",
            "--no-shared-diagnostics",
            "--force",
        ]
        returncode = main(argv)
        self.assertEqual(2, returncode)
        self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
