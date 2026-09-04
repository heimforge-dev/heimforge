import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.fixtures._helpers import generate_into_temp


class BootstrapperIndependenceTests(unittest.TestCase):
    def test_copied_generated_project_runs_its_own_preflight_standalone(self):
        _params, source_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)

        isolated_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-copy-"))
        shutil.rmtree(isolated_dir)
        shutil.copytree(source_dir, isolated_dir)

        proc = subprocess.run(
            [sys.executable, "scripts/preflight.py", "--portable", "--json"],
            cwd=isolated_dir,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
        report = json.loads(proc.stdout)
        self.assertTrue(report.get("ok"), report)


if __name__ == "__main__":
    unittest.main()
