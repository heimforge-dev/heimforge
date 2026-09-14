from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures._helpers import clone_generated_temp


def load_maintenance(project: Path):
    scripts = project / "scripts"
    saved = {name: sys.modules.pop(name, None) for name in ("preflight", "suite_metadata")}
    sys.path.insert(0, str(scripts))
    try:
        name = f"game_stack_{id(project)}"
        spec = importlib.util.spec_from_file_location(name, scripts / "update-game-stack.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(scripts))
        for name, previous in saved.items():
            if previous is not None:
                sys.modules[name] = previous


def write_runtime(project: Path, *, jotunn: str | None = "2.30.0", bepinex: str | None = "5.4.2350") -> None:
    steamapps = project / "Steam Library" / "steamapps"
    install = steamapps / "common" / "Valheim"
    managed = install / "valheim_Data" / "Managed"
    bepinex_root = project / "Profile with spaces" / "BepInEx"
    (managed / "publicized_assemblies").mkdir(parents=True, exist_ok=True)
    (managed / "publicized_assemblies" / "assembly_valheim_publicized.dll").write_bytes(b"publicized")
    (managed / "assembly_valheim.dll").write_bytes(b"gameplay-current")
    (bepinex_root / "plugins" / "Jotunn").mkdir(parents=True, exist_ok=True)
    (bepinex_root / "plugins" / "Jotunn" / "Jotunn.dll").write_bytes(b"jotunn")
    jotunn_manifest = bepinex_root / "plugins" / "Jotunn" / "manifest.json"
    if jotunn is None:
        jotunn_manifest.unlink(missing_ok=True)
    else:
        jotunn_manifest.write_text(json.dumps({"name": "Jotunn", "version_number": jotunn}), encoding="utf-8-sig")
    mods = bepinex_root.parent / "mods.yml"
    if bepinex is None:
        mods.unlink(missing_ok=True)
    else:
        mods.write_text(
            "- manifestVersion: 1\n"
            "  name: denikson-BepInExPack_Valheim\n"
            "  versionNumber:\n"
            f"    major: {bepinex.split('.')[0]}\n"
            f"    minor: {bepinex.split('.')[1]}\n"
            f"    patch: {bepinex.split('.')[2]}\n"
            "  enabled: true\n",
            encoding="utf-8",
        )
    (steamapps / "appmanifest_892970.acf").write_text(
        '"AppState"\n{\n  "appid" "892970"\n  "buildid" "123456"\n}\n', encoding="utf-8"
    )
    (project / "Environment.props").write_text(
        "<Project><PropertyGroup>"
        f"<VALHEIM_INSTALL>{install}</VALHEIM_INSTALL>"
        f"<VALHEIM_MANAGED>{managed}</VALHEIM_MANAGED>"
        f"<BEPINEX_PATH>{bepinex_root}</BEPINEX_PATH>"
        "<MOD_DEPLOYPATH>/tmp/mods</MOD_DEPLOYPATH>"
        "</PropertyGroup></Project>\n",
        encoding="utf-8",
    )


class GameStackMaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.params, self.project, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        write_runtime(self.project)
        self.module = load_maintenance(self.project)

    def invoke(self, *args: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["update-game-stack.py", *args]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = self.module.main()
        return result, stdout.getvalue(), stderr.getvalue()

    def run_game_update_check(self) -> subprocess.CompletedProcess[str]:
        install = self.project / "Steam Library" / "steamapps" / "common" / "Valheim"
        bepinex_root = self.project / "Profile with spaces" / "BepInEx"
        dev_config = {
            "schemaVersion": 1,
            "developmentOnly": True,
            "valheimInstall": str(install),
            "clientPluginDir": str(bepinex_root / "plugins" / self.params.root_namespace),
            "serverPluginDir": str(self.project / "server-plugins"),
            "dockerComposeFile": None,
            "serverLogFile": None,
            "solution": f"{self.params.root_namespace}.sln",
            "configuration": "Debug",
        }
        dev_path = self.project / ".valheim" / "dev.json"
        dev_path.parent.mkdir(exist_ok=True)
        dev_path.write_text(json.dumps(dev_config), encoding="utf-8")
        fake_bin = self.project / "fake-bin"
        fake_bin.mkdir(exist_ok=True)
        dotnet = fake_bin / "dotnet"
        dotnet.write_text("#!/usr/bin/env bash\nprintf '8.0.0\\n'\n", encoding="utf-8")
        dotnet.chmod(0o755)
        environment = dict(
            os.environ,
            PATH=f"{fake_bin}:{os.environ.get('PATH', '')}",
            SUITE_BOOTSTRAP_VALIDATION="1",
        )
        return subprocess.run(
            ["bash", "scripts/check-game-update.sh"],
            cwd=self.project,
            env=environment,
            text=True,
            capture_output=True,
        )

    def test_game_update_check_prefers_current_gameplay_assembly(self) -> None:
        managed = self.project / "Steam Library" / "steamapps" / "common" / "Valheim" / "valheim_Data" / "Managed"
        (managed / "Assembly-CSharp.dll").write_bytes(b"gameplay-legacy")

        result = self.run_game_update_check()

        self.assertEqual(0, result.returncode, result.stderr)
        selected = managed / "assembly_valheim.dll"
        self.assertIn(f"Gameplay assembly: {selected}", result.stdout)
        self.assertIn(hashlib.sha256(b"gameplay-current").hexdigest(), result.stdout)
        self.assertNotIn(str(managed / "Assembly-CSharp.dll"), result.stdout)
        self.assertIn("Harmony targets requiring revalidation:", result.stdout)

    def test_generated_command_is_present_and_check_is_non_destructive_with_matching_versions(self) -> None:
        command = self.project / "scripts" / "update-game-stack.py"
        self.assertTrue(command.is_file())
        self.assertTrue(command.stat().st_mode & 0o111)
        self.assertTrue((self.project / "scripts" / "refresh-references.sh").stat().st_mode & 0o111)
        before = {path: path.read_bytes() for path in (self.project / "suite.config.json", self.project / "build" / "Suite.Generated.props")}
        with mock.patch.object(self.module, "run_command") as run:
            code, stdout, stderr = self.invoke("check")
        self.assertEqual(0, code, stderr)
        self.assertEqual([], run.call_args_list)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertIn("Steam build ID 123456", stdout)
        self.assertIn("installed development-profile version: 2.30.0", stdout)
        self.assertEqual(2, stdout.count("drift status: matching"))
        self.assertIn("freshness: unknown", stdout)
        self.assertNotIn("current", stdout.lower())
        self.assertNotIn("up-to-date", stdout.lower())

    def test_check_reports_drift_unknown_versions_and_missing_references_safely(self) -> None:
        write_runtime(self.project, jotunn="2.29.2", bepinex=None)
        (self.project / "Steam Library" / "steamapps" / "common" / "Valheim" / "valheim_Data" / "Managed" / "publicized_assemblies" / "assembly_valheim_publicized.dll").unlink()
        with mock.patch.object(self.module, "run_command"):
            code, stdout, stderr = self.invoke("check")
        self.assertEqual(0, code, stderr)
        self.assertIn("Jötunn", stdout)
        self.assertIn("drift status: drift", stdout)
        self.assertIn("installed development-profile version: unknown", stdout)
        self.assertIn("drift status: unknown", stdout)
        self.assertIn("presence: missing", stdout)

    def apply_with_sync(self, *args: str) -> tuple[int, str, str, list[list[str]]]:
        commands: list[list[str]] = []

        def run(command: list[str]) -> None:
            commands.append(command)
            if command[-1] == "sync":
                self.module.suite_metadata.sync(self.module.suite_metadata.load_config(), structural_only=True)

        with mock.patch.object(self.module, "run_command", side_effect=run):
            code, stdout, stderr = self.invoke("apply", *args)
        return code, stdout, stderr, commands

    def test_apply_updates_only_requested_jotunn_pin_and_generated_metadata(self) -> None:
        code, stdout, stderr, commands = self.apply_with_sync("--jotunn", "2.31.0")
        self.assertEqual(0, code, stderr)
        cfg = json.loads((self.project / "suite.config.json").read_text(encoding="utf-8"))
        self.assertEqual("2.31.0", cfg["jotunnVersion"])
        self.assertEqual("5.4.2350", cfg["bepInExPackVersion"])
        self.assertIn("2.31.0", (self.project / "build" / "Suite.Generated.props").read_text(encoding="utf-8"))
        self.assertIn(["bash", "scripts/refresh-references.sh", "Debug"], commands)
        self.assertIn(["bash", "scripts/build.sh", "Debug"], commands)
        self.assertNotIn("deploy", " ".join(part for command in commands for part in command))
        self.assertNotIn("restart", " ".join(part for command in commands for part in command))
        self.assertIn("Project maintenance completed successfully", stdout)
        self.assertIn("drift status: drift", stdout)
        self.assertIn("Remote/server runtime: not inspected", stdout)
    def test_apply_updates_only_requested_bepinex_pin_and_both_pins(self) -> None:
        code, _stdout, stderr, commands = self.apply_with_sync("--bepinex", "5.4.2400")
        self.assertEqual(0, code, stderr)
        cfg = json.loads((self.project / "suite.config.json").read_text(encoding="utf-8"))
        self.assertEqual("2.30.0", cfg["jotunnVersion"])
        self.assertEqual("5.4.2400", cfg["bepInExPackVersion"])
        self.assertNotIn(["bash", "scripts/refresh-references.sh", "Debug"], commands)

        code, _stdout, stderr, _commands = self.apply_with_sync("--jotunn", "2.32.0", "--bepinex", "5.4.2500")
        self.assertEqual(0, code, stderr)
        props = (self.project / "build" / "Suite.Generated.props").read_text(encoding="utf-8")
        lock = json.loads((self.project / "packaging" / "profile-lock.json").read_text(encoding="utf-8"))
        self.assertIn("2.32.0", props)
        self.assertIn("5.4.2500", props)
        self.assertEqual("2.32.0", lock["dependencies"]["ValheimModding-Jotunn"])
        self.assertEqual("5.4.2500", lock["dependencies"]["denikson-BepInExPack_Valheim"])

    def test_refresh_keeps_metadata_unchanged_and_runs_ordered_project_steps(self) -> None:
        common = json.loads((self.project / "suite.config.json").read_text(encoding="utf-8"))["packages"]["commonModule"]
        tracked = (
            self.project / "suite.config.json",
            self.project / "build" / "Suite.Generated.props",
            self.project / "src" / common / "SuiteConstants.Generated.cs",
            self.project / "packaging" / "profile-lock.json",
        )
        before = {path: path.read_bytes() for path in tracked}
        with mock.patch.object(self.module, "run_command", side_effect=lambda command: None) as run:
            code, stdout, stderr = self.invoke("refresh")
        self.assertEqual(0, code, stderr)
        self.assertEqual(
            [
                [sys.executable, "scripts/suite_metadata.py", "check"],
                ["bash", "scripts/refresh-references.sh", "Debug"],
                ["bash", "scripts/build.sh", "Debug"],
                [sys.executable, "scripts/preflight.py"],
            ],
            [call.args[0] for call in run.call_args_list],
        )
        self.assertEqual(before, {path: path.read_bytes() for path in tracked})
        self.assertIn("Remote/server runtime: not inspected", stdout)

    def test_apply_reports_each_later_stage_failure_without_rollback(self) -> None:
        for stage, needle in (
            ("scripts/refresh-references.sh", "reference refresh failed"),
            ("scripts/build.sh", "normal build failed"),
            ("scripts/preflight.py", "preflight failed"),
        ):
            with self.subTest(stage=stage):
                def run(command: list[str]) -> None:
                    if command[-1] == "sync":
                        self.module.suite_metadata.sync(self.module.suite_metadata.load_config(), structural_only=True)
                    if len(command) > 1 and command[1] == stage:
                        raise subprocess.CalledProcessError(1, command)

                with mock.patch.object(self.module, "run_command", side_effect=run):
                    code, stdout, stderr = self.invoke("apply", "--jotunn", "2.31.0")
                self.assertEqual(2, code)
                self.assertNotIn("Project maintenance completed successfully", stdout)
                self.assertIn(needle, stderr)
                self.assertIn("Synchronized dependency pins and generated metadata remain applied.", stderr)
                cfg = self.module.suite_metadata.load_config()
                self.assertEqual("2.31.0", cfg["jotunnVersion"])
                for path, expected in self.module.suite_metadata.expected_files(cfg).items():
                    self.assertEqual(expected, path.read_text(encoding="utf-8"))

    def test_apply_reports_unknown_runtime_without_failing_project_maintenance(self) -> None:
        profile = self.project / "Profile with spaces"
        (profile / "BepInEx" / "plugins" / "Jotunn" / "manifest.json").unlink()
        (profile / "mods.yml").unlink()
        with mock.patch.object(self.module, "run_command", side_effect=lambda command: None):
            code, stdout, stderr = self.invoke("apply", "--bepinex", "5.4.2400")
        self.assertEqual(0, code, stderr)
        self.assertIn("installed development-profile version: unknown", stdout)
        self.assertIn("drift status: unknown", stdout)
        self.assertIn("Remote/server runtime: not inspected", stdout)
        self.assertIn("Project maintenance completed successfully", stdout)

    def test_sync_rolls_back_all_outputs_when_second_promotion_fails(self) -> None:
        metadata = self.module.suite_metadata
        cfg = metadata.load_config()
        targets = list(metadata.expected_files(cfg))
        targets[0].write_bytes(b"")
        before = {path: path.read_bytes() for path in targets}
        original_atomic = metadata.atomic_write_text
        calls = {"n": 0}

        def fail_second(path, content, **kwargs):
            calls["n"] += 1
            if calls["n"] == 2:
                raise metadata.MetadataError("injected output-2 failure")
            return original_atomic(path, content, **kwargs)

        cfg["jotunnVersion"] = "2.31.0"
        with mock.patch.object(metadata, "atomic_write_text", side_effect=fail_second):
            with self.assertRaises(metadata.MetadataError):
                metadata.sync(cfg, structural_only=True)
        self.assertEqual(before, {path: path.read_bytes() for path in targets})

    def test_sync_restores_outputs_when_first_promotion_fails(self) -> None:
        metadata = self.module.suite_metadata
        cfg = metadata.load_config()
        targets = list(metadata.expected_files(cfg))
        before = {path: path.read_bytes() for path in targets}
        cfg["jotunnVersion"] = "2.31.0"
        with mock.patch.object(metadata, "atomic_write_text", side_effect=metadata.MetadataError("injected output-1 failure")):
            with self.assertRaises(metadata.MetadataError):
                metadata.sync(cfg, structural_only=True)
        self.assertEqual(before, {path: path.read_bytes() for path in targets})

    def test_sync_rolls_back_an_absent_output_when_third_promotion_fails(self) -> None:
        metadata = self.module.suite_metadata
        cfg = metadata.load_config()
        targets = list(metadata.expected_files(cfg))
        absent = targets[1]
        absent.unlink()
        before = {path: (path.read_bytes() if path.exists() else None) for path in targets}
        original_atomic = metadata.atomic_write_text
        calls = {"n": 0}

        def fail_third(path, content, **kwargs):
            calls["n"] += 1
            if calls["n"] == 3:
                raise metadata.MetadataError("injected output-3 failure")
            return original_atomic(path, content, **kwargs)

        cfg["jotunnVersion"] = "2.31.0"
        with mock.patch.object(metadata, "atomic_write_text", side_effect=fail_third):
            with self.assertRaises(metadata.MetadataError):
                metadata.sync(cfg, structural_only=True)
        self.assertEqual(before, {path: (path.read_bytes() if path.exists() else None) for path in targets})

    def test_sync_rollback_failure_preserves_original_bytes_in_recovery_record(self) -> None:
        metadata = self.module.suite_metadata
        cfg = metadata.load_config()
        targets = list(metadata.expected_files(cfg))
        before = {path: path.read_bytes() for path in targets}
        original_text = metadata.atomic_write_text
        original_bytes = metadata.atomic_write_bytes
        text_calls = {"n": 0}
        rollback_failed = {"value": False}

        def fail_second_text(path, content, **kwargs):
            text_calls["n"] += 1
            if text_calls["n"] == 2:
                raise metadata.MetadataError("injected output-2 failure")
            return original_text(path, content, **kwargs)

        def fail_first_rollback(path, content, **kwargs):
            if kwargs.get("parent") is None and not rollback_failed["value"]:
                rollback_failed["value"] = True
                raise metadata.MetadataError("injected rollback failure")
            return original_bytes(path, content, **kwargs)

        cfg["jotunnVersion"] = "2.31.0"
        with mock.patch.object(metadata, "atomic_write_text", side_effect=fail_second_text), mock.patch.object(
            metadata, "atomic_write_bytes", side_effect=fail_first_rollback
        ):
            with self.assertRaisesRegex(metadata.MetadataError, "original bytes were saved in") as ctx:
                metadata.sync(cfg, structural_only=True)

        recovery_name = str(ctx.exception).split("original bytes were saved in ", 1)[1].split(":", 1)[0]
        recovery = json.loads((self.project / recovery_name).read_text(encoding="utf-8"))
        originals = {
            self.project / item["path"]: None if item["original"] is None else base64.b64decode(item["original"])
            for item in recovery["outputs"]
        }
        self.assertEqual({path: before[path] for path in targets[:2]}, originals)

    def test_apply_restores_config_and_generated_outputs_after_partial_sync_failure(self) -> None:
        metadata = self.module.suite_metadata
        cfg = metadata.load_config()
        outputs = list(metadata.expected_files(cfg))
        before = {
            self.project / "suite.config.json": (self.project / "suite.config.json").read_bytes(),
            **{path: path.read_bytes() for path in outputs},
        }
        original_text = metadata.atomic_write_text
        generated_writes = {"n": 0}

        def fail_second_generated_write(path, content, **kwargs):
            if kwargs.get("parent") is not None:
                generated_writes["n"] += 1
                if generated_writes["n"] == 2:
                    raise metadata.MetadataError("injected output-2 failure")
            return original_text(path, content, **kwargs)

        def run(command: list[str]) -> None:
            if command[-1] != "sync":
                return
            try:
                metadata.sync(metadata.load_config(), structural_only=True)
            except metadata.MetadataError as exc:
                raise subprocess.CalledProcessError(2, command) from exc

        with mock.patch.object(metadata, "atomic_write_text", side_effect=fail_second_generated_write), mock.patch.object(
            self.module, "run_command", side_effect=run
        ):
            code, stdout, stderr = self.invoke("apply", "--jotunn", "2.31.0")
        self.assertEqual(2, code)
        self.assertNotIn("Project maintenance completed successfully", stdout)
        self.assertIn("restored suite.config.json", stderr)
        self.assertNotIn("Synchronized dependency pins and generated metadata remain applied.", stderr)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_apply_initial_metadata_validation_failure_does_not_claim_synchronized_metadata(self) -> None:
        before = (self.project / "suite.config.json").read_bytes()
        with mock.patch.object(
            self.module,
            "require_valid_metadata",
            side_effect=subprocess.CalledProcessError(2, ["python3", "scripts/suite_metadata.py", "check"]),
        ):
            code, _stdout, stderr = self.invoke("apply", "--jotunn", "2.31.0")
        self.assertEqual(2, code)
        self.assertEqual(before, (self.project / "suite.config.json").read_bytes())
        self.assertNotIn("Synchronized dependency pins and generated metadata remain applied.", stderr)

    def test_apply_sync_launch_failure_restores_config_without_claiming_synchronization(self) -> None:
        metadata = self.module.suite_metadata
        cfg = metadata.load_config()
        before = {
            self.project / "suite.config.json": (self.project / "suite.config.json").read_bytes(),
            **{path: path.read_bytes() for path in metadata.expected_files(cfg)},
        }

        def run(command: list[str]) -> None:
            if command[-1] == "sync":
                raise OSError("injected sync launch failure")

        with mock.patch.object(self.module, "run_command", side_effect=run):
            code, _stdout, stderr = self.invoke("apply", "--jotunn", "2.31.0")
        self.assertEqual(2, code)
        self.assertEqual(before, {path: path.read_bytes() for path in before})
        self.assertIn("restored suite.config.json", stderr)
        self.assertNotIn("Synchronized dependency pins and generated metadata remain applied.", stderr)

    def test_apply_config_rollback_failure_reports_potentially_split_metadata(self) -> None:
        metadata = self.module.suite_metadata
        cfg = metadata.load_config()
        before_config = (self.project / "suite.config.json").read_bytes()
        before_outputs = {path: path.read_bytes() for path in metadata.expected_files(cfg)}

        def run(command: list[str]) -> None:
            if command[-1] == "sync":
                raise subprocess.CalledProcessError(1, command)

        with mock.patch.object(self.module, "run_command", side_effect=run), mock.patch.object(
            self.module, "restore_config", side_effect=metadata.MetadataError("injected config restoration failure")
        ):
            code, _stdout, stderr = self.invoke("apply", "--jotunn", "2.31.0")
        self.assertEqual(2, code)
        self.assertNotEqual(before_config, (self.project / "suite.config.json").read_bytes())
        self.assertEqual(before_outputs, {path: path.read_bytes() for path in before_outputs})
        self.assertIn("metadata synchronization failed", stderr)
        self.assertIn("suite.config.json restoration also failed", stderr)
        self.assertIn("returned non-zero exit status 1", stderr)
        self.assertIn("injected config restoration failure", stderr)
        self.assertIn("project metadata may now be inconsistent/split", stderr)
        self.assertNotIn("Synchronized dependency pins and generated metadata remain applied.", stderr)

    def test_conflicting_primary_manifest_versions_do_not_fall_back(self) -> None:
        profile = self.project / "Profile with spaces"
        second = profile / "BepInEx" / "plugins" / "OtherJotunn"
        second.mkdir(parents=True)
        (second / "manifest.json").write_text(
            json.dumps({"name": "Jotunn", "version_number": "9.9.9"}),
            encoding="utf-8",
        )
        state = self.module.inspect_runtime()
        self.assertEqual("unknown", state.jotunn)

    def test_jotunn_profile_fallback_reports_one_valid_record(self) -> None:
        profile = self.project / "Profile with spaces"
        (profile / "BepInEx" / "plugins" / "Jotunn" / "manifest.json").unlink()
        with (profile / "mods.yml").open("a", encoding="utf-8") as output:
            output.write(
                "- manifestVersion: 1\n"
                "  name: ValheimModding-Jotunn\n"
                "  versionNumber:\n"
                "    major: 2\n"
                "    minor: 30\n"
                "    patch: 0\n"
            )
        self.assertEqual("2.30.0", self.module.inspect_runtime().jotunn)

    def test_conflicting_bepinex_manifests_do_not_fall_back(self) -> None:
        profile = self.project / "Profile with spaces"
        for name, version in (("BepInExA", "5.4.2350"), ("BepInExB", "9.9.9")):
            manifest = profile / name / "manifest.json"
            manifest.parent.mkdir()
            manifest.write_text(
                json.dumps({"name": "BepInExPack_Valheim", "version_number": version}),
                encoding="utf-8",
            )
        self.assertEqual("unknown", self.module.inspect_runtime().bepinex)

    def test_bepinex_primary_manifest_reports_one_valid_version(self) -> None:
        manifest = self.project / "Profile with spaces" / "BepInExPack" / "manifest.json"
        manifest.parent.mkdir()
        manifest.write_text(
            json.dumps({"name": "BepInExPack_Valheim", "version_number": "5.4.2350"}),
            encoding="utf-8",
        )
        self.assertEqual("5.4.2350", self.module.inspect_runtime().bepinex)

    def test_malformed_target_profile_record_is_unknown(self) -> None:
        profile = self.project / "Profile with spaces"
        (profile / "mods.yml").write_text(
            "- manifestVersion: 1\n"
            "  name: denikson-BepInExPack_Valheim\n"
            "  versionNumber:\n"
            "    major: 5\n"
            "    minor: invalid\n"
            "    patch: 2350\n",
            encoding="utf-8",
        )
        self.assertEqual("unknown", self.module.inspect_runtime().bepinex)

    def test_conflicting_bepinex_profile_records_are_unknown(self) -> None:
        profile = self.project / "Profile with spaces"
        with (profile / "mods.yml").open("a", encoding="utf-8") as output:
            output.write(
                "- manifestVersion: 1\n"
                "  name: denikson-BepInExPack_Valheim\n"
                "  versionNumber:\n"
                "    major: 9\n"
                "    minor: 9\n"
                "    patch: 9\n"
            )
        self.assertEqual("unknown", self.module.inspect_runtime().bepinex)

    def test_unrelated_malformed_profile_record_does_not_mask_bepinex(self) -> None:
        profile = self.project / "Profile with spaces"
        with (profile / "mods.yml").open("a", encoding="utf-8") as output:
            output.write("- manifestVersion: 1\n  name: Unrelated\n  versionNumber: malformed\n")
        self.assertEqual("5.4.2350", self.module.inspect_runtime().bepinex)


    def test_check_rejects_stale_generated_metadata(self) -> None:
        props = self.project / "build" / "Suite.Generated.props"
        props.write_text(props.read_text(encoding="utf-8").replace("2.30.0", "2.31.0"), encoding="utf-8")
        code, stdout, stderr = self.invoke("check")
        self.assertEqual(2, code)
        self.assertIn("stale generated file build/Suite.Generated.props", stderr)

    def test_malformed_target_manifest_is_unknown(self) -> None:
        manifest = self.project / "Profile with spaces" / "BepInEx" / "plugins" / "Jotunn" / "manifest.json"
        manifest.write_text("{not json", encoding="utf-8")
        self.assertEqual("unknown", self.module.inspect_runtime().jotunn)
    def test_invalid_version_fails_before_mutation_and_sync_failure_restores_config(self) -> None:
        before = (self.project / "suite.config.json").read_bytes()
        with mock.patch.object(self.module, "run_command") as run:
            code, _stdout, stderr = self.invoke("apply", "--jotunn", "2.30.0;touch nope")
        self.assertEqual(2, code)
        self.assertIn("jotunnVersion", stderr)
        self.assertEqual(before, (self.project / "suite.config.json").read_bytes())
        self.assertEqual([], run.call_args_list)

        def failing_sync(command: list[str]) -> None:
            if command[-1] == "sync":
                raise subprocess.CalledProcessError(1, command)

        with mock.patch.object(self.module, "run_command", side_effect=failing_sync):
            code, stdout, stderr = self.invoke("apply", "--jotunn", "2.31.0")
        self.assertEqual(2, code)
        self.assertNotIn("completed successfully", stdout)
        self.assertIn("restored suite.config.json", stderr)
        self.assertNotIn("remain applied", stderr)
        self.assertEqual(before, (self.project / "suite.config.json").read_bytes())

    def test_reference_refresh_is_serialized_while_normal_build_remains_parallel_with_spaces(self) -> None:
        spaced = Path(tempfile.mkdtemp(prefix="valheimsuite maintenance ")) / "suite with spaces"
        shutil.copytree(self.project, spaced)
        fake_bin = spaced.parent / "fake bin"
        fake_bin.mkdir()
        log = spaced.parent / "dotnet args"
        (fake_bin / "python3").write_text(
            "#!/bin/sh\nif [ \"$1\" = \"-c\" ]; then echo Sampleheim.sln; fi\n", encoding="utf-8"
        )
        (fake_bin / "dotnet").write_text("#!/bin/sh\nprintf '<%s>\\n' \"$@\" > \"$LOG\"\n", encoding="utf-8")
        for executable in fake_bin.iterdir():
            executable.chmod(0o755)
        env = {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "LOG": str(log)}
        refresh = subprocess.run(["bash", "scripts/refresh-references.sh", "Debug"], cwd=spaced, env=env, text=True, capture_output=True)
        self.assertEqual(0, refresh.returncode, refresh.stderr)
        refresh_args = log.read_text(encoding="utf-8")
        self.assertIn("<-p:ExecutePrebuild=true>", refresh_args)
        self.assertIn("<-m:1>", refresh_args)
        self.assertIn("<Sampleheim.sln>", refresh_args)

        build = subprocess.run(["bash", "scripts/build.sh", "Debug"], cwd=spaced, env=env, text=True, capture_output=True)
        self.assertEqual(0, build.returncode, build.stderr)
        self.assertNotIn("<-m:1>", log.read_text(encoding="utf-8"))
        self.assertNotIn("ExecutePrebuild", log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
