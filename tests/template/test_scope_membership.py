"""Regression tests for the metadata-validation issue where a configured
runtime module's package/deployment membership could silently drift from,
or omit, what its declared compatibility scope requires.

Every scenario reproduces one of the original audit configurations or
exercises the full scope -> membership contract, using disposable temp
copies of `template/` or fully generated temp projects -- never the live
`template/` tree.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

from tests.fixtures._helpers import copy_template_to_temp, generate_into_temp, import_scripts_from


def _load_cfg(project_dir: Path) -> dict:
    return json.loads((project_dir / "suite.config.json").read_text(encoding="utf-8"))


def _save_cfg(project_dir: Path, cfg: dict) -> None:
    (project_dir / "suite.config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["python3", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _import_deploy_from(scripts_dir: Path):
    sys.path.insert(0, str(scripts_dir))
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        sys.modules.pop("deploy", None)
        sys.modules.pop("suite_metadata", None)
        import deploy as dm

        importlib.reload(dm)
        return dm
    finally:
        sys.dont_write_bytecode = previous
        sys.path.remove(str(scripts_dir))


def _write_csproj(root: Path, project: str, tfm: str) -> None:
    project_dir = root / "src" / project
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / f"{project}.csproj").write_text(
        f"<Project><PropertyGroup><TargetFramework>{tfm}</TargetFramework>"
        f"<AssemblyName>{project}</AssemblyName></PropertyGroup></Project>",
        encoding="utf-8",
    )


def _minimal_valid_cfg(root: Path) -> dict:
    """A schema-valid config with only the mandatory common module.
    Callers add scope-specific projects with `_add_project`."""
    common = "Sampleheim.Common"
    _write_csproj(root, common, "netstandard2.0")
    return {
        "schemaVersion": 1,
        "suiteName": "Sampleheim",
        "rootNamespace": "Sampleheim",
        "pluginGuidRoot": "org.example.sampleheim",
        "author": "A",
        "thunderstoreNamespace": "NS",
        "suiteVersion": "1.0.0",
        "csharpLanguageVersion": "10.0",
        "jotunnVersion": "1.0.0",
        "bepInExPackVersion": "1.0.0",
        "netFrameworkReferenceAssembliesVersion": "1.0.0",
        "projects": {common: {"scope": "common", "targetFramework": "netstandard2.0"}},
        "packages": {
            "commonModule": common,
            "serverModules": [],
            "requiredClientModules": [],
            "optionalClientModules": [],
            "clientOnlyModules": [],
        },
    }


def _add_project(root: Path, cfg: dict, project: str, scope: str, groups: set[str], tfm: str = "net48") -> None:
    """Register `project` with `scope` in `cfg` and place it into exactly
    `groups` among the four package/deployment membership arrays."""
    cfg["projects"][project] = {"scope": scope, "targetFramework": tfm}
    _write_csproj(root, project, tfm)
    for group in ("serverModules", "requiredClientModules", "optionalClientModules", "clientOnlyModules"):
        if group in groups:
            cfg["packages"][group].append(project)


class MembershipMatrixTests(unittest.TestCase):
    """Section 8: for every compatibility scope, the exact required
    membership must be accepted and every other placement -- missing one
    required group, missing all of them, an incompatible group, or a
    contradictory extra classification -- must be rejected."""

    def setUp(self) -> None:
        self.root = copy_template_to_temp()
        self.metadata, _pkg = import_scripts_from(self.root / "scripts")

    # (scope, groups the test project is placed in, expected validity)
    CASES = [
        # serverOnly: exactly {serverModules}
        ("serverOnly", {"serverModules"}, True),
        ("serverOnly", set(), False),  # missing its one required group entirely
        ("serverOnly", {"requiredClientModules"}, False),  # incompatible group, still missing required
        ("serverOnly", {"serverModules", "requiredClientModules"}, False),  # contradictory extra placement
        ("serverOnly", {"serverModules", "clientOnlyModules"}, False),
        # sharedRequired: exactly {serverModules, requiredClientModules}
        ("sharedRequired", {"serverModules", "requiredClientModules"}, True),
        ("sharedRequired", {"requiredClientModules"}, False),  # audit case: missing server side
        ("sharedRequired", {"serverModules"}, False),  # missing client side
        ("sharedRequired", set(), False),  # missing all required groups
        ("sharedRequired", {"serverModules", "optionalClientModules"}, False),  # wrong client classification
        ("sharedRequired", {"serverModules", "requiredClientModules", "optionalClientModules"}, False),  # duplicate/incompatible client classification
        # sharedOptional: exactly {serverModules, optionalClientModules}
        ("sharedOptional", {"serverModules", "optionalClientModules"}, True),
        ("sharedOptional", {"optionalClientModules"}, False),  # missing server side
        ("sharedOptional", {"serverModules"}, False),  # missing client side
        ("sharedOptional", set(), False),  # original audit case: omitted entirely
        ("sharedOptional", {"serverModules", "requiredClientModules"}, False),  # wrong client classification
        ("sharedOptional", {"serverModules", "requiredClientModules", "optionalClientModules"}, False),
        # clientOnly: exactly {clientOnlyModules}
        ("clientOnly", {"clientOnlyModules"}, True),
        ("clientOnly", set(), False),  # original audit case: omitted from client group
        ("clientOnly", {"serverModules"}, False),  # must not be required server-side
        ("clientOnly", {"clientOnlyModules", "requiredClientModules"}, False),  # duplicate client classification
        ("clientOnly", {"clientOnlyModules", "optionalClientModules"}, False),
    ]

    def test_matrix(self) -> None:
        for index, (scope, groups, valid) in enumerate(self.CASES):
            with self.subTest(scope=scope, groups=sorted(groups), valid=valid):
                cfg = _minimal_valid_cfg(self.root)
                project = f"Sampleheim.Case{index}"
                _add_project(self.root, cfg, project, scope, groups)
                if valid:
                    self.metadata.validate(cfg)
                else:
                    with self.assertRaises(self.metadata.MetadataError):
                        self.metadata.validate(cfg)


class ExistingSafetyInvariantsStillHoldTests(unittest.TestCase):
    """Section 11: the membership rewrite must not regress guarantees the
    validator already provided independently of scope membership."""

    def setUp(self) -> None:
        self.root = copy_template_to_temp()
        self.metadata, _pkg = import_scripts_from(self.root / "scripts")
        self.cfg = _minimal_valid_cfg(self.root)

    def test_unknown_project_reference_is_rejected(self) -> None:
        self.cfg["packages"]["serverModules"].append("NoSuchProject")
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)

    def test_duplicate_within_single_group_is_rejected(self) -> None:
        _add_project(self.root, self.cfg, "Sampleheim.ServerOnly", "serverOnly", {"serverModules"})
        self.cfg["packages"]["serverModules"].append("Sampleheim.ServerOnly")
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)


class ErrorQualityTests(unittest.TestCase):
    """Section 12: rejection must name the inconsistent project, its
    declared scope, and the missing/invalid membership -- not a generic
    "invalid config" message."""

    def setUp(self) -> None:
        self.root = copy_template_to_temp()
        self.metadata, _pkg = import_scripts_from(self.root / "scripts")
        self.cfg = _minimal_valid_cfg(self.root)

    def test_message_names_project_scope_and_missing_groups(self) -> None:
        project = "Sampleheim.Shared.Diagnostics"
        _add_project(self.root, self.cfg, project, "sharedOptional", set())

        with self.assertRaises(self.metadata.MetadataError) as ctx:
            self.metadata.validate(self.cfg)

        message = str(ctx.exception)
        self.assertIn(project, message)
        self.assertIn("sharedOptional", message)
        self.assertIn("serverModules", message)
        self.assertIn("optionalClientModules", message)

    def test_message_names_contradictory_extra_membership(self) -> None:
        project = "Sampleheim.ClientOnly"
        _add_project(self.root, self.cfg, project, "clientOnly", {"clientOnlyModules", "serverModules"})

        with self.assertRaises(self.metadata.MetadataError) as ctx:
            self.metadata.validate(self.cfg)

        message = str(ctx.exception)
        self.assertIn(project, message)
        self.assertIn("clientOnly", message)
        self.assertIn("must not appear in serverModules", message)


class EffectivePackageDeploymentTests(unittest.TestCase):
    """Section 9: valid metadata must still make the actual deploy.py and
    package.py consumers -- not just validate() -- produce the intended
    per-scope definitions."""

    def setUp(self) -> None:
        self.root = copy_template_to_temp()
        self.metadata, self.pkg = import_scripts_from(self.root / "scripts")
        self.deploy = _import_deploy_from(self.root / "scripts")
        self.cfg = _minimal_valid_cfg(self.root)

    def _definitions(self) -> dict[str, list[str]]:
        return {name: modules for name, modules, _kind in self.metadata.package_definitions(self.cfg)}

    def test_shared_required_reaches_server_and_required_client_sides(self) -> None:
        project = "Sampleheim.Shared.Required"
        _add_project(self.root, self.cfg, project, "sharedRequired", {"serverModules", "requiredClientModules"})
        self.metadata.validate(self.cfg)

        self.assertIn(project, self.deploy.modules_for(self.cfg, "server"))
        self.assertIn(project, self.deploy.modules_for(self.cfg, "client"))

        definitions = self._definitions()
        self.assertIn(project, definitions["Sampleheim-ServerPack"])
        self.assertIn(project, definitions["Sampleheim-ClientPack"])
        self.assertIn(project, definitions["Sampleheim-Shared-Required"])

    def test_shared_optional_reaches_server_and_optional_client_sides(self) -> None:
        project = "Sampleheim.Shared.Optional"
        _add_project(self.root, self.cfg, project, "sharedOptional", {"serverModules", "optionalClientModules"})
        self.metadata.validate(self.cfg)

        self.assertIn(project, self.deploy.modules_for(self.cfg, "server"))
        self.assertIn(project, self.deploy.modules_for(self.cfg, "client"))

        definitions = self._definitions()
        self.assertIn(project, definitions["Sampleheim-ServerPack"])
        self.assertIn(project, definitions["Sampleheim-ClientPack"])
        self.assertIn(project, definitions["Sampleheim-Shared-Optional"])

    def test_client_only_reaches_client_side_only(self) -> None:
        project = "Sampleheim.ClientOnly"
        _add_project(self.root, self.cfg, project, "clientOnly", {"clientOnlyModules"})
        self.metadata.validate(self.cfg)

        self.assertNotIn(project, self.deploy.modules_for(self.cfg, "server"))
        self.assertIn(project, self.deploy.modules_for(self.cfg, "client"))

        definitions = self._definitions()
        self.assertIn(project, definitions["Sampleheim-Client"])
        self.assertNotIn("Sampleheim-ServerPack", definitions)

    def test_server_only_reaches_server_side_only(self) -> None:
        project = "Sampleheim.ServerOnly"
        _add_project(self.root, self.cfg, project, "serverOnly", {"serverModules"})
        self.metadata.validate(self.cfg)

        self.assertIn(project, self.deploy.modules_for(self.cfg, "server"))
        self.assertNotIn(project, self.deploy.modules_for(self.cfg, "client"))

        definitions = self._definitions()
        self.assertIn(project, definitions["Sampleheim-ServerCore"])
        self.assertNotIn("Sampleheim-ClientPack", definitions)


class OriginalAuditRegressionTests(unittest.TestCase):
    """Section 7: the three configurations the audit found `sync`/`check`
    silently accepting must now be rejected end-to-end, through the real
    CLI, on a fully generated project."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)

    def _assert_rejected_everywhere(self) -> None:
        _save_cfg(self.output_dir, self.cfg)
        metadata, _pkg = import_scripts_from(self.output_dir / "scripts")
        with self.assertRaises(metadata.MetadataError):
            metadata.validate(_load_cfg(self.output_dir))

        sync = _run(["scripts/suite_metadata.py", "sync"], self.output_dir)
        self.assertNotEqual(0, sync.returncode, sync.stdout)

        check = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, check.returncode, check.stdout)

    def test_shared_optional_omitted_from_both_groups_is_rejected(self) -> None:
        shared_diag = next(p for p, item in self.cfg["projects"].items() if item["scope"] == "sharedOptional")
        self.cfg["packages"]["serverModules"].remove(shared_diag)
        self.cfg["packages"]["optionalClientModules"].remove(shared_diag)
        self._assert_rejected_everywhere()

    def test_client_only_omitted_from_client_group_is_rejected(self) -> None:
        client_project = next(p for p, item in self.cfg["projects"].items() if item["scope"] == "clientOnly")
        self.cfg["packages"]["clientOnlyModules"].remove(client_project)
        self._assert_rejected_everywhere()

    def test_shared_required_kept_client_side_but_omitted_server_side_is_rejected(self) -> None:
        project = "Sampleheim.Shared.Required"
        self.cfg["projects"][project] = {"scope": "sharedRequired", "targetFramework": "net48"}
        _write_csproj(self.output_dir, project, "net48")
        self.cfg["packages"]["requiredClientModules"].append(project)
        # Deliberately not added to serverModules -- the exact audited defect.
        self._assert_rejected_everywhere()


