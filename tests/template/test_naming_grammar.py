"""Regression tests for the generator-input / generated-code validity
issue: SemVer and Thunderstore-namespace grammars, bootstrap/generated
validator alignment, and the `check --release` gate.

Every test uses a disposable generated project (`generate_into_temp()`)
or a disposable copy of `template/` -- never the live template -- so a
pre-fix reproduction run can never contaminate this repository.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from bootstrap import naming
from bootstrap.create_project import generate
from tests.fixtures._helpers import copy_template_to_temp, generate_into_temp, import_scripts_from, make_params

NAMESPACE_CASES = [
    ("class", False),
    ("namespace.Tools", False),
    ("Example.class", False),
    ("Example", True),
    ("Example.Tools", True),
    ("_Private", True),
]

SEMVER_CASES = [
    # Original audit evidence.
    ("01.2.3", False),
    ("1.2.3-alpha..1", False),
    ("1.2.3-...", False),
    ("1.2.3-alpha+build.1", True),
    # Representative additional SemVer 2.0.0 syntax.
    ("1.02.3", False),
    ("1.2.03", False),
    ("1.2.3-alpha.01", False),
    ("1.2.3-", False),
    ("1.2.3+", False),
    ("0.1.0", True),
    ("1.2.3-alpha", True),
    ("1.2.3-alpha.1", True),
    ("1.2.3-0.3.7", True),
    ("1.2.3-x.7.z.92", True),
    ("1.2.3+build.1", True),
    ("1.2.3+001", True),
]

THUNDERSTORE_NAMESPACE_CASES = [
    ("Bad Name!", False),
    ("Bad Name", False),
    ("bad-name", False),
    ("bad.name", False),
    ("bad/name", False),
    ("bad\nname", False),
    ("", False),
    ("SampleNS", True),
    ("Sample_NS1", True),
    # Reviewer follow-up: edge characters must be alphanumeric, and the
    # namespace has an explicit 64-character maximum.
    ("Team", True),
    ("Team_One", True),
    ("Northern_Guild1", True),
    ("a" * 64, True),
    ("_Team", False),
    ("Team_", False),
    ("_", False),
    ("a" * 65, False),
    ("café", False),
]

AUTHOR_CASES = [
    ("Tai Benvenuti", True),
    ("Ünïcödé Authör", True),
    ("O'Brien & Sons \"Team\" <legit>", True),
    ("", False),
    ("has/slash", False),
    ("has\\backslash", False),
    ("Tai\nBenvenuti", False),
    ("Tai\tBenvenuti", False),
    # Reviewer follow-up: Unicode control/line/paragraph separators that
    # the old ASCII-only control check (`ord(ch) < 0x20 or ord(ch) ==
    # 0x7F`) let through.
    ("Tai\u0085Benvenuti", False),
    ("Tai\u009fBenvenuti", False),
    ("Tai\u2028Benvenuti", False),
    ("Tai\u2029Benvenuti", False),
    # Reviewer follow-up: `author` is emitted into `Suite.Generated.props`
    # (XML), so every accepted character must additionally be legal XML
    # 1.0 character data -- Cc/Zl/Zp alone does not exclude surrogates
    # (category `Cs`) or the U+FFFE/U+FFFF noncharacters (category `Cn`).
    ("Tai\ud800Benvenuti", False),
    ("Tai\udfffBenvenuti", False),
    ("Tai\ufffeBenvenuti", False),
    ("Tai\uffffBenvenuti", False),
    ("Tai\ufffdBenvenuti", True),
    ("Tai" + chr(0x1F600) + "Benvenuti", True),
]


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=cwd, text=True, capture_output=True)


def _load_cfg(project_dir: Path) -> dict:
    return json.loads((project_dir / "suite.config.json").read_text(encoding="utf-8"))


def _save_cfg(project_dir: Path, cfg: dict) -> None:
    (project_dir / "suite.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


class GeneratedSemverGrammarTests(unittest.TestCase):
    """Item 7/10: the generated project's own `validate_semver` must
    accept/reject exactly the SemVer 2.0.0 syntax the bootstrapper does."""

    def setUp(self):
        scripts_dir = copy_template_to_temp() / "scripts"
        self.metadata, _pkg = import_scripts_from(scripts_dir)

    def test_semver_syntax(self):
        for value, expected_ok in SEMVER_CASES:
            with self.subTest(value=value):
                if expected_ok:
                    self.metadata.validate_semver(value, "suiteVersion")
                else:
                    with self.assertRaises(self.metadata.MetadataError):
                        self.metadata.validate_semver(value, "suiteVersion")


class GeneratedThunderstoreNamespaceGrammarTests(unittest.TestCase):
    """Item 4/10: the generated project's own Thunderstore-namespace
    grammar must reject `Bad Name!` and accept the platform charset."""

    def setUp(self):
        scripts_dir = copy_template_to_temp() / "scripts"
        self.metadata, _pkg = import_scripts_from(scripts_dir)

    def test_thunderstore_namespace_charset(self):
        for value, expected_ok in THUNDERSTORE_NAMESPACE_CASES:
            with self.subTest(value=value):
                if expected_ok:
                    self.metadata.validate_thunderstore_namespace(value, "thunderstoreNamespace")
                else:
                    with self.assertRaises(self.metadata.MetadataError):
                        self.metadata.validate_thunderstore_namespace(value, "thunderstoreNamespace")


class GeneratedAuthorLabelGrammarTests(unittest.TestCase):
    """Item 3/10: the generated project's own display-label validator
    must reject Unicode control/line/paragraph separators in `author`."""

    def setUp(self):
        scripts_dir = copy_template_to_temp() / "scripts"
        self.metadata, _pkg = import_scripts_from(scripts_dir)

    def test_author_label_rejects_unicode_control_and_separators(self):
        for value, expected_ok in AUTHOR_CASES:
            with self.subTest(value=value):
                cfg = {"author": value}
                if expected_ok:
                    self.metadata.validate_label(cfg, "author")
                else:
                    with self.assertRaises(self.metadata.MetadataError):
                        self.metadata.validate_label(cfg, "author")


class GeneratorBoundaryXmlCharacterTests(unittest.TestCase):
    """Item 4: an author value that is invalid XML 1.0 character data
    must fail with the normal naming-validation error before the
    requested output directory is ever created -- never a
    `UnicodeEncodeError` or a downstream XML/MSBuild failure."""

    def _assert_generation_rejected_before_output_dir_exists(self, author: str) -> None:
        parent = Path(tempfile.mkdtemp(prefix="valheimsuite-xmlchar-boundary-"))
        output_dir = parent / "generated"  # deliberately not created yet
        params = make_params(author=author)
        with self.assertRaises(naming.NamingError):
            generate(params, output_dir)
        self.assertFalse(output_dir.exists())

    def test_rejects_author_with_u_fffe_before_creating_output_dir(self):
        self._assert_generation_rejected_before_output_dir_exists("Tai\ufffeBenvenuti")

    def test_rejects_author_with_u_ffff_before_creating_output_dir(self):
        self._assert_generation_rejected_before_output_dir_exists("Tai\uffffBenvenuti")

    def test_rejects_author_with_unpaired_surrogate_before_creating_output_dir(self):
        self._assert_generation_rejected_before_output_dir_exists("Tai\ud800Benvenuti")


class GeneratedSyncXmlCharacterTests(unittest.TestCase):
    """Item 5: the generated project's own `validate`/`sync` must reject
    XML-1.0-invalid author values and never write a corrupted
    `Suite.Generated.props` over the existing valid one."""

    def setUp(self):
        _params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        self.output_dir = output_dir
        self.metadata, _pkg = import_scripts_from(output_dir / "scripts")

    def test_validate_rejects_invalid_xml_author_values(self):
        cfg = json.loads((self.output_dir / "suite.config.json").read_text(encoding="utf-8"))
        for bad in ("Tai\ufffeBenvenuti", "Tai\uffffBenvenuti", "Tai\ud800Benvenuti"):
            with self.subTest(bad=bad):
                bad_cfg = dict(cfg, author=bad)
                with self.assertRaises(self.metadata.MetadataError):
                    self.metadata.validate(bad_cfg)

    def test_sync_leaves_generated_props_unchanged_when_author_is_invalid(self):
        props_path = self.output_dir / "build" / "Suite.Generated.props"
        before = props_path.read_bytes()
        cfg = json.loads((self.output_dir / "suite.config.json").read_text(encoding="utf-8"))
        for bad in ("Tai\ufffeBenvenuti", "Tai\uffffBenvenuti", "Tai\ud800Benvenuti"):
            with self.subTest(bad=bad):
                bad_cfg = dict(cfg, author=bad)
                with self.assertRaises(self.metadata.MetadataError):
                    self.metadata.sync(bad_cfg)
                self.assertEqual(before, props_path.read_bytes())


class GeneratedPropsXmlEscapingTests(unittest.TestCase):
    """Item 7: representative accepted author strings must round-trip
    correctly through XML escaping in the actually-generated
    `build/Suite.Generated.props`, verified with an independent XML
    parser (`xml.etree.ElementTree`, not the generator's own escaper)."""

    def _generated_author_text(self, author: str) -> str:
        _params, output_dir, result = generate_into_temp(author=author)
        self.assertTrue(result.ok, result.errors)
        tree = ET.parse(output_dir / "build" / "Suite.Generated.props")
        element = tree.getroot().find(".//SuiteAuthors")
        self.assertIsNotNone(element)
        return element.text

    def test_quotes_ampersands_and_angle_brackets_round_trip(self):
        author = "O'Brien & Sons \"Team\" <legit>"
        self.assertEqual(author, self._generated_author_text(author))

    def test_non_ascii_unicode_round_trips(self):
        author = "Ünïcödé Authör Renée"
        self.assertEqual(author, self._generated_author_text(author))


class BootstrapGeneratedGrammarAlignmentTests(unittest.TestCase):
    """Item 8: the same semantic field must not be accepted by one of
    the bootstrap-time (`bootstrap.naming`) and generated-project-time
    (`suite_metadata`) validators while rejected by the other."""

    def setUp(self):
        scripts_dir = copy_template_to_temp() / "scripts"
        self.metadata, _pkg = import_scripts_from(scripts_dir)

    def _accepts(self, fn, error_type, value: str) -> bool:
        try:
            fn(value, "field")
        except error_type:
            return False
        return True

    def test_namespace_alignment(self):
        for value, expected_ok in NAMESPACE_CASES:
            with self.subTest(value=value):
                self.assertEqual(expected_ok, self._accepts(naming.validate_namespace, naming.NamingError, value))
                self.assertEqual(
                    expected_ok, self._accepts(self.metadata.validate_namespace, self.metadata.MetadataError, value)
                )

    def test_semver_alignment(self):
        for value, expected_ok in SEMVER_CASES:
            with self.subTest(value=value):
                self.assertEqual(expected_ok, self._accepts(naming.validate_semver, naming.NamingError, value))
                self.assertEqual(
                    expected_ok, self._accepts(self.metadata.validate_semver, self.metadata.MetadataError, value)
                )

    def test_thunderstore_namespace_alignment(self):
        for value, expected_ok in THUNDERSTORE_NAMESPACE_CASES:
            with self.subTest(value=value):
                self.assertEqual(
                    expected_ok, self._accepts(naming.validate_thunderstore_namespace, naming.NamingError, value)
                )
                self.assertEqual(
                    expected_ok,
                    self._accepts(
                        self.metadata.validate_thunderstore_namespace, self.metadata.MetadataError, value
                    ),
                )

    def test_author_alignment(self):
        """The two implementations must agree, and each must independently
        match the expected accept/reject outcome (not merely each other)."""
        for value, expected_ok in AUTHOR_CASES:
            with self.subTest(value=value):
                bootstrap_ok = self._accepts(naming.validate_label, naming.NamingError, value)
                self.assertEqual(expected_ok, bootstrap_ok)
                try:
                    self.metadata.validate_label({"author": value}, "author")
                    generated_ok = True
                except self.metadata.MetadataError:
                    generated_ok = False
                self.assertEqual(expected_ok, generated_ok)


class SuiteNameLengthAlignmentTests(unittest.TestCase):
    """Item 5: scripts/deploy.py's deployment manifest filename embeds
    suiteName; the bootstrap-time and generated-project-time validators
    must agree on the same maximum length, so an oversized suiteName is
    always rejected at generation and never discovered later as a raw
    ENAMETOOLONG failure from deploy.py."""

    def setUp(self):
        scripts_dir = copy_template_to_temp() / "scripts"
        self.metadata, _pkg = import_scripts_from(scripts_dir)

    def test_constants_agree(self):
        self.assertEqual(naming.MAX_SUITE_NAME_LENGTH, self.metadata.MAX_SUITE_NAME_LENGTH)

    def test_generated_validator_accepts_suite_name_at_max_length(self):
        _params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        metadata, _pkg = import_scripts_from(output_dir / "scripts")
        cfg = json.loads((output_dir / "suite.config.json").read_text(encoding="utf-8"))
        cfg["suiteName"] = "S" * metadata.MAX_SUITE_NAME_LENGTH
        metadata.validate(cfg)

    def test_generated_validator_rejects_suite_name_over_max_length(self):
        _params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        metadata, _pkg = import_scripts_from(output_dir / "scripts")
        cfg = json.loads((output_dir / "suite.config.json").read_text(encoding="utf-8"))
        cfg["suiteName"] = "S" * (metadata.MAX_SUITE_NAME_LENGTH + 1)
        with self.assertRaises(metadata.MetadataError):
            metadata.validate(cfg)


class ReleaseGateTests(unittest.TestCase):
    """Item 9: `check --release` must reject invalid release metadata --
    reproducing the exact audit cases -- and accept representative valid
    metadata."""

    def setUp(self):
        params, output_dir, result = generate_into_temp(
            suite_name="Vibeheim",
            root_namespace="ExampleCompany.Vibeheim",
            plugin_guid_root="net.example-tests.vibeheim",
            author="Tai Benvenuti",
            thunderstore_namespace="TaiBenvenuti",
            suite_version="1.2.3-alpha+build.1",
        )
        self.assertTrue(result.ok, result.errors)
        self.output_dir = output_dir

    def test_valid_representative_metadata_passes_release_check(self):
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)

    def test_rejects_suite_name_dotdot(self):
        cfg = _load_cfg(self.output_dir)
        cfg["suiteName"] = ".."
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("suiteName", proc.stdout + proc.stderr)

    def test_rejects_newline_containing_author(self):
        cfg = _load_cfg(self.output_dir)
        cfg["author"] = "Tai\nBenvenuti"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("author", proc.stdout + proc.stderr)

    def test_rejects_thunderstore_namespace_bad_name(self):
        cfg = _load_cfg(self.output_dir)
        cfg["thunderstoreNamespace"] = "Bad Name!"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("thunderstoreNamespace", proc.stdout + proc.stderr)

    def test_rejects_malformed_semver(self):
        cfg = _load_cfg(self.output_dir)
        cfg["suiteVersion"] = "01.2.3"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("suiteVersion", proc.stdout + proc.stderr)

    def test_rejects_thunderstore_namespace_leading_underscore(self):
        cfg = _load_cfg(self.output_dir)
        cfg["thunderstoreNamespace"] = "_Team"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("thunderstoreNamespace", proc.stdout + proc.stderr)

    def test_rejects_thunderstore_namespace_trailing_underscore(self):
        cfg = _load_cfg(self.output_dir)
        cfg["thunderstoreNamespace"] = "Team_"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("thunderstoreNamespace", proc.stdout + proc.stderr)

    def test_rejects_thunderstore_namespace_over_max_length(self):
        cfg = _load_cfg(self.output_dir)
        cfg["thunderstoreNamespace"] = "a" * 65
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("thunderstoreNamespace", proc.stdout + proc.stderr)

    def test_accepts_thunderstore_namespace_at_max_length(self):
        cfg = _load_cfg(self.output_dir)
        cfg["thunderstoreNamespace"] = "a" * 64
        _save_cfg(self.output_dir, cfg)
        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertEqual(0, sync.returncode, sync.stdout + sync.stderr)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)

    def test_accepts_thunderstore_namespace_with_internal_underscore(self):
        cfg = _load_cfg(self.output_dir)
        cfg["thunderstoreNamespace"] = "Northern_Guild1"
        _save_cfg(self.output_dir, cfg)
        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertEqual(0, sync.returncode, sync.stdout + sync.stderr)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)

    def test_rejects_author_next_line(self):
        cfg = _load_cfg(self.output_dir)
        cfg["author"] = "Tai\u0085Benvenuti"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("author", proc.stdout + proc.stderr)

    def test_rejects_author_c1_control(self):
        cfg = _load_cfg(self.output_dir)
        cfg["author"] = "Tai\u009fBenvenuti"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("author", proc.stdout + proc.stderr)

    def test_rejects_author_line_separator(self):
        cfg = _load_cfg(self.output_dir)
        cfg["author"] = "Tai\u2028Benvenuti"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("author", proc.stdout + proc.stderr)

    def test_rejects_author_paragraph_separator(self):
        cfg = _load_cfg(self.output_dir)
        cfg["author"] = "Tai\u2029Benvenuti"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("author", proc.stdout + proc.stderr)

    def test_accepts_unicode_author_and_ordinary_spaces(self):
        cfg = _load_cfg(self.output_dir)
        cfg["author"] = "Ünïcödé Authör O'Brien & Sons"
        _save_cfg(self.output_dir, cfg)
        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertEqual(0, sync.returncode, sync.stdout + sync.stderr)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)

    def test_rejects_author_u_fffe(self):
        cfg = _load_cfg(self.output_dir)
        cfg["author"] = "Tai\ufffeBenvenuti"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("author", proc.stdout + proc.stderr)

    def test_rejects_author_u_ffff(self):
        cfg = _load_cfg(self.output_dir)
        cfg["author"] = "Tai\uffffBenvenuti"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("author", proc.stdout + proc.stderr)

    def test_rejects_author_unpaired_surrogate(self):
        """The surrogate never travels as a subprocess argument -- only
        `_save_cfg`'s `json.dumps(..., ensure_ascii=True)` (a `\\ud800`
        text escape, not raw UTF-8 bytes of the surrogate) writes it to
        `suite.config.json`, which the CLI reads as a file. Passing a
        lone surrogate directly as a subprocess argv value is not
        reliable (`str.encode("utf-8")` raises `UnicodeEncodeError`), so
        that path is intentionally not exercised here."""
        cfg = _load_cfg(self.output_dir)
        cfg["author"] = "Tai\ud800Benvenuti"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check", "--release"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("author", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
