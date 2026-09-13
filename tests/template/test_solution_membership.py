"""Regression tests for the config <-> canonical-solution project
membership invariant: `suite.config.json`'s `projects` must exactly equal
which C# projects `<rootNamespace>.sln` actually declares under `src/`.

Before this fix, a project could be added to `suite.config.json` without
a matching `.sln` entry (packaged/deployed but never built by
`dotnet build`), or removed from `suite.config.json` while the solution
still built it (built but metadata claims it doesn't exist), and
`sync`/`check` accepted both. Downstream mutation and parser scenarios use
private `clone_generated_temp()` fixtures from certified seeds. The optional
module matrix keeps real `generate_into_temp()` coverage. No test uses the live
`template/` tree.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from tests.fixtures._helpers import clone_generated_temp, generate_into_temp, import_scripts_from, write_dev_json, write_fake_artifacts

CSHARP_PROJECT_TYPE_GUID = "{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}"


def _load_cfg(project_dir: Path) -> dict:
    return json.loads((project_dir / "suite.config.json").read_text(encoding="utf-8"))


def _save_cfg(project_dir: Path, cfg: dict) -> None:
    (project_dir / "suite.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["python3", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _run_combined(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _sln_path(output_dir: Path, cfg: dict) -> Path:
    return output_dir / f"{cfg['rootNamespace']}.sln"


def _add_sln_entry(output_dir: Path, cfg: dict, project: str) -> None:
    sln_path = _sln_path(output_dir, cfg)
    lines = sln_path.read_text(encoding="utf-8").splitlines()
    insert_at = next(i for i, line in enumerate(lines) if line.strip() == "Global")
    guid = "{" + str(uuid.uuid4()).upper() + "}"
    lines[insert_at:insert_at] = [
        f'Project("{CSHARP_PROJECT_TYPE_GUID}") = "{project}", "src\\{project}\\{project}.csproj", "{guid}"',
        "EndProject",
    ]
    section = next(i for i, line in enumerate(lines) if "GlobalSection(ProjectConfigurationPlatforms)" in line)
    lines[section + 1:section + 1] = [
        f"\t\t{guid}.{configuration}|Any CPU.{mapping} = {configuration}|Any CPU"
        for configuration in ("Debug", "Release") for mapping in ("ActiveCfg", "Build.0")
    ]
    sln_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _remove_sln_entry(output_dir: Path, cfg: dict, project: str) -> None:
    sln_path = _sln_path(output_dir, cfg)
    lines = sln_path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("Project(") and f'"{project}"' in line)
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "EndProject")
    guid = lines[start].rsplit('"', 2)[1]
    del lines[start : end + 1]
    lines = [line for line in lines if not line.strip().startswith(guid + ".")]
    sln_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_csproj(output_dir: Path, project: str, tfm: str) -> None:
    project_dir = output_dir / "src" / project
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / f"{project}.csproj").write_text(
        f'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>{tfm}</TargetFramework>'
        f"<AssemblyName>{project}</AssemblyName></PropertyGroup></Project>",
        encoding="utf-8",
    )


def _generated_snapshot(output_dir: Path, cfg: dict) -> dict:
    common = cfg["packages"]["commonModule"]
    paths = [
        output_dir / "build" / "Suite.Generated.props",
        output_dir / "packaging" / "profile-lock.json",
        output_dir / "src" / common / "SuiteConstants.Generated.cs",
        output_dir / "suite.identity.lock.json",
    ]
    return {path: (path.read_bytes() if path.is_file() else None) for path in paths}


def _insert_raw_block(output_dir: Path, cfg: dict, name: str, raw_path: str) -> None:
    """Insert a `Project(...)"`/`EndProject` block with an arbitrary,
    possibly-malformed `raw_path` -- for constructing regressions the
    canonical `_add_sln_entry()` cannot express."""
    sln_path = _sln_path(output_dir, cfg)
    lines = sln_path.read_text(encoding="utf-8").splitlines()
    insert_at = next(i for i, line in enumerate(lines) if line.strip() == "Global")
    guid = "{" + str(uuid.uuid4()).upper() + "}"
    lines[insert_at:insert_at] = [
        f'Project("{CSHARP_PROJECT_TYPE_GUID}") = "{name}", "{raw_path}", "{guid}"',
        "EndProject",
    ]
    sln_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class SolutionParserTests(unittest.TestCase):
    """Section 7: a narrow line-shape parser, not a substring search,
    identifies `src/` C# project entries and excludes the generated test
    project and non-`src/` entries by role/path. Returns a list, not a
    dict, so duplicate entries survive parsing intact for validation to
    reject explicitly."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        self.metadata, _pkg = import_scripts_from(self.output_dir / "scripts")

    def test_parses_every_configured_src_project(self) -> None:
        sln_text = _sln_path(self.output_dir, self.cfg).read_text(encoding="utf-8")
        parsed = self.metadata.parse_solution_src_projects(sln_text)
        self.assertEqual(set(self.cfg["projects"]), {name for name, _path in parsed})

    def test_excludes_the_generated_test_project(self) -> None:
        sln_text = _sln_path(self.output_dir, self.cfg).read_text(encoding="utf-8")
        parsed = self.metadata.parse_solution_src_projects(sln_text)
        test_project = f"{self.params.root_namespace}.Common.Tests"
        self.assertIn(test_project, sln_text)
        self.assertNotIn(test_project, {name for name, _path in parsed})

    def test_windows_backslash_paths_normalize_to_forward_slashes(self) -> None:
        common = self.cfg["packages"]["commonModule"]
        sln_text = _sln_path(self.output_dir, self.cfg).read_text(encoding="utf-8")
        self.assertIn(f'"src\\{common}\\{common}.csproj"', sln_text)
        parsed = self.metadata.parse_solution_src_projects(sln_text)
        self.assertEqual(f"src/{common}/{common}.csproj", dict(parsed)[common])

    def test_preserves_duplicate_entries_instead_of_collapsing_them(self) -> None:
        common = self.cfg["packages"]["commonModule"]
        sln_text = _sln_path(self.output_dir, self.cfg).read_text(encoding="utf-8")
        lines = sln_text.splitlines()
        insert_at = next(i for i, line in enumerate(lines) if line.strip() == "Global")
        duplicate = [
            f'Project("{{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}}") = "{common}", "src\\{common}\\{common}.csproj", "{{11111111-1111-1111-1111-111111111111}}"',
            "EndProject",
        ]
        lines[insert_at:insert_at] = duplicate
        parsed = self.metadata.parse_solution_src_projects("\n".join(lines))
        self.assertEqual(2, sum(1 for name, _path in parsed if name == common))

    def test_lowercase_project_type_guid_is_still_recognized(self) -> None:
        common = self.cfg["packages"]["commonModule"]
        sln_text = _sln_path(self.output_dir, self.cfg).read_text(encoding="utf-8")
        lowered = sln_text.replace("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}", "{fae04ec0-301f-11d3-bf4b-00c04f79efbc}")
        parsed = self.metadata.parse_solution_src_projects(lowered)
        self.assertIn(common, {name for name, _path in parsed})


