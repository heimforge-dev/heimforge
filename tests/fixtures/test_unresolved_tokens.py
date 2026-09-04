import json
import tempfile
import unittest
from pathlib import Path

from bootstrap.model import build_model, suite_config_dict
from bootstrap.validate_generated import validate_generated
from tests.fixtures._helpers import make_params


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


if __name__ == "__main__":
    unittest.main()
