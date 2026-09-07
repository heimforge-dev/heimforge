"""Regression coverage for `bootstrap/render.py`'s token grammar and for
rendering module-dependent passages against actual rendered output --
`token_map()` alone can hide a token whose *name* the renderer's own
regex cannot recognize (see `PROJECT_SPEC_MILESTONE2_BODY`, which
contains a digit and was silently left unrendered until `TOKEN_RE` was
widened to match it).
"""

import tempfile
import unittest
from pathlib import Path

from bootstrap.model import ProjectParams, build_model
from bootstrap.render import KNOWN_TOKENS, TOKEN_RE, render_tree


def make_params(**overrides) -> ProjectParams:
    defaults = dict(
        suite_name="Sampleheim",
        root_namespace="Sampleheim",
        plugin_guid_root="org.example-tests.sampleheim",
        author="Sample Author",
        thunderstore_namespace="SampleNS",
        suite_version="0.1.0",
    )
    defaults.update(overrides)
    return ProjectParams(**defaults)


def _render_project_spec(**overrides) -> str:
    model = build_model(make_params(**overrides))
    with tempfile.TemporaryDirectory() as raw_dir:
        output_dir = Path(raw_dir)
        render_tree(model, output_dir)
        return (output_dir / "docs" / "PROJECT_SPEC.md").read_text(encoding="utf-8")


class TokenRegexDigitSupportTests(unittest.TestCase):
    def test_token_names_containing_digits_are_recognized(self):
        self.assertEqual(["PROJECT_SPEC_MILESTONE2_BODY"], TOKEN_RE.findall("{{PROJECT_SPEC_MILESTONE2_BODY}}"))

    def test_unresolved_digit_token_is_detected(self):
        """The exact leftover-marker shape `validate_generated()`'s
        unresolved-token check must not silently pass through."""
        self.assertTrue(TOKEN_RE.search("still contains {{SOME2THING}} after rendering"))

    def test_token_name_must_still_start_with_a_letter_or_underscore(self):
        self.assertIsNone(TOKEN_RE.match("{{2LEADING_DIGIT}}"))

    def test_every_registered_token_name_matches_the_grammar(self):
        for name in KNOWN_TOKENS:
            with self.subTest(token=name):
                self.assertRegex(name, r"\A[A-Z_][A-Z0-9_]*\Z")


class ProjectSpecMilestone2RenderedOutputTests(unittest.TestCase):
    """Section 1/2: assert against the actual rendered file, not just
    `token_map()`'s dict entry."""

    def test_diagnostics_enabled_renders_diagnostics_body_with_no_raw_marker(self):
        text = _render_project_spec()
        self.assertNotIn("{{PROJECT_SPEC_MILESTONE2_BODY}}", text)
        self.assertIn(
            "Shared Diagnostics proves CustomRPC request/response, module/version reporting, and "
            "multiplayer plumbing without changing gameplay state.",
            text,
        )
        self.assertIsNone(TOKEN_RE.search(text))

    def test_diagnostics_disabled_renders_not_applicable_body_with_no_raw_marker(self):
        text = _render_project_spec(include_shared_diagnostics=False)
        self.assertNotIn("{{PROJECT_SPEC_MILESTONE2_BODY}}", text)
        self.assertIn("Not applicable: Shared.Diagnostics was not generated for this suite.", text)
        milestone_2 = text.split("### Milestone 2")[1].split("### Milestone 3")[0]
        self.assertNotIn("CustomRPC", milestone_2)
        self.assertIsNone(TOKEN_RE.search(text))


if __name__ == "__main__":
    unittest.main()