class ProjectAdditionTests(unittest.TestCase):
    """Section 8: adding a project to `suite.config.json` without a
    matching `.sln` entry must be rejected; adding the `.sln` entry too
    must be accepted."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        self.new_project = f"{self.params.root_namespace}.Extra"
        self.cfg["projects"][self.new_project] = {"scope": "sharedOptional", "targetFramework": "net48"}
        self.cfg["packages"]["serverModules"].append(self.new_project)
        self.cfg["packages"]["optionalClientModules"].append(self.new_project)
        _write_csproj(self.output_dir, self.new_project, "net48")

    def test_addition_missing_from_solution_is_rejected(self) -> None:
        _save_cfg(self.output_dir, self.cfg)
        before = _generated_snapshot(self.output_dir, self.cfg)

        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertNotEqual(0, sync.returncode, sync.stdout)
        self.assertIn("must exactly match the canonical solution", sync.stdout)
        self.assertIn(self.new_project, sync.stdout)

        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, check.returncode, check.stdout)
        self.assertEqual(before, _generated_snapshot(self.output_dir, self.cfg))

    def test_package_cannot_proceed_while_addition_is_missing_from_solution(self) -> None:
        _save_cfg(self.output_dir, self.cfg)
        proc = _run(["scripts/package.py"], self.output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertFalse((self.output_dir / "artifacts").exists())

    def test_addition_present_in_solution_is_accepted(self) -> None:
        _add_sln_entry(self.output_dir, self.cfg, self.new_project)
        _save_cfg(self.output_dir, self.cfg)

        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertEqual(0, sync.returncode, sync.stdout)
        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertEqual(0, check.returncode, check.stdout)


class ProjectRemovalTests(unittest.TestCase):
    """Section 9: removing a project from `suite.config.json` while the
    solution still builds it must be rejected; removing it from both must
    be accepted. The now-orphaned `src/` directory is not itself flagged
    -- unreferenced source files are allowed, matching the existing
    architecture."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        self.removed = next(p for p, item in self.cfg["projects"].items() if item["scope"] == "sharedOptional")

    def _cfg_without_removed(self) -> dict:
        cfg = json.loads(json.dumps(self.cfg))
        del cfg["projects"][self.removed]
        for group in ("serverModules", "requiredClientModules", "optionalClientModules", "clientOnlyModules"):
            cfg["packages"][group] = [p for p in cfg["packages"][group] if p != self.removed]
        return cfg

    def test_removal_while_still_in_solution_is_rejected(self) -> None:
        cfg = self._cfg_without_removed()
        _save_cfg(self.output_dir, cfg)
        before = _generated_snapshot(self.output_dir, self.cfg)

        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertNotEqual(0, sync.returncode, sync.stdout)
        self.assertIn("must exactly match the canonical solution", sync.stdout)
        self.assertIn(self.removed, sync.stdout)

        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, check.returncode, check.stdout)
        self.assertEqual(before, _generated_snapshot(self.output_dir, self.cfg))

    def test_removal_from_both_config_and_solution_is_accepted(self) -> None:
        cfg = self._cfg_without_removed()
        _remove_sln_entry(self.output_dir, self.cfg, self.removed)
        _save_cfg(self.output_dir, cfg)

        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertEqual(0, sync.returncode, sync.stdout)
        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertEqual(0, check.returncode, check.stdout)
        # The orphaned src/ directory is left on disk untouched and unflagged.
        self.assertTrue((self.output_dir / "src" / self.removed).is_dir())


