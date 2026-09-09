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

from tests.fixtures._helpers import generate_into_temp


class PreflightEnvironmentPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.params, self.root, result = generate_into_temp()
        self.assertTrue(result.ok, result.errors)
        self.preflight = self._load_preflight()

    def _load_preflight(self):
        name = f"preflight_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(name, self.root / "scripts" / "preflight.py")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(module)
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
        (managed / "Assembly-CSharp.dll").parent.mkdir(parents=True, exist_ok=True)
        (managed / "Assembly-CSharp.dll").write_bytes(b"")
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
        self.assertEqual(str(managed / "Assembly-CSharp.dll"), report["checks"]["assemblyCSharp"])
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
