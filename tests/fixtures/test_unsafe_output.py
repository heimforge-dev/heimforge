import tempfile
import unittest
from pathlib import Path

from bootstrap.create_project import GenerationError, _safe_output_dir, generate
from tests.fixtures._helpers import make_params


class UnsafeOutputTests(unittest.TestCase):
    def test_non_empty_output_is_refused_without_force(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        sentinel = output_dir / "pre-existing.txt"
        sentinel.write_text("do not touch", encoding="utf-8")

        with self.assertRaises(GenerationError):
            generate(make_params(), output_dir)

        self.assertTrue(sentinel.is_file())
        self.assertEqual("do not touch", sentinel.read_text(encoding="utf-8"))

    def test_non_empty_output_is_overwritten_with_force(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        (output_dir / "pre-existing.txt").write_text("stale", encoding="utf-8")

        result = generate(make_params(), output_dir, force=True)

        self.assertTrue(result.ok, result.errors)
        self.assertFalse((output_dir / "pre-existing.txt").exists())
        self.assertTrue((output_dir / "Sampleheim.sln").is_file())

    def test_safe_output_dir_rejects_root_and_home(self):
        for bad in ("/", "~"):
            with self.assertRaises(GenerationError):
                _safe_output_dir(bad)

    def test_safe_output_dir_rejects_bootstrapper_repository_and_ancestors(self):
        bootstrapper_root = Path(__file__).resolve().parents[2]
        for bad in (str(bootstrapper_root), "~/src", str(bootstrapper_root.parent)):
            with self.assertRaises(GenerationError):
                _safe_output_dir(bad)

    def test_safe_output_dir_accepts_sibling_directory(self):
        accepted = _safe_output_dir("~/src/vibeheim")
        self.assertEqual(Path.home() / "src" / "vibeheim", accepted)


if __name__ == "__main__":
    unittest.main()