class BuildTestDeployMismatchTests(unittest.TestCase):
    """Section 13: the standard workflows must not succeed while
    `projects` and solution membership disagree."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        self.new_project = f"{self.params.root_namespace}.Extra"
        self.cfg["projects"][self.new_project] = {"scope": "sharedOptional", "targetFramework": "net48"}
        self.cfg["packages"]["serverModules"].append(self.new_project)
        self.cfg["packages"]["optionalClientModules"].append(self.new_project)
        _write_csproj(self.output_dir, self.new_project, "net48")
        _save_cfg(self.output_dir, self.cfg)

    def test_build_script_fails_via_metadata_check_before_dotnet_build(self) -> None:
        proc = _run_combined(["bash", "scripts/build.sh", "Debug"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("must exactly match the canonical solution", proc.stdout)

    def test_test_script_fails_via_metadata_check(self) -> None:
        proc = _run_combined(["bash", "scripts/test.sh"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("must exactly match the canonical solution", proc.stdout)

    def test_deploy_rejects_before_any_mutation(self) -> None:
        write_dev_json(self.output_dir)
        write_fake_artifacts(self.output_dir, self.cfg)
        destination = Path(tempfile.mkdtemp(prefix="valheimsuite-solution-mismatch-deploy-"))
        proc = _run_combined(
            ["python3", "scripts/deploy.py", "--target", "server", "--destination", str(destination)],
            self.output_dir,
        )
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertIn("must exactly match the canonical solution", proc.stdout)
        self.assertFalse(any(destination.iterdir()))


class OptionalModuleMatrixSolutionMembershipTests(unittest.TestCase):
    """Section 18: every generated optional-module combination's
    `projects` must exactly match its own solution's project set."""

    def test_all_seven_supported_combinations_have_exact_solution_membership(self) -> None:
        for server_core in (True, False):
            for client in (True, False):
                for shared_diagnostics in (True, False):
                    if not (server_core or client or shared_diagnostics):
                        continue  # 000: no runtime module enabled -- rejected at bootstrap, covered separately.
                    with self.subTest(server_core=server_core, client=client, shared_diagnostics=shared_diagnostics):
                        _params, output_dir, result = generate_into_temp(
                            include_server_core=server_core,
                            include_client=client,
                            include_shared_diagnostics=shared_diagnostics,
                        )
                        self.assertTrue(result.ok, result.errors)
                        check = _run(["scripts/suite_metadata.py", "check"], output_dir)
                        self.assertEqual(0, check.returncode, check.stdout)


