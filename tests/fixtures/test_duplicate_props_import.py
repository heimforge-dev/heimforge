import json
import tempfile
import unittest
from pathlib import Path

from bootstrap.model import build_model, suite_config_dict
from bootstrap.validate_generated import SUITE_GENERATED_IMPORT_RE, validate_generated
from tests.fixtures._helpers import generate_into_temp, make_params


class DuplicatePropsImportTests(unittest.TestCase):
    def test_generated_template_imports_suite_generated_props_exactly_once(self):
        params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)

        importers = [
            name
            for name in ("Directory.Build.props", "Directory.Packages.props")
            if SUITE_GENERATED_IMPORT_RE.search((output_dir / name).read_text(encoding="utf-8"))
        ]
        self.assertEqual(["Directory.Build.props"], importers)

    def test_validate_generated_fails_when_both_props_files_import_it(self):
        params = make_params()
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        cfg = suite_config_dict(build_model(params))
        (output_dir / "suite.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        (output_dir / "Directory.Build.props").write_text(
            '<Project>\n  <Import Project="$(MSBuildThisFileDirectory)build/Suite.Generated.props" />\n</Project>\n',
            encoding="utf-8",
        )
        (output_dir / "Directory.Packages.props").write_text(
            '<Project>\n  <Import Project="$(MSBuildThisFileDirectory)build/Suite.Generated.props" />\n</Project>\n',
            encoding="utf-8",
        )

        result = validate_generated(output_dir, params)

        self.assertFalse(result.ok)
        self.assertTrue(any("imported by more than one" in e for e in result.errors), result.errors)


if __name__ == "__main__":
    unittest.main()
