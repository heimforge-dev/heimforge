import json
import tempfile
import unittest
from pathlib import Path

from bootstrap.create_project import generate
from bootstrap.model import build_model, suite_config_dict
from bootstrap.validate_generated import validate_generated
from tests.fixtures._helpers import copy_template_to_temp, generate_into_temp, make_params


class UnresolvedTokensTests(unittest.TestCase):
    def test_stray_token_marker_fails_validation(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        params = make_params()
        cfg = suite_config_dict(build_model(params))
        (output_dir / "suite.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        broken = output_dir / "NOTES.md"
        broken.write_text("still contains {{UNKNOWN}} after rendering", encoding="utf-8")

        result = validate_generated(output_dir, params)

        self.assertFalse(result.ok)
        self.assertTrue(any("NOTES.md" in e and "unresolved template token" in e for e in result.errors), result.errors)

    def test_malformed_marker_fails_validation(self):
        """`{{BAD1}}` (uppercase, digit-bearing) already matches
        `render.py`'s own `TOKEN_RE` and was already caught before this
        fix. The remaining shapes below do not -- `TOKEN_RE`-only
        detection let every one of them survive.

        `{{BAD}1}}` and `{{BAD{1}}}` are both malformed by exactly one
        stray interior brace after a token-like prefix (`UNRESOLVED_MARKER_RE`'s
        "no brace inside" class structurally cannot reach either shape).
        `{{BAD{1}}}` is deliberately rejected the same as `{{BAD}1}}`, not
        treated as legitimate nested interpolation syntax: scanning every
        generated file across all seven optional-module combinations
        turns up exactly one legitimate doubled-brace construct in any
        generated output (`scripts/suite_metadata.py`'s f-string escape
        for literal C# braces, covered by
        `test_legitimate_doubled_brace_source_survives_validation` below),
        and its `{{` is immediately followed by a literal backslash-n, not
        a token-like character -- nothing resembling `{{BAD{1}}}` exists in
        any real generated file.
        """
        params = make_params()
        cfg = suite_config_dict(build_model(params))
        markers = (
            "{{bad}}",
            "{{ BAD }}",
            "{{BROKEN-TOKEN}}",
            "{{123}}",
            "{{}}",
            "{{{BAD}}}",
            "{{BAD}}}",
            "{{{BAD}}",
            "{{BAD}1}}",
            "{{BAD{1}}}",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
                (output_dir / "suite.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
                (output_dir / "NOTES.md").write_text(f"still contains {marker} after rendering", encoding="utf-8")

                result = validate_generated(output_dir, params)

                self.assertFalse(result.ok)
                self.assertTrue(
                    any("NOTES.md" in e and "unresolved template token" in e for e in result.errors), result.errors
                )

    def test_legitimate_doubled_brace_source_survives_validation(self):
        """`scripts/suite_metadata.py`'s f-string brace-escape for
        generating `SuiteConstants.Generated.cs` is the one legitimate
        doubled-brace construct anywhere in generated output. Content
        validation must never flag it."""
        params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        metadata = (output_dir / "scripts" / "suite_metadata.py").read_text(encoding="utf-8")
        self.assertIn("{{", metadata)
        self.assertIn("}}", metadata)

    def test_marker_in_path_fails_validation(self):
        """Every adversarial marker form -- ordinary, malformed by one
        stray brace, or a bare unmatched delimiter -- has no legitimate
        brace syntax in a path at all, so path validation rejects any
        raw `{{`/`}}` outright rather than trying to parse marker shape."""
        params = make_params()
        cfg = suite_config_dict(build_model(params))
        filenames = (
            "{{BAD1}}.md",
            "{{bad}}.md",
            "{{BAD{1}}}.md",
            "{{BAD}1}}.md",
            "{{{BAD}}}.md",
            "{{BAD}}}.md",
            "{{{BAD}}.md",
            "foo}}bar.md",
            "foo{{bar.md",
        )
        for filename in filenames:
            with self.subTest(filename=filename):
                output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
                (output_dir / "suite.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
                (output_dir / "docs").mkdir()
                (output_dir / "docs" / filename).write_text("hello", encoding="utf-8")

                result = validate_generated(output_dir, params)

                self.assertFalse(result.ok)
                self.assertTrue(
                    any(filename in e and "unresolved template brace delimiter" in e for e in result.errors),
                    result.errors,
                )

    def test_marker_in_directory_name_fails_validation(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        params = make_params()
        cfg = suite_config_dict(build_model(params))
        (output_dir / "suite.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        leaked_dir = output_dir / "{{BAD}1}}"
        leaked_dir.mkdir()
        (leaked_dir / "file.bin").write_bytes(b"\x00\x01\xff")

        result = validate_generated(output_dir, params)

        self.assertFalse(result.ok)
        self.assertTrue(
            any("{{BAD}1}}" in e and "unresolved template brace delimiter" in e for e in result.errors),
            result.errors,
        )


class ValidationBeforePromotionTests(unittest.TestCase):
    def test_malformed_marker_blocks_promotion_and_preserves_destination(self):
        """A malformed marker only this fix's broader final-output check
        catches (`{{BAD}1}}`, invisible to `validate_template()`'s
        `TOKEN_RE`-based known-token check since it isn't shaped like a
        real token attempt) must still fail generation at the
        `validate_generated()` stage and never promote -- and a forced
        generation over a non-empty destination must leave that
        destination byte-identical."""
        template_dir = copy_template_to_temp()
        readme = template_dir / "README.md"
        readme.write_text(readme.read_text(encoding="utf-8") + "\nstill contains {{BAD}1}} after rendering\n", encoding="utf-8")

        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        sentinel = output_dir / "pre-existing.txt"
        sentinel.write_bytes(b"do not touch")

        result = generate(make_params(), output_dir, force=True, template_dir=template_dir)

        self.assertFalse(result.ok)
        self.assertTrue(any("unresolved template token" in e and "README.md" in e for e in result.errors), result.errors)
        self.assertEqual(b"do not touch", sentinel.read_bytes())
        self.assertEqual(["pre-existing.txt"], [p.name for p in output_dir.iterdir()])
        self.assertEqual([], list(output_dir.parent.glob(f".{output_dir.name}.*")))


if __name__ == "__main__":
    unittest.main()