class DuplicateSourceEntryValidationTests(unittest.TestCase):
    """Section 3/12: `_reject_duplicate_source_entries()`'s own contract,
    exercised directly with hand-built entry lists -- "same name,
    different path" and "different names, same path" cannot occur in
    real `.sln` text once `parse_solution_src_projects()`'s per-entry
    exact-path check runs (either entry would already fail that check
    first), so this is the precise place to prove the helper itself
    still rejects them if ever reached some other way."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.metadata, _pkg = import_scripts_from(self.output_dir / "scripts")

    def test_no_duplicates_passes(self) -> None:
        self.metadata._reject_duplicate_source_entries([("A", "src/A/A.csproj"), ("B", "src/B/B.csproj")])  # must not raise

    def test_identical_name_and_path_twice_is_rejected(self) -> None:
        with self.assertRaises(self.metadata.MetadataError) as ctx:
            self.metadata._reject_duplicate_source_entries([("A", "src/A/A.csproj"), ("A", "src/A/A.csproj")])
        self.assertIn("duplicate project entry", str(ctx.exception))

    def test_same_name_different_path_is_rejected(self) -> None:
        with self.assertRaises(self.metadata.MetadataError) as ctx:
            self.metadata._reject_duplicate_source_entries([("A", "src/A/A.csproj"), ("A", "src/A/Other.csproj")])
        self.assertIn("two different paths", str(ctx.exception))

    def test_different_names_same_path_is_rejected(self) -> None:
        with self.assertRaises(self.metadata.MetadataError) as ctx:
            self.metadata._reject_duplicate_source_entries([("A", "src/Shared/Shared.csproj"), ("B", "src/Shared/Shared.csproj")])
        self.assertIn("two different project names", str(ctx.exception))


class MalformedSolutionEntryRegressionTests(unittest.TestCase):
    """Sections 1/2/4-6/11/13/15: every way a solution entry can keep a
    configured project's name while its path/structure is wrong must be
    rejected before any generated file, package output, or deployment
    destination is touched -- reconfirmed for `sync`, `check`, and
    `package.py` (the pre-existing `BuildTestDeployMismatchTests` already
    covers `build.sh`/`test.sh`/`deploy.py` ordering for a config/
    solution mismatch of this general shape)."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        self.target = self.cfg["packages"]["commonModule"]
        self.canonical_quoted_path = f'"src\\{self.target}\\{self.target}.csproj"'

    def _mutate_sln(self, transform) -> None:
        sln_path = _sln_path(self.output_dir, self.cfg)
        text = sln_path.read_text(encoding="utf-8")
        mutated = transform(text)
        self.assertNotEqual(text, mutated, "test setup did not actually change the solution")
        sln_path.write_text(mutated, encoding="utf-8")

    def _assert_rejected_before_any_mutation(self) -> None:
        before = _generated_snapshot(self.output_dir, self.cfg)

        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertNotEqual(0, sync.returncode, sync.stdout)
        self.assertNotIn("Traceback", sync.stdout)
        self.assertEqual(before, _generated_snapshot(self.output_dir, self.cfg))

        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, check.returncode, check.stdout)
        self.assertNotIn("Traceback", check.stdout)

        pkg = _run(["scripts/package.py"], self.output_dir)
        self.assertNotEqual(0, pkg.returncode, pkg.stdout)
        self.assertFalse((self.output_dir / "artifacts").exists())

    def test_correct_name_nonexistent_path_is_rejected(self) -> None:
        self._mutate_sln(
            lambda text: text.replace(
                self.canonical_quoted_path, f'"src\\{self.target}\\nonexistent\\{self.target}.csproj"'
            )
        )
        self._assert_rejected_before_any_mutation()

    def test_correct_name_path_redirected_to_another_configured_csproj_is_rejected(self) -> None:
        other = next(p for p in self.cfg["projects"] if p != self.target)
        self._mutate_sln(lambda text: text.replace(self.canonical_quoted_path, f'"src\\{other}\\{other}.csproj"'))
        self._assert_rejected_before_any_mutation()

    def test_traversal_to_an_external_project_is_rejected(self) -> None:
        """Section 5: the reviewer's exact reproduction -- a `..`
        traversal keeps the configured project's *name* while its path
        redirects to a real, buildable external project."""
        external_dir = self.output_dir.parent / f"external-{uuid.uuid4().hex}"
        external_dir.mkdir()
        (external_dir / f"{self.target}.csproj").write_text(
            "<Project><PropertyGroup><TargetFramework>netstandard2.0</TargetFramework>"
            f"<AssemblyName>{self.target}</AssemblyName></PropertyGroup></Project>",
            encoding="utf-8",
        )
        self.addCleanup(lambda: shutil.rmtree(external_dir, ignore_errors=True))
        traversal = f"src\\..\\..\\{external_dir.name}\\{self.target}.csproj"
        self._mutate_sln(lambda text: text.replace(self.canonical_quoted_path, f'"{traversal}"'))
        self._assert_rejected_before_any_mutation()

    def test_duplicate_identical_entry_in_real_solution_is_rejected(self) -> None:
        _insert_raw_block(self.output_dir, self.cfg, self.target, f"src\\{self.target}\\{self.target}.csproj")
        self._assert_rejected_before_any_mutation()

    def test_missing_end_project_is_rejected(self) -> None:
        def transform(text: str) -> str:
            lines = text.splitlines()
            start = next(
                i
                for i, line in enumerate(lines)
                if line.strip().startswith("Project(") and f'"{self.target}"' in line
            )
            end = next(i for i in range(start, len(lines)) if lines[i].strip() == "EndProject")
            del lines[end]
            return "\n".join(lines) + "\n"

        self._mutate_sln(transform)
        self._assert_rejected_before_any_mutation()


