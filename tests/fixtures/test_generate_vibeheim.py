import stat
import sys
import unittest

from tests.fixtures._helpers import generate_into_temp


class GenerateVibeheimTests(unittest.TestCase):
    def test_vibeheim_generation_produces_expected_identity(self):
        params, output_dir, result = generate_into_temp(
            suite_name="Vibeheim",
            root_namespace="Vibeheim",
            plugin_guid_root="com.taibenvenuti.vibeheim",
            author="Tai Benvenuti",
            thunderstore_namespace="TaiBenvenuti",
        )
        self.assertTrue(result.ok, result.errors)

        preflight_mode = (output_dir / "scripts" / "preflight.py").stat().st_mode
        self.assertTrue(
            preflight_mode & stat.S_IXUSR,
            "generated scripts/preflight.py must be executable",
        )

        sln = (output_dir / "Vibeheim.sln").read_text(encoding="utf-8")
        for project in (
            "Vibeheim.Common",
            "Vibeheim.ServerCore",
            "Vibeheim.Client",
            "Vibeheim.Shared.Diagnostics",
        ):
            self.assertIn(f"src\\{project}\\{project}.csproj", sln)
            csproj = (output_dir / "src" / project / f"{project}.csproj").read_text(encoding="utf-8")
            self.assertIn(f"<AssemblyName>{project}</AssemblyName>", csproj)
        for project in ("Vibeheim.ServerCore", "Vibeheim.Client", "Vibeheim.Shared.Diagnostics"):
            plugin = (output_dir / "src" / project / "Plugin.cs").read_text(encoding="utf-8")
            self.assertIn(f"namespace {project};", plugin)
        self.assertIn("tests\\Vibeheim.Common.Tests\\Vibeheim.Common.Tests.csproj", sln)

        constants = (output_dir / "src/Vibeheim.Common/SuiteConstants.Generated.cs").read_text(encoding="utf-8")
        self.assertIn('"com.taibenvenuti.vibeheim"', constants)

        cfg_path = output_dir / "suite.config.json"
        sys.path.insert(0, str(output_dir / "scripts"))
        try:
            import importlib

            import package as generated_package

            importlib.reload(generated_package)
            import json
            dev_example = json.loads((output_dir / ".valheim/dev.json.example").read_text(encoding="utf-8"))
            self.assertEqual(2, dev_example["schemaVersion"])
            self.assertEqual("local", dev_example["server"]["deployment"]["type"])
            self.assertEqual("none", dev_example["server"]["lifecycle"]["type"])
            self.assertNotIn("serverPluginDir", dev_example)


            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            names = {name for name, _modules, _kind in generated_package.metadata.package_definitions(cfg)}
        finally:
            sys.path.remove(str(output_dir / "scripts"))
            sys.modules.pop("package", None)

        self.assertEqual(
            names,
            {
                "Vibeheim-ServerCore",
                "Vibeheim-Client",
                "Vibeheim-Shared-Diagnostics",
                "Vibeheim-ServerPack",
                "Vibeheim-ClientPack",
            },
        )


if __name__ == "__main__":
    unittest.main()
