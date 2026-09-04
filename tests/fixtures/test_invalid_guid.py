import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bootstrap import naming

ROOT = Path(__file__).resolve().parents[2]


class InvalidGuidTests(unittest.TestCase):
    def test_naming_validator_rejects_malformed_guid(self):
        with self.assertRaises(naming.NamingError):
            naming.validate_guid_root("NotAValidGuid!!")

    def test_cli_rejects_malformed_guid(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "bootstrap.create_project",
                "--name",
                "Sampleheim",
                "--guid",
                "NotAValidGuid!!",
                "--author",
                "Sample Author",
                "--thunderstore-namespace",
                "SampleNS",
                "--output",
                str(output_dir),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("pluginGuidRoot", result.stderr)
        self.assertFalse(any(output_dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
