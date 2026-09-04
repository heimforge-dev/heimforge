import unittest

from tests.fixtures._helpers import generate_into_temp


class GenerateAlternateIdentityTests(unittest.TestCase):
    def test_dotted_namespace_and_omitted_client_are_generic_not_hardcoded(self):
        params, output_dir, result = generate_into_temp(
            suite_name="Skogtind",
            root_namespace="ExampleCompany.Skogtind",
            plugin_guid_root="net.example-mods.skogtind",
            author="Test Author",
            thunderstore_namespace="TestNS",
            suite_version="0.2.0",
            include_client=False,
        )
        self.assertTrue(result.ok, result.errors)

        sln = (output_dir / "ExampleCompany.Skogtind.sln").read_text(encoding="utf-8")
        self.assertIn("src\\ExampleCompany.Skogtind.Common\\ExampleCompany.Skogtind.Common.csproj", sln)
        self.assertIn("src\\ExampleCompany.Skogtind.ServerCore\\ExampleCompany.Skogtind.ServerCore.csproj", sln)
        self.assertIn(
            "src\\ExampleCompany.Skogtind.Shared.Diagnostics\\ExampleCompany.Skogtind.Shared.Diagnostics.csproj", sln
        )
        self.assertNotIn("Client", sln)
        self.assertFalse((output_dir / "src/ExampleCompany.Skogtind.Client").exists())

        import json

        cfg = json.loads((output_dir / "suite.config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["packages"]["clientOnlyModules"], [])


if __name__ == "__main__":
    unittest.main()
