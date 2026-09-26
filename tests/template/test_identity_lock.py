"""Regression tests for the metadata source-of-truth issue: `sync`/`check`
previously accepted a `suiteName` or `rootNamespace` edit that left the
repository's real identity (the `.sln` filename, project directories, C#
namespaces, and the deployment-manifest ownership identity) silently
pointing at the old value; accepted a non-integer `schemaVersion` (e.g.
`true`, since Python's `True == 1`); accepted a malformed/incomplete
`suite.identity.lock.json`; and dependency-version/`suiteVersion`/
`pluginGuidRoot` edits that `sync`/`check` accepted while README/context/
docs/changelog/module-catalog prose still showed the old bootstrap-time
literal.

Most scenarios exercise downstream generated-project behavior using private
`clone_generated_temp()` fixtures from certified seeds. The bootstrap/generated
lock parity case keeps real `generate_into_temp()` coverage. No test uses the
live `template/` tree.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from bootstrap.model import DEPENDENCY_BASELINE
from tests.fixtures._helpers import clone_generated_temp, generate_into_temp, import_scripts_from, run_deploy, write_dev_json, write_fake_artifacts

DEFAULT_DEPENDENCY_BASELINE = {
    "jotunnVersion": DEPENDENCY_BASELINE["jotunn_version"],
    "bepInExPackVersion": DEPENDENCY_BASELINE["bepinex_version"],
    "netFrameworkReferenceAssembliesVersion": DEPENDENCY_BASELINE["netfx_reference_version"],
}
STALE_DEPENDENCY_BASELINE = {"jotunnVersion": "2.29.2", "bepInExPackVersion": "5.4.2333", "netFrameworkReferenceAssembliesVersion": "1.0.3"}
NEW_DEPENDENCY_VERSIONS = {"jotunnVersion": "9.9.9", "bepInExPackVersion": "8.8.8", "netFrameworkReferenceAssembliesVersion": "7.7.7"}
RENDERED_DOCS = ("README.md", ".context/references/project.md", ".context/findings/valheim-runtime.md", ".context/state/current.md", "docs/dependencies.md", "docs/development.md")
DEPENDENCY_AUTHORITY_DOCS = (
    "README.md",
    ".context/references/project.md",
    "docs/dependencies.md",
    "docs/development.md",
)


def _load_cfg(project_dir: Path) -> dict:
    return json.loads((project_dir / "suite.config.json").read_text(encoding="utf-8"))


def _save_cfg(project_dir: Path, cfg: dict) -> None:
    (project_dir / "suite.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _load_lock(project_dir: Path) -> dict:
    return json.loads((project_dir / "suite.identity.lock.json").read_text(encoding="utf-8"))


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["python3", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _generated_snapshot(project_dir: Path, cfg: dict) -> dict[Path, bytes | None]:
    common = cfg["packages"]["commonModule"]
    paths = [
        project_dir / "build" / "Suite.Generated.props",
        project_dir / "packaging" / "profile-lock.json",
        project_dir / "src" / common / "SuiteConstants.Generated.cs",
        project_dir / "suite.identity.lock.json",
    ]
    return {path: (path.read_bytes() if path.is_file() else None) for path in paths}


class RootNamespaceAuditRegressionTests(unittest.TestCase):
    """Section 5: the exact original audit case -- edit `rootNamespace`,
    run `sync`, run `check` -- must now be rejected end to end, before any
    generated file is touched, and `Renamed.sln` must never be treated as
    real."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)

    def test_sync_and_check_reject_a_renamed_root_namespace(self) -> None:
        before = _generated_snapshot(self.output_dir, self.cfg)

        cfg = dict(self.cfg, rootNamespace="Renamed")
        _save_cfg(self.output_dir, cfg)

        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertNotEqual(0, sync.returncode, sync.stdout)
        self.assertIn("rootNamespace is immutable after generation", sync.stdout)
        self.assertIn(f"expected {self.params.root_namespace}", sync.stdout)
        self.assertIn("got Renamed", sync.stdout)

        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, check.returncode, check.stdout)
        self.assertIn("rootNamespace is immutable after generation", check.stdout)

        self.assertFalse((self.output_dir / "Renamed.sln").exists())
        self.assertTrue((self.output_dir / f"{self.params.root_namespace}.sln").exists())
        self.assertEqual(before, _generated_snapshot(self.output_dir, self.cfg))

    def test_build_script_never_targets_the_rejected_namespace(self) -> None:
        """Section 6: the original defect -- `build.sh` built `Renamed.sln`
        from the mutable config. `build.sh` must fail via `check` and must
        never derive a solution path from the rejected `rootNamespace`."""
        cfg = dict(self.cfg, rootNamespace="Renamed")
        _save_cfg(self.output_dir, cfg)

        build = subprocess.run(
            ["bash", "scripts/build.sh", "Debug"], cwd=self.output_dir, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.assertNotEqual(0, build.returncode)
        self.assertIn("rootNamespace is immutable after generation", build.stdout)

        test_run = subprocess.run(
            ["bash", "scripts/test.sh"], cwd=self.output_dir, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self.assertNotEqual(0, test_run.returncode)
        self.assertIn("rootNamespace is immutable after generation", test_run.stdout)

    def test_build_and_test_scripts_derive_solution_identity_from_the_lock_file(self) -> None:
        """`build.sh`/`test.sh` must read `rootNamespace` from
        `suite.identity.lock.json`, not `suite.config.json`, so a rejected
        edit can never become effective even if `check` were skipped."""
        cfg = dict(self.cfg, rootNamespace="Renamed")
        _save_cfg(self.output_dir, cfg)

        for script, expected_fragment in (
            ("build.sh", f"{self.params.root_namespace}.sln"),
            ("test.sh", f"tests/{self.params.root_namespace}.Common.Tests"),
        ):
            text = (self.output_dir / "scripts" / script).read_text(encoding="utf-8")
            match = re.search(r"python3 -c '([^']+)'", text)
            self.assertIsNotNone(match, script)
            self.assertIn("suite.identity.lock.json", match.group(1))
            self.assertNotIn("suite.config.json", match.group(1))
            derive = subprocess.run(["python3", "-c", match.group(1)], cwd=self.output_dir, text=True, capture_output=True)
            self.assertEqual(0, derive.returncode, derive.stderr)
            self.assertIn(expected_fragment, derive.stdout)
            self.assertNotIn("Renamed", derive.stdout)

    def test_package_rejects_a_renamed_root_namespace(self) -> None:
        """Section 14: an unauthorized identity edit must not let package
        names/paths silently diverge from repository structure."""
        cfg = dict(self.cfg, rootNamespace="Renamed")
        _save_cfg(self.output_dir, cfg)

        proc = _run(["scripts/package.py"], self.output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertIn("rootNamespace is immutable after generation", proc.stdout)
        self.assertFalse((self.output_dir / "artifacts").exists())


class DependencyVersionAuditRegressionTests(unittest.TestCase):
    """Section 7/15: the exact original audit case -- change all three
    dependency versions, run `sync`, run `check` -- must keep succeeding
    for these mutable fields, and every rendered doc/context file that
    used to embed the bootstrap-time literal must reflect the change (by
    no longer embedding a literal that can go stale)."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        for key, value in DEFAULT_DEPENDENCY_BASELINE.items():
            self.assertEqual(value, self.cfg[key], key)

    def test_sync_and_check_succeed_and_generated_outputs_use_the_new_versions(self) -> None:
        _save_cfg(self.output_dir, dict(self.cfg, **STALE_DEPENDENCY_BASELINE))
        cfg = dict(self.cfg, **NEW_DEPENDENCY_VERSIONS)
        _save_cfg(self.output_dir, cfg)

        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertEqual(0, sync.returncode, sync.stdout)
        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertEqual(0, check.returncode, check.stdout)

        props = (self.output_dir / "build" / "Suite.Generated.props").read_text(encoding="utf-8")
        lock = json.loads((self.output_dir / "packaging" / "profile-lock.json").read_text(encoding="utf-8"))
        for new_value in NEW_DEPENDENCY_VERSIONS.values():
            self.assertIn(new_value, props)
        self.assertEqual(NEW_DEPENDENCY_VERSIONS["jotunnVersion"], lock["dependencies"]["ValheimModding-Jotunn"])
        self.assertEqual(NEW_DEPENDENCY_VERSIONS["bepInExPackVersion"], lock["dependencies"]["denikson-BepInExPack_Valheim"])

    def test_rendered_docs_do_not_embed_mutable_dependency_baselines(self) -> None:
        _save_cfg(self.output_dir, dict(self.cfg, **STALE_DEPENDENCY_BASELINE))
        cfg = dict(self.cfg, **NEW_DEPENDENCY_VERSIONS)
        _save_cfg(self.output_dir, cfg)
        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertEqual(0, sync.returncode, sync.stdout)

        rendered_docs: dict[str, str] = {}
        for doc in RENDERED_DOCS:
            with self.subTest(doc=doc, invariant="no frozen dependency pins"):
                text = (self.output_dir / doc).read_text(encoding="utf-8")
                rendered_docs[doc] = text
                for value in (*STALE_DEPENDENCY_BASELINE.values(), *DEFAULT_DEPENDENCY_BASELINE.values()):
                    self.assertNotIn(value, text, f"{doc} embeds mutable dependency pin {value}")

        for doc in DEPENDENCY_AUTHORITY_DOCS:
            with self.subTest(doc=doc, invariant="dependency authority"):
                self.assertIn("suite.config.json", rendered_docs[doc])


class ImmutableIdentityMatrixTests(unittest.TestCase):
    """Section 16: table-driven coverage for every field this repository's
    metadata model classifies as generation-time identity/layout:
    `suiteName` and `rootNamespace` -- both locked in
    `suite.identity.lock.json` and iterated generically via
    `metadata.IMMUTABLE_IDENTITY_FIELDS` below, so this matrix covers
    both without hardcoding either. `pluginGuidRoot`/`author`/
    `thunderstoreNamespace`/dependency pins/`csharpLanguageVersion` are
    read dynamically or synchronized (see `docs/GENERATOR_ARCHITECTURE.md`),
    and `projects`/`packages` are independently validated against the
    files they claim to describe (see `tests/template/test_scope_membership.py`,
    `tests/template/test_solution_membership.py`, and
    `AbsoluteProjectPathTests`/`PackageWriteBoundaryTests` in
    `test_metadata_path_safety.py`, which already accept a *new*,
    physically-created project post-generation)."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        self.metadata, self.pkg = import_scripts_from(self.output_dir / "scripts")

    def test_generation_time_value_is_accepted(self) -> None:
        for field in self.metadata.IMMUTABLE_IDENTITY_FIELDS:
            with self.subTest(field=field):
                self.metadata.validate(self.cfg)
                self.metadata.validate_identity(self.cfg)  # must not raise

    def test_changed_value_is_rejected_by_validate_identity(self) -> None:
        for field in self.metadata.IMMUTABLE_IDENTITY_FIELDS:
            with self.subTest(field=field):
                cfg = dict(self.cfg, **{field: self.cfg[field] + "Changed"})
                with self.assertRaises(self.metadata.MetadataError):
                    self.metadata.validate_identity(cfg)

    def test_sync_rejects_before_any_mutation(self) -> None:
        before = _generated_snapshot(self.output_dir, self.cfg)
        for field in self.metadata.IMMUTABLE_IDENTITY_FIELDS:
            with self.subTest(field=field):
                cfg = dict(self.cfg, **{field: self.cfg[field] + "Changed"})
                _save_cfg(self.output_dir, cfg)
                proc = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
                self.assertNotEqual(0, proc.returncode, proc.stdout)
                self.assertEqual(before, _generated_snapshot(self.output_dir, self.cfg))
        _save_cfg(self.output_dir, self.cfg)

    def test_check_rejects(self) -> None:
        for field in self.metadata.IMMUTABLE_IDENTITY_FIELDS:
            with self.subTest(field=field):
                cfg = dict(self.cfg, **{field: self.cfg[field] + "Changed"})
                _save_cfg(self.output_dir, cfg)
                proc = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
                self.assertNotEqual(0, proc.returncode, proc.stdout)
        _save_cfg(self.output_dir, self.cfg)


class ErrorQualityTests(unittest.TestCase):
    """Section 18: an invalid *value* must be reported as a syntax error,
    not as an immutable-field change -- the two are different developer
    actions with different remedies."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        self.metadata, _pkg = import_scripts_from(self.output_dir / "scripts")

    def test_malformed_root_namespace_is_reported_as_invalid_syntax_not_immutable(self) -> None:
        cfg = dict(self.cfg, rootNamespace="not valid!!")
        with self.assertRaises(self.metadata.MetadataError) as ctx:
            self.metadata.validate(cfg)
        self.assertIn("must be a dot-separated sequence", str(ctx.exception))
        self.assertNotIn("immutable", str(ctx.exception))

    def test_valid_but_changed_root_namespace_is_reported_as_immutable(self) -> None:
        cfg = dict(self.cfg, rootNamespace="Renamed")
        self.metadata.validate(cfg, structural_only=True)  # syntactically fine
        with self.assertRaises(self.metadata.MetadataError) as ctx:
            self.metadata.validate_identity(cfg)
        message = str(ctx.exception)
        self.assertIn("immutable after generation", message)
        self.assertIn(self.params.root_namespace, message)
        self.assertIn("Renamed", message)
        self.assertIn("regenerate", message.lower())


class IdentityLockFileIntegrityTests(unittest.TestCase):
    """Section 3/4: a missing/corrupt/incomplete baseline must fail
    closed with a controlled `MetadataError`, never a raw exception, and
    user edits to `suite.config.json` can never redefine the baseline
    because `sync` never writes to it."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        self.lock_path = self.output_dir / "suite.identity.lock.json"

    def test_missing_lock_file_fails_closed(self) -> None:
        self.lock_path.unlink()
        proc = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("metadata error:", proc.stdout)
        self.assertIn("suite.identity.lock.json", proc.stdout)
        self.assertNotIn("Traceback", proc.stdout)

    def test_corrupt_lock_file_fails_closed(self) -> None:
        self.lock_path.write_text("not json", encoding="utf-8")
        proc = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("metadata error:", proc.stdout)
        self.assertNotIn("Traceback", proc.stdout)

    def test_lock_file_missing_required_field_fails_closed(self) -> None:
        self.lock_path.write_text(json.dumps({"schemaVersion": 1}), encoding="utf-8")
        proc = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("metadata error:", proc.stdout)

    def test_sync_never_rewrites_the_lock_file_to_match_an_unauthorized_edit(self) -> None:
        original = self.lock_path.read_bytes()
        cfg = dict(self.cfg, rootNamespace="Renamed")
        _save_cfg(self.output_dir, cfg)
        _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertEqual(original, self.lock_path.read_bytes())


class BootstrapAndGeneratedParityTests(unittest.TestCase):
    """Section 12: bootstrap-side generation and the generated project's
    own validation must agree on the baseline format and field set."""

    def test_lock_file_matches_bootstrap_identity_lock_dict(self) -> None:
        from bootstrap.model import build_model, identity_lock_dict

        params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        expected = identity_lock_dict(build_model(params))
        self.assertEqual(expected, _load_lock(output_dir))

        metadata, _pkg = import_scripts_from(output_dir / "scripts")
        self.assertEqual(set(expected) - {"schemaVersion"}, set(metadata.IMMUTABLE_IDENTITY_FIELDS))


class SuiteNameAuditRegressionTests(unittest.TestCase):
    """Section 1: `suiteName` is generation-time identity too -- a valid
    but changed name must be rejected by `sync`/`check`/`package.py`,
    before any generated file is touched. Rendered bootstrap-time
    `{{SUITE_NAME}}` labels correctly stay on the original name now."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)

    def test_sync_and_check_reject_a_renamed_suite_name(self) -> None:
        before = _generated_snapshot(self.output_dir, self.cfg)
        cfg = dict(self.cfg, suiteName="RenamedSuite")
        _save_cfg(self.output_dir, cfg)

        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertNotEqual(0, sync.returncode, sync.stdout)
        self.assertIn("suiteName is immutable after generation", sync.stdout)
        self.assertIn(f"expected {self.params.suite_name}", sync.stdout)
        self.assertIn("got RenamedSuite", sync.stdout)

        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, check.returncode, check.stdout)
        self.assertIn("suiteName is immutable after generation", check.stdout)
        self.assertEqual(before, _generated_snapshot(self.output_dir, self.cfg))

    def test_package_rejects_before_any_output(self) -> None:
        cfg = dict(self.cfg, suiteName="RenamedSuite")
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/package.py"], self.output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertIn("suiteName is immutable after generation", proc.stdout)
        self.assertFalse((self.output_dir / "artifacts").exists())

    def test_rendered_identity_labels_correctly_remain_on_the_original_name(self) -> None:
        """Once suiteName is immutable, README's `# {{SUITE_NAME}}` title
        (and similar bootstrap-time labels) are no longer stale
        derivatives -- they are the correct, permanent identity."""
        readme = (self.output_dir / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"# {self.params.suite_name}", readme)


class SuiteNameDeploymentOwnershipTests(unittest.TestCase):
    """Section 1/5: a `suiteName` edit must never let a suite start a
    second, unrelated deployment-manifest identity at a destination that
    already owns DLLs under the original name."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        write_dev_json(self.output_dir)
        write_fake_artifacts(self.output_dir, self.cfg)
        self.destination = Path(tempfile.mkdtemp(prefix="valheimsuite-suitename-deploy-"))

    def test_renamed_suite_name_cannot_create_a_second_ownership_manifest(self) -> None:
        first = run_deploy(self.output_dir, "server", destination=self.destination)
        self.assertEqual(0, first.returncode, first.stdout)
        old_manifest = self.destination / f".{self.params.suite_name}.deploy-manifest.json"
        self.assertTrue(old_manifest.is_file())
        before = {p.name: p.read_bytes() for p in self.destination.iterdir()}

        cfg = dict(self.cfg, suiteName="RenamedSuite")
        _save_cfg(self.output_dir, cfg)

        second = run_deploy(self.output_dir, "server", destination=self.destination)
        self.assertNotEqual(0, second.returncode, second.stdout)
        self.assertIn("suiteName is immutable after generation", second.stdout)

        self.assertFalse((self.destination / ".RenamedSuite.deploy-manifest.json").exists())
        after = {p.name: p.read_bytes() for p in self.destination.iterdir()}
        self.assertEqual(before, after)


class IdentityLockStrictSchemaTests(unittest.TestCase):
    """Section 2: `suite.identity.lock.json` is a closed, strictly-typed
    schema. A malformed lock is reported as a malformed *lock*, never
    misattributed to `suite.config.json`."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.lock_path = self.output_dir / "suite.identity.lock.json"
        self.original = json.loads(self.lock_path.read_text(encoding="utf-8"))

    def _write_lock_and_check(self, payload) -> subprocess.CompletedProcess:
        self.lock_path.write_text(json.dumps(payload), encoding="utf-8")
        return _run(["scripts/suite_metadata.py", "check"], self.output_dir)

    def _assert_malformed(self, proc: subprocess.CompletedProcess, *fragments: str) -> None:
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertIn("suite.identity.lock.json is malformed", proc.stdout)
        for fragment in fragments:
            self.assertIn(fragment, proc.stdout)

    def test_bool_schema_version_is_rejected(self) -> None:
        self._assert_malformed(self._write_lock_and_check({**self.original, "schemaVersion": True}), "schemaVersion")

    def test_float_schema_version_is_rejected(self) -> None:
        self._assert_malformed(self._write_lock_and_check({**self.original, "schemaVersion": 1.0}))

    def test_string_schema_version_is_rejected(self) -> None:
        self._assert_malformed(self._write_lock_and_check({**self.original, "schemaVersion": "1"}))

    def test_null_schema_version_is_rejected(self) -> None:
        self._assert_malformed(self._write_lock_and_check({**self.original, "schemaVersion": None}))

    def test_wrong_integer_schema_version_is_rejected(self) -> None:
        self._assert_malformed(self._write_lock_and_check({**self.original, "schemaVersion": 2}))

    def test_extra_field_is_rejected(self) -> None:
        self._assert_malformed(self._write_lock_and_check({**self.original, "extra": "field"}), "unexpected")

    def test_missing_field_is_rejected(self) -> None:
        incomplete = dict(self.original)
        del incomplete["suiteName"]
        self._assert_malformed(self._write_lock_and_check(incomplete), "missing")

    def test_invalid_suite_name_in_lock_is_reported_as_malformed_lock_not_config(self) -> None:
        proc = self._write_lock_and_check({**self.original, "suiteName": "../escaped"})
        self._assert_malformed(proc)
        self.assertNotIn("suite.config.json", proc.stdout)

    def test_invalid_root_namespace_in_lock_is_reported_as_malformed_lock(self) -> None:
        self._assert_malformed(self._write_lock_and_check({**self.original, "rootNamespace": "not valid!!"}))

    def test_non_object_root_is_rejected(self) -> None:
        self._assert_malformed(self._write_lock_and_check(["not", "an", "object"]))


class ConfigSchemaVersionStrictnessTests(unittest.TestCase):
    """Section 3: `suite.config.json`'s `schemaVersion` must be the exact
    JSON integer 1 -- Python's `True == 1` must not let a boolean pass."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        self.metadata, _pkg = import_scripts_from(self.output_dir / "scripts")

    def _assert_rejected(self, schema_version) -> None:
        cfg = dict(self.cfg, schemaVersion=schema_version)
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(cfg)
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertIn("schemaVersion must be the JSON integer 1", proc.stdout)

    def test_bool_schema_version_is_rejected(self) -> None:
        self._assert_rejected(True)

    def test_false_schema_version_is_rejected(self) -> None:
        self._assert_rejected(False)

    def test_float_schema_version_is_rejected(self) -> None:
        self._assert_rejected(1.0)

    def test_string_schema_version_is_rejected(self) -> None:
        self._assert_rejected("1")

    def test_null_schema_version_is_rejected(self) -> None:
        self._assert_rejected(None)

    def test_wrong_integer_schema_version_is_rejected(self) -> None:
        self._assert_rejected(2)

    def test_valid_int_schema_version_still_passes(self) -> None:
        self.metadata.validate(self.cfg)  # must not raise


class SuiteVersionChangelogTests(unittest.TestCase):
    """Section 4/17: `suiteVersion` stays mutable; the changelog heading
    stays a version-independent `## Unreleased` so a version bump never
    leaves a stale release heading in a package."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)

    def test_changed_version_passes_sync_and_check(self) -> None:
        cfg = dict(self.cfg, suiteVersion="0.2.0")
        _save_cfg(self.output_dir, cfg)
        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertEqual(0, sync.returncode, sync.stdout)
        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertEqual(0, check.returncode, check.stdout)

    def test_changelog_heading_is_version_independent(self) -> None:
        changelog = (self.output_dir / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## Unreleased", changelog)
        self.assertNotIn(self.cfg["suiteVersion"], changelog)

    def test_packaged_changelog_has_no_stale_bootstrap_version_after_a_bump(self) -> None:
        old_version = self.cfg["suiteVersion"]
        cfg = dict(self.cfg, suiteVersion="0.2.0")
        _save_cfg(self.output_dir, cfg)
        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertEqual(0, sync.returncode, sync.stdout)
        write_fake_artifacts(self.output_dir, cfg, configuration="Release")

        pkg = _run(["scripts/package.py"], self.output_dir)
        self.assertEqual(0, pkg.returncode, pkg.stdout)

        zips = sorted((self.output_dir / "artifacts" / "packages").glob("*.zip"))
        self.assertTrue(zips)
        for zip_path in zips:
            with self.subTest(zip=zip_path.name):
                self.assertIn("0.2.0", zip_path.name)
                self.assertNotIn(old_version, zip_path.name)
                with zipfile.ZipFile(zip_path) as zf:
                    changelog_text = zf.read("CHANGELOG.md").decode("utf-8")
                    self.assertIn("## Unreleased", changelog_text)
                    self.assertNotIn(old_version, changelog_text)
                    info = json.loads(zf.read("package-info.json"))
                    self.assertEqual("0.2.0", info["version"])


class PluginGuidRootModuleCatalogTests(unittest.TestCase):
    """Section 5/17: `pluginGuidRoot` stays mutable; `docs/module-catalog.md`
    must never retain a bootstrap-time-derived GUID after it changes."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)

    def test_changed_plugin_guid_root_passes_sync_and_check(self) -> None:
        cfg = dict(self.cfg, pluginGuidRoot="org.newroot.newsuite")
        _save_cfg(self.output_dir, cfg)
        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertEqual(0, sync.returncode, sync.stdout)
        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertEqual(0, check.returncode, check.stdout)

    def test_generated_guid_constant_updates(self) -> None:
        cfg = dict(self.cfg, pluginGuidRoot="org.newroot.newsuite")
        _save_cfg(self.output_dir, cfg)
        _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        common = self.cfg["packages"]["commonModule"]
        constants = (self.output_dir / "src" / common / "SuiteConstants.Generated.cs").read_text(encoding="utf-8")
        self.assertIn("org.newroot.newsuite", constants)
        self.assertNotIn(self.cfg["pluginGuidRoot"], constants)

    def test_module_catalog_never_embeds_a_literal_guid_from_generation(self) -> None:
        catalog = (self.output_dir / "docs" / "module-catalog.md").read_text(encoding="utf-8")
        self.assertNotIn(self.cfg["pluginGuidRoot"], catalog)
        self.assertIn("suite.config.json", catalog)

    def test_module_catalog_stays_free_of_the_old_guid_after_a_change(self) -> None:
        cfg = dict(self.cfg, pluginGuidRoot="org.newroot.newsuite")
        _save_cfg(self.output_dir, cfg)
        _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        catalog = (self.output_dir / "docs" / "module-catalog.md").read_text(encoding="utf-8")
        self.assertNotIn(self.cfg["pluginGuidRoot"], catalog)
        self.assertNotIn("org.newroot.newsuite", catalog)


if __name__ == "__main__":
    unittest.main()
