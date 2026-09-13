"""The artifact contract package.py/deploy.py rely on is MSBuild's *evaluated*
TargetFramework/AssemblyName, not a textual XML occurrence: a later
declaration, an import, a conditional, or a property expansion can otherwise
leave metadata certifying `bin/<cfg>/net48/<project>.dll` while the project
builds something else entirely, so stale bytes at the certified path ship.
"""

import base64
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap.validate_generated import NO_BYTECODE_ENV
from tests.fixtures._helpers import (
    clone_generated_temp,
    import_deploy_from,
    import_scripts_from,
    run_deploy,
    write_dev_json,
    write_fake_artifacts,
)


@unittest.skipUnless(shutil.which("dotnet"), "dotnet required to evaluate effective project properties")
class EffectiveProjectContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _params, cls.base, result = clone_generated_temp()
        if not result.ok:
            raise AssertionError(result.errors)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(self.base, self.root)
        self.cfg = json.loads((self.root / "suite.config.json").read_text())
        self.project = "Sampleheim.ServerCore"
        self.common = self.cfg["packages"]["commonModule"]
        self.metadata, _package = import_scripts_from(self.root / "scripts")
        props = self.root / "Directory.Build.props"
        props.write_text(props.read_text().replace("</Project>", """
  <Target Name="ObserveArtifactContract" BeforeTargets="Build">
    <WriteLinesToFile File="$(MSBuildProjectDirectory)/observed-$(Configuration)"
      Lines="$(TargetFramework);$(AssemblyName);$(Configuration);$(Platform);$(BuildingSolutionFile)"
      Overwrite="true" Encoding="UTF-8" />
    <ItemGroup>
      <ObservedContext Include="Configuration" Value="$([MSBuild]::ConvertToBase64('$(Configuration)'))" />
      <ObservedContext Include="Platform" Value="$([MSBuild]::ConvertToBase64('$(Platform)'))" />
      <ObservedContext Include="BuildingSolutionFile" Value="$([MSBuild]::ConvertToBase64('$(BuildingSolutionFile)'))" />
      <ObservedContext Include="CurrentSolutionConfigurationContents" Value="$([MSBuild]::ConvertToBase64('$(CurrentSolutionConfigurationContents)'))" />
      <ObservedContext Include="SolutionDir" Value="$([MSBuild]::ConvertToBase64('$(SolutionDir)'))" />
      <ObservedContext Include="SolutionPath" Value="$([MSBuild]::ConvertToBase64('$(SolutionPath)'))" />
      <ObservedContext Include="SolutionName" Value="$([MSBuild]::ConvertToBase64('$(SolutionName)'))" />
      <ObservedContext Include="SolutionFileName" Value="$([MSBuild]::ConvertToBase64('$(SolutionFileName)'))" />
      <ObservedContext Include="SolutionExt" Value="$([MSBuild]::ConvertToBase64('$(SolutionExt)'))" />
    </ItemGroup>
    <WriteLinesToFile File="$(MSBuildProjectDirectory)/context-$(Configuration)"
      Lines="@(ObservedContext->'%(Identity)=%(Value)')" Overwrite="true" Encoding="UTF-8" />
  </Target>
</Project>"""))

    def csproj(self, project):
        return self.root / "src" / project / f"{project}.csproj"

    def append(self, project, xml):
        path = self.csproj(project)
        path.write_text(path.read_text().replace("</Project>", xml + "</Project>"))

    def forged_reporter(self):
        return """
<Target Name="_SuiteReportArtifactContract">
  <ItemGroup>
    <Forged Include="MSBuildProjectFullPath" Value="$([MSBuild]::ConvertToBase64('$(MSBuildProjectFullPath)'))" />
    <Forged Include="Configuration" Value="$([MSBuild]::ConvertToBase64('$(Configuration)'))" />
    <Forged Include="Platform" Value="$([MSBuild]::ConvertToBase64('$(Platform)'))" />
    <Forged Include="BuildingSolutionFile" Value="$([MSBuild]::ConvertToBase64('true'))" />
    <Forged Include="TargetFramework" Value="$([MSBuild]::ConvertToBase64('net48'))" />
    <Forged Include="AssemblyName" Value="$([MSBuild]::ConvertToBase64('Sampleheim.ServerCore'))" />
  </ItemGroup>
  <WriteLinesToFile File="$(SuiteContractReportDirectory)/$(MSBuildProjectName).properties"
    Lines="@(Forged->'%(Identity)=%(Value)')" Overwrite="true" Encoding="UTF-8" />
</Target>"""

    def evaluated(self, project, configuration):
        """MSBuild's own answer, queried independently of the validator."""
        result = subprocess.run(
            ["dotnet", "msbuild", str(self.csproj(project)), "-nologo",
             "-getProperty:TargetFramework,AssemblyName",
             f"-p:Configuration={configuration}", "-p:Platform=AnyCPU"],
            cwd=self.root, env=NO_BYTECODE_ENV, text=True, capture_output=True,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)["Properties"]

    def solution_evaluated(self, configuration, *, build=False):
        solution = self.root / f"{self.cfg['rootNamespace']}.sln"
        command = (["dotnet", "build", str(solution), "-c", configuration] if build else
                   ["dotnet", "msbuild", str(solution), "-target:ObserveArtifactContract",
                    f"-property:Configuration={configuration}"])
        result = subprocess.run(command, cwd=self.root, env=NO_BYTECODE_ENV, text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        fields = ("TargetFramework", "AssemblyName", "Configuration", "Platform", "BuildingSolutionFile")
        return {
            project: dict(zip(fields, (self.csproj(project).parent / f"observed-{configuration}")
                              .read_text(encoding="utf-8-sig").splitlines()))
            for project in self.cfg["projects"]
        }

    def observed_solution_context(self, configuration):
        self.solution_evaluated(configuration)
        path = self.csproj(self.project).parent / f"context-{configuration}"
        return {
            key: base64.b64decode(value).decode()
            for key, value in (line.split("=", 1) for line in path.read_text(encoding="utf-8-sig").splitlines())
        }

    def run_script(self, *args, env=NO_BYTECODE_ENV):
        return subprocess.run([sys.executable, *args], cwd=self.root, env=env, text=True, capture_output=True)

    def assert_rejected(self, project, configuration, prop, hijacked, expected):
        self.assertEqual(hijacked, self.evaluated(project, configuration)[prop])
        result = self.run_script("scripts/suite_metadata.py", "check")
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        for fragment in (project, configuration, prop, hijacked, expected):
            self.assertIn(fragment, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_later_declaration_wins_and_blocks_stale_artifacts_before_mutation(self):
        write_dev_json(self.root)
        write_fake_artifacts(self.root, self.cfg, "Release")
        destination = Path(self.temp.name) / "destination"
        self.assertEqual(0, run_deploy(self.root, "server", destination, "Release").returncode)
        self.assertEqual(0, self.run_script("scripts/package.py", "--clean").returncode)
        packages = self.root / "artifacts" / "packages"
        snapshot = lambda root: {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        deployed, packaged = snapshot(destination), snapshot(packages)
        original = self.csproj(self.project).read_text()
        stale = f"{self.project}-build-output".encode()
        self.assertEqual(stale, (destination / f"{self.project}.dll").read_bytes())

        for prop, hijacked in (("TargetFramework", "net8.0"), ("AssemblyName", "Hijacked.Runtime")):
            with self.subTest(property=prop):
                self.csproj(self.project).write_text(original)
                self.append(self.project, f"<PropertyGroup><{prop}>{hijacked}</{prop}></PropertyGroup>")
                expected = self.project if prop == "AssemblyName" else "net48"
                self.assert_rejected(self.project, "Debug", prop, hijacked, expected)

                package = self.run_script("scripts/package.py", "--clean")
                self.assertEqual(2, package.returncode, package.stdout)
                self.assertIn(prop, package.stderr)
                self.assertEqual(packaged, snapshot(packages))

                deploy = run_deploy(self.root, "server", destination, "Release")
                self.assertNotEqual(0, deploy.returncode, deploy.stdout)
                self.assertIn(prop, deploy.stdout)
                self.assertEqual(deployed, snapshot(destination))

                fresh = Path(self.temp.name) / f"fresh-{prop}"
                self.assertNotEqual(0, run_deploy(self.root, "server", fresh, "Release").returncode)
                self.assertFalse(fresh.exists())

    def test_imported_override_is_rejected_for_runtime_and_common(self):
        for project in (self.project, self.common):
            original = self.csproj(project).read_text()
            tfm = self.cfg["projects"][project]["targetFramework"]
            for prop, hijacked, expected in (
                ("TargetFramework", "net8.0", tfm), ("AssemblyName", "Hijacked.Runtime", project)
            ):
                with self.subTest(project=project, property=prop):
                    (self.csproj(project).parent / "override.props").write_text(
                        f"<Project><PropertyGroup><{prop}>{hijacked}</{prop}></PropertyGroup></Project>"
                    )
                    self.append(project, '<Import Project="override.props" />')
                    self.assert_rejected(project, "Debug", prop, hijacked, expected)
                    self.csproj(project).write_text(original)

    def test_configuration_conditional_override_is_rejected_from_either_side(self):
        original = self.csproj(self.project).read_text()
        for configuration in ("Debug", "Release"):
            other = "Release" if configuration == "Debug" else "Debug"
            for prop, hijacked, expected in (
                ("TargetFramework", "net8.0", "net48"), ("AssemblyName", "Hijacked.Runtime", self.project)
            ):
                with self.subTest(configuration=configuration, property=prop):
                    self.csproj(self.project).write_text(original)
                    self.append(self.project, (
                        f"""<PropertyGroup Condition="'$(Configuration)|$(Platform)' == '{configuration}|AnyCPU'">"""
                        f"<{prop}>{hijacked}</{prop}></PropertyGroup>"
                    ))
                    self.assertEqual(expected, self.evaluated(self.project, other)[prop])
                    self.assert_rejected(self.project, configuration, prop, hijacked, expected)

    def test_property_expansion_through_directory_build_props_is_rejected(self):
        props = self.root / "Directory.Build.props"
        props.write_text(props.read_text().replace(
            "</Project>", "<PropertyGroup><ChosenFramework>net8.0</ChosenFramework></PropertyGroup></Project>"
        ))
        self.append(self.project, "<PropertyGroup><TargetFramework>$(ChosenFramework)</TargetFramework></PropertyGroup>")
        self.assert_rejected(self.project, "Debug", "TargetFramework", "net8.0", "net48")

    def test_directory_build_targets_override_is_rejected(self):
        (self.root / "Directory.Build.targets").write_text(
            f"""<Project><PropertyGroup Condition="'$(MSBuildProjectName)' == '{self.project}'">"""
            "<AssemblyName>Hijacked.Runtime</AssemblyName></PropertyGroup></Project>"
        )
        self.assert_rejected(self.project, "Debug", "AssemblyName", "Hijacked.Runtime", self.project)

    def test_unevaluable_project_fails_closed(self):
        self.append(self.project, '<Import Project="missing.props" />')
        result = self.run_script("scripts/suite_metadata.py", "check")
        self.assertEqual(2, result.returncode)
        self.assertIn(self.project, result.stderr)
        self.assertIn("missing.props", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_malformed_structured_msbuild_output_fails_closed(self):
        valid = {"Properties": {
            "MSBuildProjectFullPath": str(self.csproj(self.common)),
            **self.metadata.solution_evaluation_properties(
                (self.root / "Sampleheim.sln").read_text(), self.root / "Sampleheim.sln", "Debug"
            ),
            "TargetFramework": "netstandard2.0",
            "AssemblyName": self.common,
        }}
        cases = (
            "not JSON",
            "[]",
            json.dumps({"Properties": []}),
            json.dumps({"Properties": {}}),
            json.dumps({**valid, "Properties": {**valid["Properties"], "Unknown": "forged"}}),
        )
        for stdout in cases:
            with self.subTest(stdout=stdout), mock.patch.object(
                self.metadata.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 0, stdout, ""),
            ):
                with self.assertRaises(self.metadata.MetadataError):
                    self.metadata.validate(self.cfg)

    def test_observer_process_failure_and_timeout_fail_closed(self):
        for failure in (
            subprocess.CompletedProcess([], 1, "", "observer failed"),
            subprocess.TimeoutExpired(["dotnet"], 60),
        ):
            with self.subTest(failure=type(failure).__name__), mock.patch.object(
                self.metadata.subprocess, "run",
                return_value=failure if isinstance(failure, subprocess.CompletedProcess) else mock.DEFAULT,
                side_effect=failure if isinstance(failure, BaseException) else None,
            ):
                with self.assertRaises(self.metadata.MetadataError):
                    self.metadata.validate(self.cfg)

    def test_without_dotnet_only_the_explicit_structural_operation_succeeds(self):
        env = {**NO_BYTECODE_ENV, "PATH": self.temp.name}
        for command in ("check", "sync"):
            with self.subTest(command=command):
                result = self.run_script("scripts/suite_metadata.py", command, env=env)
                self.assertEqual(2, result.returncode)
                self.assertIn("cannot evaluate", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                result = self.run_script("scripts/suite_metadata.py", command, "--structural-only", env=env)
                self.assertEqual(0, result.returncode, result.stderr)
                if command == "check":
                    self.assertIn("NOT certified", result.stdout)

    def test_valid_generated_projects_evaluate_the_certified_contract(self):
        self.assertFalse((self.root / "Environment.props").exists(), "game references must not be needed")
        for project, item in self.cfg["projects"].items():
            for configuration in ("Debug", "Release"):
                with self.subTest(project=project, configuration=configuration):
                    self.assertEqual(
                        {"TargetFramework": item["targetFramework"], "AssemblyName": project},
                        self.evaluated(project, configuration),
                    )
        result = self.run_script("scripts/suite_metadata.py", "check", env={**NO_BYTECODE_ENV, "PYTHONPATH": ""})
        self.assertEqual(0, result.returncode, result.stderr)

    def test_emulated_globals_equal_actual_solution_child_context(self):
        sln = self.root / "Sampleheim.sln"
        sln_text = sln.read_text()
        for configuration in ("Debug", "Release"):
            with self.subTest(configuration=configuration):
                expected = self.metadata.solution_evaluation_properties(sln_text, sln, configuration)
                self.assertEqual(expected, self.observed_solution_context(configuration))

    def test_standard_solution_globals_cannot_override_the_certified_identity(self):
        original = self.csproj(self.project).read_text()
        conditions = {
            "BuildingSolutionFile": "'$(BuildingSolutionFile)' == 'true'",
            "SolutionDir": f"'$(SolutionDir)' == '{self.root}/'",
            "SolutionPath": f"'$(SolutionPath)' == '{self.root}/Sampleheim.sln'",
            "SolutionName": "'$(SolutionName)' == 'Sampleheim'",
            "SolutionFileName": "'$(SolutionFileName)' == 'Sampleheim.sln'",
            "SolutionExt": "'$(SolutionExt)' == '.sln'",
            "CurrentSolutionConfigurationContents": "'$(CurrentSolutionConfigurationContents)' != ''",
        }
        for property_name, condition in conditions.items():
            with self.subTest(property=property_name):
                self.csproj(self.project).write_text(original)
                self.append(self.project, f"""<PropertyGroup Condition="{condition}">
<AssemblyName>Hijacked.Solution</AssemblyName></PropertyGroup>""")
                self.assertEqual(self.project, self.evaluated(self.project, "Release")["AssemblyName"])
                actual = self.solution_evaluated("Release")[self.project]
                self.assertEqual("Hijacked.Solution", actual["AssemblyName"])
                self.assertEqual("true", actual["BuildingSolutionFile"])
                result = self.run_script("scripts/suite_metadata.py", "check")
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                self.assertIn("Hijacked.Solution", result.stderr)
                self.assertIn(self.project, result.stderr)

    def test_solution_only_override_in_either_configuration_is_rejected(self):
        original = self.csproj(self.project).read_text()
        for configuration in ("Debug", "Release"):
            with self.subTest(configuration=configuration):
                self.csproj(self.project).write_text(original)
                self.append(self.project, f"""<PropertyGroup Condition="'$(BuildingSolutionFile)' == 'true'
And '$(Configuration)|$(Platform)' == '{configuration}|AnyCPU'">
<TargetFramework>net8.0</TargetFramework></PropertyGroup>""")
                other = "Release" if configuration == "Debug" else "Debug"
                self.assertEqual("net48", self.evaluated(self.project, configuration)["TargetFramework"])
                self.assertEqual("net48", self.solution_evaluated(other)[self.project]["TargetFramework"])
                self.assertEqual("net8.0", self.solution_evaluated(configuration)[self.project]["TargetFramework"])
                result = self.run_script("scripts/suite_metadata.py", "check")
                self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                for fragment in (self.project, configuration, "TargetFramework", "net8.0", "net48"):
                    self.assertIn(fragment, result.stderr)


    def test_inline_redefinition_cannot_forge_certification(self):
        self.append(self.project, """<PropertyGroup Condition="'$(BuildingSolutionFile)' == 'true'">
<AssemblyName>Hijacked.Solution</AssemblyName></PropertyGroup>""" + self.forged_reporter())
        self.assertEqual("Hijacked.Solution", self.solution_evaluated("Release")[self.project]["AssemblyName"])
        result = self.run_script("scripts/suite_metadata.py", "check")
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("Hijacked.Solution", result.stderr)
        self.assertFalse(list(self.root.rglob("*.properties")))

    def test_imported_redefinition_cannot_forge_certification(self):
        malicious = self.csproj(self.project).parent / "malicious.targets"
        malicious.write_text("""<Project>
<PropertyGroup Condition="'$(BuildingSolutionFile)' == 'true'">
  <TargetFramework>net8.0</TargetFramework>
</PropertyGroup>""" + self.forged_reporter() + "</Project>")
        self.append(self.project, '<Import Project="malicious.targets" />')
        self.assertEqual("net8.0", self.solution_evaluated("Release")[self.project]["TargetFramework"])
        result = self.run_script("scripts/suite_metadata.py", "check")
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertIn("net8.0", result.stderr)
        self.assertFalse(list(self.root.rglob("*.properties")))

    def test_actual_solution_build_cannot_ship_stale_canonical_artifacts(self):
        # Compile harmless fixture sources through the unchanged generated solution.
        # Runtime reference declarations remain, but no game APIs are needed.
        for project, item in self.cfg["projects"].items():
            if item["scope"] == "common":
                continue
            self.append(project, """<PropertyGroup><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup>
<ItemGroup><Compile Include="FreezeMarker.cs" /><PackageReference Remove="JotunnLib" /></ItemGroup>""")
            (self.csproj(project).parent / "FreezeMarker.cs").write_text("namespace FreezeFixture { public class Marker {} }")
        original = self.csproj(self.project).read_text()
        write_dev_json(self.root)
        packages = self.root / "artifacts/packages"
        packages.mkdir(parents=True)
        (packages / "existing.zip").write_bytes(b"package-sentinel")
        (packages / "SHA256SUMS").write_bytes(b"checksum-sentinel")
        destination = Path(self.temp.name) / "destination"
        destination.mkdir()
        (destination / f"{self.project}.dll").write_bytes(b"installed-before")
        deploy = import_deploy_from(self.root / "scripts")
        (destination / deploy.manifest_name(self.cfg)).write_text(
            json.dumps({"version": 1, "files": [f"{self.project}.dll"]})
        )
        snapshot = lambda root: {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        packaged, deployed = snapshot(packages), snapshot(destination)
        for prop, value in (("AssemblyName", "Hijacked.Solution"), ("TargetFramework", "net8.0")):
            with self.subTest(property=prop):
                self.csproj(self.project).write_text(original)
                self.append(self.project, f"""<PropertyGroup Condition="'$(BuildingSolutionFile)' == 'true'">
<{prop}>{value}</{prop}></PropertyGroup>""")
                self.append(self.project, self.forged_reporter())
                if prop == "TargetFramework":
                    # Solution restore uses a different context; give the fixture assets for both TFMs.
                    self.append(self.project, "<PropertyGroup><TargetFrameworks>net48;net8.0</TargetFrameworks></PropertyGroup>")
                write_fake_artifacts(self.root, self.cfg, "Release")
                stale = self.csproj(self.project).parent / "bin/Release/net48" / f"{self.project}.dll"
                stale_bytes = stale.read_bytes()
                direct_expected = self.project if prop == "AssemblyName" else "net48"
                self.assertEqual(direct_expected, self.evaluated(self.project, "Release")[prop])
                self.assertEqual(value, self.solution_evaluated("Release", build=True)[self.project][prop])
                output = self.csproj(self.project).parent / "bin/Release"
                output /= "net8.0" if prop == "TargetFramework" else "net48"
                output /= "Hijacked.Solution.dll" if prop == "AssemblyName" else f"{self.project}.dll"
                self.assertTrue(output.is_file(), output)
                self.assertNotEqual(stale_bytes, output.read_bytes())
                self.assertEqual(stale_bytes, stale.read_bytes())
                for args in (("scripts/suite_metadata.py", "check"), ("scripts/package.py", "--clean")):
                    result = self.run_script(*args)
                    self.assertEqual(2, result.returncode, result.stdout + result.stderr)
                    self.assertIn(value, result.stderr)
                result = run_deploy(self.root, "server", destination, "Release")
                self.assertNotEqual(0, result.returncode, result.stdout)
                self.assertIn(value, result.stdout)
                self.assertEqual(packaged, snapshot(packages))
                self.assertEqual(deployed, snapshot(destination))
                with mock.patch.object(deploy.fcntl, "flock", side_effect=AssertionError("transaction began")), \
                     mock.patch.object(sys, "stderr", io.StringIO()), \
                     mock.patch.object(sys, "argv", ["deploy.py", "--target", "server", "--configuration", "Release",
                                                   "--destination", str(destination)]):
                    self.assertEqual(2, deploy.main())

    def test_certification_executes_no_project_targets_or_game_work(self):
        for project in self.cfg["projects"]:
            self.append(project, """<Target Name="RejectAnyTargetExecution"
BeforeTargets="Restore;ResolveReferences;CoreCompile;Build;_SuiteReportArtifactContract">
<Error Text="artifact certification must not execute project targets" /></Target>""")
        scratch = Path(self.temp.name) / "scratch"
        scratch.mkdir()
        self.assertFalse((self.root / "Environment.props").exists())
        result = self.run_script("scripts/suite_metadata.py", "check",
                                 env={**NO_BYTECODE_ENV, "TMPDIR": str(scratch), "PYTHONPATH": ""})
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(list(self.root.rglob("bin")))
        self.assertFalse(list(self.root.rglob("obj")))
        self.assertFalse(list(self.root.rglob("*.properties")))
