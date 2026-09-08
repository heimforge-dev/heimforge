"""Regression coverage for the OMP `valheim_inspect` assembly-confinement
issue: `template/.omp/extensions/valheim-dev/index.ts` must confine
`ilspycmd` to assemblies whose *canonical* filesystem target sits inside the
canonical `valheim_Data/Managed` directory, not merely inside it lexically.

The actual behavioral regression suite is a Bun test
(`tests/template/ts/valheim_inspect_confinement.test.ts`) that registers the
real extension tools, invokes `valheim_inspect` directly, and stubs
`ilspycmd` on PATH to record its exact argv -- see that file for the full
symlink-escape / traversal / prefix-collision / broken-symlink matrix. This
wrapper follows the existing `BunSyntaxCheckTests` convention
(tests/bootstrap/test_render_ts_escaping.py) of shelling out to `bun` from
the Python suite so `python -m unittest discover` still covers it.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

_TS_TEST = Path(__file__).resolve().parent / "ts" / "valheim_inspect_confinement.test.ts"


@unittest.skipUnless(shutil.which("bun"), "bun not available in this environment")
class ValheimInspectConfinementTests(unittest.TestCase):
    def test_bun_regression_suite_passes(self):
        self.assertTrue(_TS_TEST.is_file(), f"missing {_TS_TEST}")
        proc = subprocess.run(
            [shutil.which("bun"), "test", str(_TS_TEST)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
