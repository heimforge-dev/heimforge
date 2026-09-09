import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from bootstrap.model import build_model, suite_config_dict
from bootstrap.validate_generated import NO_BYTECODE_ENV, SUITE_GENERATED_IMPORT_RE, validate_generated
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


@unittest.skipUnless(shutil.which("dotnet"), "dotnet required for synthetic Jotunn runtime build")
class JotunnEnvironmentImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _params, cls.base, result = generate_into_temp()
        if not result.ok:
            raise AssertionError(result.errors)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.base)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(self.base, self.root)
        self.cfg = json.loads((self.root / "suite.config.json").read_text(encoding="utf-8"))

    def test_portable_preflight_and_common_tests_need_no_environment_props(self) -> None:
        self.assertFalse((self.root / "Environment.props").exists())
        preflight = subprocess.run(
            ["bash", "scripts/preflight.sh", "--portable", "--json"],
            cwd=self.root,
            env=NO_BYTECODE_ENV,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, preflight.returncode, preflight.stdout + preflight.stderr)
        tests = subprocess.run(
            ["bash", "scripts/test.sh"],
            cwd=self.root,
            env=NO_BYTECODE_ENV,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, tests.returncode, tests.stdout + tests.stderr)

    def test_runtime_projects_import_environment_through_jotunn_without_msb4011(self) -> None:
        (self.root / "Environment.props").write_text(
            """<Project><PropertyGroup>
  <VALHEIM_INSTALL>/fixture/Valheim</VALHEIM_INSTALL>
  <VALHEIM_MANAGED>$(VALHEIM_INSTALL)/valheim_Data/Managed</VALHEIM_MANAGED>
  <BEPINEX_PATH>$(VALHEIM_INSTALL)/BepInEx</BEPINEX_PATH>
</PropertyGroup></Project>
""",
            encoding="utf-8",
        )
        package_source = self.root / "test-packages"
        package_source.mkdir()
        with zipfile.ZipFile(package_source / "JotunnLib.2.29.2.nupkg", "w") as package:
            package.writestr(
                "JotunnLib.nuspec",
                """<?xml version="1.0" encoding="utf-8"?>
<package><metadata>
  <id>JotunnLib</id><version>2.29.2</version><authors>Fixture</authors><description>Fixture</description>
</metadata></package>
""",
            )
            package.writestr("lib/netstandard2.0/_._", "")
            package.writestr(
                "build/JotunnLib.props",
                '<Project><Import Project="$(MSBuildThisFileDirectory)Paths.props" /></Project>\n',
            )
            package.writestr(
                "build/Paths.props",
                """<Project>
  <Import Project="$(SolutionDir)Environment.props"
          Condition="'$(SolutionDir)' != '' AND Exists('$(SolutionDir)Environment.props')" />
  <Target Name="CaptureJotunnEnvironment" BeforeTargets="CoreCompile">
    <WriteLinesToFile File="$(MSBuildProjectDirectory)/jotunn-environment.txt"
      Lines="$(VALHEIM_INSTALL)|$(VALHEIM_MANAGED)|$(BEPINEX_PATH)" Overwrite="true" />
  </Target>
</Project>
""",
            )
        nuget_config = self.root / "NuGet.Config"
        nuget_config.write_text(
            f"""<configuration><packageSources>
  <clear />
  <add key="fixture" value="{package_source.as_uri()}" />
</packageSources></configuration>
""",
            encoding="utf-8",
        )
        environment = {**NO_BYTECODE_ENV, "NUGET_PACKAGES": str(self.root / "nuget-cache")}
        sdk = subprocess.run(["dotnet", "--version"], env=environment, text=True, capture_output=True)
        self.assertEqual(0, sdk.returncode, sdk.stdout + sdk.stderr)
        target_framework = f"net{sdk.stdout.strip().split('.', 1)[0]}.0"
        common = self.cfg["packages"]["commonModule"]
        common_csproj = self.root / "src" / common / f"{common}.csproj"
        common_csproj.write_text(
            common_csproj.read_text(encoding="utf-8").replace(
                "<TargetFramework>netstandard2.0</TargetFramework>",
                f"<TargetFramework>{target_framework}</TargetFramework>",
            ),
            encoding="utf-8",
        )
        runtime_projects = [
            project for project, item in self.cfg["projects"].items() if item["scope"] != "common"
        ]
        for project in runtime_projects:
            with self.subTest(project=project):
                csproj = self.root / "src" / project / f"{project}.csproj"
                self.assertIn('<PackageReference Include="JotunnLib" />', csproj.read_text(encoding="utf-8"))
                csproj.write_text(
                    csproj.read_text(encoding="utf-8").replace(
                        "</Project>",
                        f"""  <PropertyGroup>
    <TargetFramework>{target_framework}</TargetFramework>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
  </PropertyGroup>
  <ItemGroup>
    <Compile Include="Synthetic.cs" />
    <PackageReference Remove="Microsoft.NETFramework.ReferenceAssemblies" />
  </ItemGroup>
</Project>
""",
                    ),
                    encoding="utf-8",
                )
                (csproj.parent / "Synthetic.cs").write_text(
                    "namespace Synthetic; public static class Marker { }\n", encoding="utf-8"
                )
                restore = subprocess.run(
                    ["dotnet", "restore", str(csproj), "--configfile", str(nuget_config), "-nologo"],
                    cwd=self.root,
                    env=environment,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(0, restore.returncode, restore.stdout + restore.stderr)
                build = subprocess.run(
                    [
                        "dotnet",
                        "build",
                        str(csproj),
                        "--no-restore",
                        "-nologo",
                        f"-p:SolutionDir={self.root.as_posix()}/",
                    ],
                    cwd=self.root,
                    env=environment,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(0, build.returncode, build.stdout + build.stderr)
                self.assertNotIn("MSB4011", build.stdout + build.stderr)
                self.assertEqual(
                    "/fixture/Valheim|/fixture/Valheim/valheim_Data/Managed|/fixture/Valheim/BepInEx",
                    (csproj.parent / "jotunn-environment.txt").read_text(encoding="utf-8").strip(),
                )

if __name__ == "__main__":
    unittest.main()
