"""Regression tests for the generator-input / generated-code validity
issue: `.ts` template rendering must not rely solely on a token's input
grammar to stay syntactically valid (item 6) -- and the actually
generated OMP extension must be syntactically valid TypeScript (item 12).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from bootstrap.render import _substitute, _ts_string_escape
from tests.fixtures._helpers import generate_into_temp

# A value representative of the original bug report: embedded quote,
# newline, tab, and backslash -- any one of which breaks a naive
# double-quoted TS string literal if substituted in raw.
_DANGEROUS_VALUE = 'Bad"Name\nWith\tTabs\\Backslash\'Quote'


class TsStringEscapeTests(unittest.TestCase):
    def test_escape_round_trips_through_json_for_arbitrary_control_characters(self):
        escaped = _ts_string_escape(_DANGEROUS_VALUE)
        self.assertEqual(_DANGEROUS_VALUE, json.loads(f'"{escaped}"'))

    def test_substitute_without_escape_lets_a_dangerous_value_break_the_literal(self):
        """Reproduces the original bug: naive substitution embeds the raw
        value verbatim, so an embedded quote terminates the string literal
        early."""
        text = 'label: "Build {{SUITE_NAME}}"'
        rendered = _substitute(text, {"SUITE_NAME": 'Bad"Name'})
        self.assertEqual('label: "Build Bad"Name"', rendered)

    def test_substitute_with_ts_escape_keeps_the_literal_syntactically_valid(self):
        text = 'label: "Build {{SUITE_NAME}}"'
        rendered = _substitute(text, {"SUITE_NAME": _DANGEROUS_VALUE}, escape=_ts_string_escape)
        self.assertEqual('label: "Build ' + _ts_string_escape(_DANGEROUS_VALUE) + '"', rendered)
        body = rendered[len('label: "'):-1]
        self.assertEqual("Build " + _DANGEROUS_VALUE, json.loads(f'"{body}"'))


@unittest.skipUnless(shutil.which("bun"), "bun not available in this environment")
class BunSyntaxCheckTests(unittest.TestCase):
    """Independently confirms the escaping claim above by actually
    parsing the rendered text as TypeScript/JavaScript with `bun build`."""

    def _bun_build(self, source: str) -> subprocess.CompletedProcess:
        workdir = Path(tempfile.mkdtemp(prefix="ts-syntax-check-"))
        src = workdir / "check.ts"
        src.write_text(source, encoding="utf-8")
        return subprocess.run(
            [shutil.which("bun"), "build", str(src), "--outfile", str(workdir / "out.js")],
            capture_output=True,
            text=True,
        )

    def test_unescaped_dangerous_value_breaks_ts_syntax(self):
        text = 'const x: string = "Build {{SUITE_NAME}}";\nexport default x;\n'
        rendered = _substitute(text, {"SUITE_NAME": _DANGEROUS_VALUE})
        proc = self._bun_build(rendered)
        self.assertNotEqual(0, proc.returncode, "expected the unescaped literal to fail as TypeScript")

    def test_escaped_dangerous_value_is_valid_ts_and_preserves_the_value(self):
        text = 'const x: string = "Build {{SUITE_NAME}}";\nexport default x;\n'
        rendered = _substitute(text, {"SUITE_NAME": _DANGEROUS_VALUE}, escape=_ts_string_escape)
        proc = self._bun_build(rendered)
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)

    def test_generated_index_ts_is_syntactically_valid(self):
        """Item 12: the actually generated OMP extension, with
        representative non-trivial metadata, must be valid TypeScript."""
        _params, output_dir, result = generate_into_temp(
            suite_name="Vibeheim",
            root_namespace="ExampleCompany.Vibeheim",
            plugin_guid_root="net.example-tests.vibeheim",
            author="Tai Benvenuti",
            thunderstore_namespace="TaiBenvenuti",
            suite_version="1.2.3-alpha+build.1",
        )
        self.assertTrue(result.ok, result.errors)
        index_ts = output_dir / ".omp" / "extensions" / "valheim-dev" / "index.ts"
        self.assertTrue(index_ts.is_file())
        out_file = Path(tempfile.mkdtemp(prefix="ts-build-check-")) / "out.js"
        proc = subprocess.run(
            [
                shutil.which("bun"),
                "build",
                str(index_ts),
                "--outfile",
                str(out_file),
                "--external",
                "@oh-my-pi/pi-coding-agent",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
