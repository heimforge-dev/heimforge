import unittest

from tests.fixtures._helpers import generate_into_temp


class GenerateDefaultTests(unittest.TestCase):
    def test_default_generation_validates_cleanly(self):
        params, output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        self.assertTrue((output_dir / f"{params.root_namespace}.sln").is_file())

    def test_bootstrapper_attribution_survives_validation(self):
        _params, output_dir, result = generate_into_temp()
        readme = (output_dir / "README.md").read_text(encoding="utf-8")
        self.assertIn("ValheimSuite Bootstrap", readme)
        self.assertTrue(result.ok, result.errors)


if __name__ == "__main__":
    unittest.main()
