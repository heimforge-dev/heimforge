from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

from tests.fixtures._helpers import clone_generated_temp


class PreflightEnvironmentPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.params, self.root, result = clone_generated_temp()
        self.assertTrue(result.ok, result.errors)
        self.preflight = self._load_preflight()

    def _load_preflight(self):
        name = f"preflight_{uuid.uuid4().hex}"
        scripts = self.root / "scripts"
        spec = importlib.util.spec_from_file_location(name, scripts / "preflight.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        sys.path.insert(0, str(scripts))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(scripts))
        return module

    def _write_environment(self, **values: str) -> None:
        properties = "\n".join(f"    <{name}>{value}</{name}>" for name, value in values.items())
        (self.root / "Environment.props").write_text(
            f"<Project><PropertyGroup>\n{properties}\n  </PropertyGroup></Project>\n",
            encoding="utf-8",
        )

    def _write_dev_config(self, install: Path, client_plugins: Path) -> None:
        payload = {
            "schemaVersion": 1,
            "developmentOnly": True,
            "valheimInstall": str(install),
            "clientPluginDir": str(client_plugins / self.params.root_namespace),
            "serverPluginDir": str(self.root / "server-plugins"),
            "dockerComposeFile": None,
            "serverLogFile": None,
            "solution": f"{self.params.root_namespace}.sln",
            "configuration": "Debug",
        }
        dev_config = self.root / ".valheim" / "dev.json"
        dev_config.parent.mkdir(exist_ok=True)
        dev_config.write_text(json.dumps(payload), encoding="utf-8")

    def _write_runtime_files(self, managed: Path, bepinex: Path, jotunn_relative_path: Path) -> Path:
        (managed / "assembly_valheim.dll").parent.mkdir(parents=True, exist_ok=True)
        (managed / "assembly_valheim.dll").write_bytes(b"")
        (bepinex / "core").mkdir(parents=True, exist_ok=True)
        (bepinex / "core" / "BepInEx.dll").write_bytes(b"")
        jotunn = bepinex / "plugins" / jotunn_relative_path
        jotunn.parent.mkdir(parents=True, exist_ok=True)
        jotunn.write_bytes(b"")
        return jotunn

    def _run_nonportable_preflight(self) -> tuple[int, dict]:
        output = io.StringIO()
        completed = subprocess.CompletedProcess([], 0, stdout="ok")
        with (
            mock.patch.object(self.preflight, "run", return_value=completed),
            mock.patch.object(self.preflight.shutil, "which", return_value="/usr/bin/tool"),
            mock.patch.object(self.preflight.sys, "argv", ["preflight.py", "--json"]),
            contextlib.redirect_stdout(output),
        ):
            result = self.preflight.main()
        return result, json.loads(output.getvalue())

    def test_uses_default_same_install_layout(self) -> None:
        install = self.root / "SteamLibrary" / "steamapps" / "common" / "Valheim"
        managed = install / "valheim_Data" / "Managed"
        bepinex = install / "BepInEx"
        jotunn = self._write_runtime_files(managed, bepinex, Path("Jotunn.dll"))
        self._write_environment(
            VALHEIM_INSTALL=str(install),
            VALHEIM_MANAGED="$(VALHEIM_INSTALL)/valheim_Data/Managed",
            BEPINEX_PATH="$(VALHEIM_INSTALL)/BepInEx",
            MOD_DEPLOYPATH="$(BEPINEX_PATH)/plugins/Sampleheim",
        )
        self._write_dev_config(install, bepinex / "plugins")

        status, report = self._run_nonportable_preflight()

        self.assertEqual(0, status, report)
        self.assertTrue(report["ok"], report)
        self.assertEqual(str(managed / "assembly_valheim.dll"), report["checks"]["gameAssembly"])
        self.assertEqual(str(bepinex / "core" / "BepInEx.dll"), report["checks"]["bepInEx"])
        self.assertEqual(str(jotunn), report["checks"]["jotunn"])

    def test_uses_split_thunderstore_bepinex_and_nested_jotunn(self) -> None:
        install = self.root / "SteamLibrary" / "steamapps" / "common" / "Valheim"
        managed = install / "valheim_Data" / "Managed"
        bepinex = self.root / "Thunderstore" / "profiles" / "Vibeheim Dev" / "BepInEx"
        jotunn = self._write_runtime_files(managed, bepinex, Path("Jotunn") / "dependencies" / "Jotunn.dll")
        self._write_environment(
            VALHEIM_INSTALL=str(install),
            VALHEIM_MANAGED="$(VALHEIM_INSTALL)/valheim_Data/Managed",
            BEPINEX_PATH=str(bepinex),
            MOD_DEPLOYPATH="$(BEPINEX_PATH)/plugins/Sampleheim",
        )
        self._write_dev_config(install, bepinex / "plugins")

        status, report = self._run_nonportable_preflight()

        self.assertEqual(0, status, report)
        self.assertTrue(report["ok"], report)
        self.assertEqual(str(bepinex / "core" / "BepInEx.dll"), report["checks"]["bepInEx"])
        self.assertEqual(str(jotunn), report["checks"]["jotunn"])

    def test_gameplay_assembly_prefers_current_layout(self) -> None:
        managed = self.root / "current-managed"
        managed.mkdir()
        (managed / "Assembly-CSharp.dll").write_bytes(b"legacy")
        (managed / "assembly_valheim.dll").write_bytes(b"current")

        self.assertEqual(managed / "assembly_valheim.dll", self.preflight.resolve_game_assembly(managed))

    def test_gameplay_assembly_falls_back_to_legacy_layout(self) -> None:
        managed = self.root / "legacy-managed"
        managed.mkdir()
        (managed / "Assembly-CSharp.dll").write_bytes(b"legacy")

        self.assertEqual(managed / "Assembly-CSharp.dll", self.preflight.resolve_game_assembly(managed))

    def test_gameplay_assembly_reports_missing_known_layouts(self) -> None:
        managed = self.root / "empty-managed"
        managed.mkdir()

        with self.assertRaisesRegex(
            self.preflight.PreflightError,
            r"gameplay assembly not found.*assembly_valheim\.dll or Assembly-CSharp\.dll",
        ):
            self.preflight.resolve_game_assembly(managed)

    def test_uses_configured_managed_path_for_gameplay_assembly(self) -> None:
        install = self.root / "SteamLibrary" / "steamapps" / "common" / "Valheim"
        managed = self.root / "custom-managed"
        bepinex = install / "BepInEx"
        jotunn = self._write_runtime_files(managed, bepinex, Path("Jotunn.dll"))
        self._write_environment(
            VALHEIM_INSTALL=str(install),
            VALHEIM_MANAGED=str(managed),
            BEPINEX_PATH="$(VALHEIM_INSTALL)/BepInEx",
            MOD_DEPLOYPATH="$(BEPINEX_PATH)/plugins/Sampleheim",
        )
        self._write_dev_config(install, bepinex / "plugins")

        status, report = self._run_nonportable_preflight()

        self.assertEqual(0, status, report)
        self.assertTrue(report["ok"], report)
        self.assertEqual(
            str(managed / "assembly_valheim.dll"),
            report["checks"]["gameAssembly"],
        )
        self.assertEqual(str(jotunn), report["checks"]["jotunn"])

    def test_expands_supported_property_references(self) -> None:
        self._write_environment(
            VALHEIM_INSTALL="/mnt/d/SteamLibrary/steamapps/common/Valheim",
            VALHEIM_MANAGED="$(VALHEIM_INSTALL)/valheim_Data/Managed",
            BEPINEX_PATH="$(VALHEIM_INSTALL)/BepInEx",
            MOD_DEPLOYPATH="$(BEPINEX_PATH)/plugins/Sampleheim",
        )

        values = self.preflight.parse_environment_props(self.root / "Environment.props")

        self.assertEqual("/mnt/d/SteamLibrary/steamapps/common/Valheim/valheim_Data/Managed", values["VALHEIM_MANAGED"])
        self.assertEqual("/mnt/d/SteamLibrary/steamapps/common/Valheim/BepInEx", values["BEPINEX_PATH"])
        self.assertEqual("/mnt/d/SteamLibrary/steamapps/common/Valheim/BepInEx/plugins/Sampleheim", values["MOD_DEPLOYPATH"])

    def test_rejects_unknown_property_reference(self) -> None:
        self._write_environment(VALHEIM_INSTALL="$(UNKNOWN_PROPERTY)/Valheim")

        with self.assertRaisesRegex(
            self.preflight.PreflightError,
            r"unknown Environment\.props property reference: \$\(UNKNOWN_PROPERTY\)",
        ):
            self.preflight.parse_environment_props(self.root / "Environment.props")

    def test_rejects_cyclic_property_reference(self) -> None:
        self._write_environment(
            VALHEIM_MANAGED="$(BEPINEX_PATH)",
            BEPINEX_PATH="$(VALHEIM_MANAGED)",
        )

        with self.assertRaisesRegex(
            self.preflight.PreflightError,
            r"cyclic Environment\.props property reference: VALHEIM_MANAGED -> BEPINEX_PATH -> VALHEIM_MANAGED",
        ):
            self.preflight.parse_environment_props(self.root / "Environment.props")

    def test_rejects_unresolved_property_reference(self) -> None:
        self._write_environment(VALHEIM_MANAGED="$(VALHEIM_INSTALL)/valheim_Data/Managed")

        with self.assertRaisesRegex(
            self.preflight.PreflightError,
            r"unresolved Environment\.props property reference: \$\(VALHEIM_INSTALL\)",
        ):
            self.preflight.parse_environment_props(self.root / "Environment.props")


if __name__ == "__main__":
    unittest.main()