class MalformedScopeValueTests(unittest.TestCase):
    """Reviewer follow-up: an unhashable `scope` (list/dict) must raise a
    controlled `MetadataError` through `validate()`, `sync`, and `check` --
    never a raw `TypeError` -- and must not touch generated output files."""

    def setUp(self) -> None:
        self.params, self.output_dir, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        self.cfg = _load_cfg(self.output_dir)
        self.metadata, _pkg = import_scripts_from(self.output_dir / "scripts")
        self.project = next(iter(self.cfg["projects"]))

    def _snapshot_generated_files(self) -> dict[Path, bytes | None]:
        paths = [
            self.output_dir / "build" / "Suite.Generated.props",
            self.output_dir / "packaging" / "profile-lock.json",
        ]
        paths += [self.output_dir / "src" / p / "SuiteConstants.Generated.cs" for p in self.cfg["projects"]]
        return {path: (path.read_bytes() if path.is_file() else None) for path in paths}

    def _baseline_exit_code(self) -> int:
        """The exit code an already-controlled metadata failure (an
        ordinary bad *string* scope) produces here, so the new
        unhashable-scope cases are verified against the same controlled
        path rather than a hardcoded number."""
        cfg = _load_cfg(self.output_dir)
        cfg["projects"][self.project]["scope"] = "not-a-real-scope"
        _save_cfg(self.output_dir, cfg)
        proc = _run(["scripts/suite_metadata.py", "check"], self.output_dir)
        self.assertNotEqual(0, proc.returncode)
        return proc.returncode

    def test_validate_rejects_list_scope_without_raw_typeerror(self) -> None:
        self.cfg["projects"][self.project]["scope"] = []
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)

    def test_validate_rejects_dict_scope_without_raw_typeerror(self) -> None:
        self.cfg["projects"][self.project]["scope"] = {}
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)

    def test_validate_rejects_nested_container_scope_without_raw_typeerror(self) -> None:
        self.cfg["projects"][self.project]["scope"] = [{"nested": ["value"]}]
        with self.assertRaises(self.metadata.MetadataError):
            self.metadata.validate(self.cfg)

    def _assert_sync_and_check_fail_like_baseline(self, scope_value: object) -> None:
        baseline_code = self._baseline_exit_code()

        cfg = _load_cfg(self.output_dir)
        cfg["projects"][self.project]["scope"] = scope_value
        _save_cfg(self.output_dir, cfg)
        before = self._snapshot_generated_files()

        for args in (["scripts/suite_metadata.py", "sync"], ["scripts/suite_metadata.py", "check"]):
            proc = _run(args, self.output_dir)
            self.assertEqual(baseline_code, proc.returncode, proc.stdout)
            self.assertNotIn("Traceback", proc.stdout)
            self.assertIn("metadata error:", proc.stdout)
            self.assertEqual(before, self._snapshot_generated_files())

    def test_sync_and_check_fail_like_baseline_for_list_scope(self) -> None:
        self._assert_sync_and_check_fail_like_baseline([])

    def test_sync_and_check_fail_like_baseline_for_dict_scope(self) -> None:
        self._assert_sync_and_check_fail_like_baseline({})


if __name__ == "__main__":
    unittest.main()