class StaleArtifactBypassRegressionTest(unittest.TestCase):
    """Section 14: the reviewer's strongest bypass, reproduced end to
    end -- a solution entry redirected to an external project must never
    let package/deploy certify a stale local DLL as corresponding to the
    canonical build."""

    def test_redirected_solution_entry_blocks_package_and_deploy_of_the_stale_local_dll(self) -> None:
        params, output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        cfg = _load_cfg(output_dir)
        target = cfg["packages"]["commonModule"]
        tfm = cfg["projects"][target]["targetFramework"]

        # A stale local DLL from an earlier, legitimate build.
        stale_dll = output_dir / "src" / target / "bin" / "Release" / tfm / f"{target}.dll"
        stale_dll.parent.mkdir(parents=True, exist_ok=True)
        stale_dll.write_bytes(b"stale-local-build")
        write_fake_artifacts(output_dir, cfg, configuration="Release")

        # Redirect the solution entry for `target` to a real external project.
        external_dir = output_dir.parent / f"external-{uuid.uuid4().hex}"
        external_dir.mkdir()
        (external_dir / f"{target}.csproj").write_text(
            f"<Project><PropertyGroup><TargetFramework>{tfm}</TargetFramework>"
            f"<AssemblyName>{target}</AssemblyName></PropertyGroup></Project>",
            encoding="utf-8",
        )
        self.addCleanup(lambda: shutil.rmtree(external_dir, ignore_errors=True))
        sln_path = _sln_path(output_dir, cfg)
        sln_path.write_text(
            sln_path.read_text(encoding="utf-8").replace(
                f'"src\\{target}\\{target}.csproj"', f'"src\\..\\..\\{external_dir.name}\\{target}.csproj"'
            ),
            encoding="utf-8",
        )

        check = _run(["scripts/suite_metadata.py", "check"], output_dir)
        self.assertNotEqual(0, check.returncode, check.stdout)

        pkg = _run(["scripts/package.py"], output_dir)
        self.assertNotEqual(0, pkg.returncode, pkg.stdout)
        self.assertFalse((output_dir / "artifacts").exists(), "stale local DLL must never be packaged")

        write_dev_json(output_dir)
        destination = Path(tempfile.mkdtemp(prefix="valheimsuite-stale-artifact-deploy-"))
        deploy = _run_combined(
            ["python3", "scripts/deploy.py", "--target", "server", "--destination", str(destination)], output_dir
        )
        self.assertNotEqual(0, deploy.returncode, deploy.stdout)
        self.assertFalse(any(destination.iterdir()), "stale local DLL must never be deployed")


class ValidNonSuiteEntryTests(unittest.TestCase):
    """Section 5/10: a stricter malformed-header rule must not reject
    syntactically valid blocks merely because they are outside the suite
    C# project universe."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)

    def _insert_and_check(self, project_type_guid: str, name: str) -> subprocess.CompletedProcess:
        sln_path = _sln_path(self.output_dir, self.cfg)
        lines = sln_path.read_text(encoding="utf-8").splitlines()
        insert_at = next(i for i, line in enumerate(lines) if line.strip() == "Global")
        guid = "{" + str(uuid.uuid4()).upper() + "}"
        lines[insert_at:insert_at] = [f'Project("{project_type_guid}") = "{name}", "{name}", "{guid}"', "EndProject"]
        sln_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return _run(["scripts/suite_metadata.py", "check"], self.output_dir)

    def test_valid_solution_folder_is_accepted_and_excluded(self) -> None:
        # {2150E333-8FDC-42A3-9474-1A3956D46DE8} is the well-known Visual
        # Studio "Solution Folder" project-type GUID.
        proc = self._insert_and_check("{2150E333-8FDC-42A3-9474-1A3956D46DE8}", "SolutionItems")
        self.assertEqual(0, proc.returncode, proc.stdout)

    def test_valid_unrelated_project_type_is_accepted_and_excluded(self) -> None:
        proc = self._insert_and_check("{11111111-1111-1111-1111-111111111111}", "SomeOtherProjectType")
        self.assertEqual(0, proc.returncode, proc.stdout)

    def test_mixed_case_csharp_type_guid_is_still_recognized(self) -> None:
        sln_path = _sln_path(self.output_dir, self.cfg)
        text = sln_path.read_text(encoding="utf-8")
        mixed = text.replace("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}", "{Fae04Ec0-301F-11d3-BF4b-00C04f79EFBC}")
        sln_path.write_text(mixed, encoding="utf-8")
        proc = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertEqual(0, proc.returncode, proc.stdout)


class MalformedProjectHeaderRegressionTests(unittest.TestCase):
    """Sections 1/3/4/6: a `Project(...)` header that opens a block but
    does not parse as a supported declaration must invalidate the whole
    solution -- matching `dotnet sln <solution> list`'s own rejection --
    not be silently ignored as "not a C# project"."""

    MALFORMED_HEADER = "Project(This is not a valid solution project header)"

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        sln_path = _sln_path(self.output_dir, self.cfg)
        lines = sln_path.read_text(encoding="utf-8").splitlines()
        insert_at = next(i for i, line in enumerate(lines) if line.strip() == "Global")
        lines[insert_at:insert_at] = [self.MALFORMED_HEADER, "EndProject"]
        sln_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_parser_raises_directly(self) -> None:
        metadata, _pkg = import_scripts_from(self.output_dir / "scripts")
        sln_text = _sln_path(self.output_dir, self.cfg).read_text(encoding="utf-8")
        with self.assertRaises(metadata.MetadataError) as ctx:
            metadata.parse_solution_src_projects(sln_text)
        self.assertIn("does not match the supported declaration syntax", str(ctx.exception))
        self.assertIn(self.MALFORMED_HEADER, str(ctx.exception))

    def test_sync_and_check_fail_with_no_generated_mutation(self) -> None:
        before = _generated_snapshot(self.output_dir, self.cfg)

        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertNotEqual(0, sync.returncode, sync.stdout)
        self.assertIn("does not match the supported declaration syntax", sync.stdout)
        self.assertNotIn("Traceback", sync.stdout)
        self.assertEqual(before, _generated_snapshot(self.output_dir, self.cfg))

        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, check.returncode, check.stdout)
        self.assertIn("does not match the supported declaration syntax", check.stdout)

    def test_package_does_not_proceed(self) -> None:
        pkg = _run(["scripts/package.py"], self.output_dir)
        self.assertNotEqual(0, pkg.returncode, pkg.stdout)
        self.assertFalse((self.output_dir / "artifacts").exists())

    def test_deploy_does_not_mutate_the_destination(self) -> None:
        write_dev_json(self.output_dir)
        write_fake_artifacts(self.output_dir, self.cfg)
        destination = Path(tempfile.mkdtemp(prefix="valheimsuite-malformed-header-deploy-"))
        deploy = _run_combined(
            ["python3", "scripts/deploy.py", "--target", "server", "--destination", str(destination)],
            self.output_dir,
        )
        self.assertNotEqual(0, deploy.returncode, deploy.stdout)
        self.assertFalse(any(destination.iterdir()))

    def test_build_and_test_scripts_never_reach_dotnet(self) -> None:
        build = _run_combined(["bash", "scripts/build.sh", "Debug"], self.output_dir)
        self.assertNotEqual(0, build.returncode)
        self.assertIn("does not match the supported declaration syntax", build.stdout)

        test_run = _run_combined(["bash", "scripts/test.sh"], self.output_dir)
        self.assertNotEqual(0, test_run.returncode)
        self.assertIn("does not match the supported declaration syntax", test_run.stdout)

    def test_dotnet_sln_list_also_rejects_the_same_solution(self) -> None:
        """Section 4: canonical CLI agreement -- both metadata validation
        and `dotnet sln list` reject the malformed solution."""
        if shutil.which("dotnet") is None:
            self.skipTest("dotnet SDK not discoverable on PATH")
        sln_name = f"{self.cfg['rootNamespace']}.sln"
        proc = _run_combined(["dotnet", "sln", sln_name, "list"], self.output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)


class CommonOnlyRuntimeInvariantTests(unittest.TestCase):
    """Section 18/23: a generated suite whose runtime projects are all
    removed post-generation -- from `projects`, every package group, and
    the `.sln` -- leaving only Common must be rejected by metadata
    validation and every workflow that depends on it (sync, check,
    package, deploy, preflight), not silently certified as a valid empty
    mod suite."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)

    def _strip_to_common_only(self) -> None:
        common = self.cfg["packages"]["commonModule"]
        removed = [p for p in self.cfg["projects"] if p != common]
        self.cfg["projects"] = {common: self.cfg["projects"][common]}
        self.cfg["packages"] = {
            "commonModule": common,
            "serverModules": [],
            "requiredClientModules": [],
            "optionalClientModules": [],
            "clientOnlyModules": [],
        }
        _save_cfg(self.output_dir, self.cfg)
        for project in removed:
            _remove_sln_entry(self.output_dir, self.cfg, project)

    def test_sync_rejects_common_only_config(self) -> None:
        self._strip_to_common_only()
        proc = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertIn("runtime", proc.stdout)

    def test_check_rejects_common_only_config(self) -> None:
        self._strip_to_common_only()
        proc = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertIn("runtime", proc.stdout)

    def test_package_rejects_before_writing_any_output(self) -> None:
        self._strip_to_common_only()
        proc = _run(["scripts/package.py"], self.output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertFalse((self.output_dir / "artifacts").exists())

    def test_deploy_rejects_before_touching_destination(self) -> None:
        self._strip_to_common_only()
        write_dev_json(self.output_dir)
        destination = Path(tempfile.mkdtemp(prefix="valheimsuite-common-only-deploy-"))
        proc = _run_combined(
            ["python3", "scripts/deploy.py", "--target", "server", "--destination", str(destination)],
            self.output_dir,
        )
        self.assertNotEqual(0, proc.returncode, proc.stdout)
        self.assertFalse(any(destination.iterdir()))

    def test_preflight_portable_rejects_common_only_config(self) -> None:
        self._strip_to_common_only()
        proc = _run(["scripts/preflight.py", "--portable", "--json"], self.output_dir)
        self.assertNotEqual(0, proc.returncode, proc.stdout)


if __name__ == "__main__":
    unittest.main()
