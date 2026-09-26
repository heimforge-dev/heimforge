from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap import update_dependency_baseline as updater


def different_version(current: str, preferred: str) -> str:
    if current != preferred:
        return preferred
    return "0.0.0" if current != "0.0.0" else "0.0.1"


class DependencyBaselineUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_model = updater.MODEL_PATH.read_text(encoding="utf-8")
        self.source_manifest = updater.MANIFEST_PATH.read_text(encoding="utf-8")

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

        bootstrap_dir = self.root / "bootstrap"
        bootstrap_dir.mkdir()

        self.model_path = bootstrap_dir / "model.py"
        self.manifest_path = self.root / "BOOTSTRAP_MANIFEST.json"
        self.model_path.write_text(self.source_model, encoding="utf-8")
        self.manifest_path.write_text(self.source_manifest, encoding="utf-8")

        for name, value in (
            ("ROOT", self.root),
            ("MODEL_PATH", self.model_path),
            ("MANIFEST_PATH", self.manifest_path),
        ):
            patcher = mock.patch.object(updater, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.initial, _model, _manifest = updater._load_authorities()
        self.other_jotunn = different_version(self.initial.jotunn, "9.9.9")
        self.other_bepinex = different_version(self.initial.bepinex, "8.8.8")
        self.other_netfx = different_version(self.initial.netfx, "7.7.7")

    def snapshot(self) -> tuple[bytes, bytes]:
        return self.model_path.read_bytes(), self.manifest_path.read_bytes()

    def test_noop_preserves_both_authorities_byte_for_byte(self) -> None:
        before = self.snapshot()

        result = updater.update_baseline(
            jotunn=self.initial.jotunn,
            bepinex=self.initial.bepinex,
        )

        self.assertEqual(self.initial, result)
        self.assertEqual(before, self.snapshot())

    def test_updates_only_requested_jotunn_pin_with_minimal_text_diff(self) -> None:
        target = self.other_jotunn

        result = updater.update_baseline(jotunn=target, bepinex=None)

        self.assertEqual(target, result.jotunn)
        self.assertEqual(self.initial.bepinex, result.bepinex)

        expected_model = self.source_model.replace(
            f'"jotunn_version": "{self.initial.jotunn}"',
            f'"jotunn_version": "{target}"',
            1,
        )
        expected_manifest = self.source_manifest.replace(
            f'"Jotunn": "{self.initial.jotunn}"',
            f'"Jotunn": "{target}"',
            1,
        )
        self.assertEqual(expected_model, self.model_path.read_text(encoding="utf-8"))
        self.assertEqual(expected_manifest, self.manifest_path.read_text(encoding="utf-8"))

    def test_updates_both_pins_and_reloads_matching_authorities(self) -> None:
        target = updater.Baseline(
            jotunn=self.other_jotunn,
            bepinex=self.other_bepinex,
            netfx=self.initial.netfx,
        )

        result = updater.update_baseline(
            jotunn=target.jotunn,
            bepinex=target.bepinex,
        )

        self.assertEqual(target, result)
        verified, _model, _manifest = updater._load_authorities()
        self.assertEqual(target, verified)

    def test_invalid_requested_version_fails_before_mutation(self) -> None:
        before = self.snapshot()

        with self.assertRaises(updater.BaselineUpdateError):
            updater.update_baseline(jotunn="2.30", bepinex=None)

        self.assertEqual(before, self.snapshot())

    def test_preexisting_authority_disagreement_fails_before_mutation(self) -> None:
        mismatched = self.source_manifest.replace(
            f'"Jotunn": "{self.initial.jotunn}"',
            f'"Jotunn": "{self.other_jotunn}"',
            1,
        )
        self.manifest_path.write_text(mismatched, encoding="utf-8")
        before = self.snapshot()

        with self.assertRaisesRegex(
            updater.BaselineUpdateError,
            "dependency baseline authorities disagree before mutation",
        ):
            updater.update_baseline(jotunn=self.other_jotunn, bepinex=None)

        self.assertEqual(before, self.snapshot())

    def test_netfx_authority_disagreement_fails_before_mutation(self) -> None:
        mismatched = self.source_manifest.replace(
            f'"Microsoft.NETFramework.ReferenceAssemblies": "{self.initial.netfx}"',
            f'"Microsoft.NETFramework.ReferenceAssemblies": "{self.other_netfx}"',
            1,
        )
        self.manifest_path.write_text(mismatched, encoding="utf-8")
        before = self.snapshot()

        with self.assertRaisesRegex(
            updater.BaselineUpdateError,
            "dependency baseline authorities disagree before mutation",
        ):
            updater.update_baseline(jotunn=self.other_jotunn, bepinex=None)

        self.assertEqual(before, self.snapshot())

    def test_second_authority_write_failure_rolls_back_first_authority(self) -> None:
        before_model = self.model_path.read_text(encoding="utf-8")
        before_manifest = self.manifest_path.read_text(encoding="utf-8")
        real_write = updater._atomic_write_text
        injected = False

        def write_with_failure(path: Path, content: str) -> None:
            nonlocal injected
            if (
                path == self.manifest_path
                and content != before_manifest
                and not injected
            ):
                injected = True
                raise OSError("simulated manifest write failure")
            real_write(path, content)

        with mock.patch.object(
            updater,
            "_atomic_write_text",
            side_effect=write_with_failure,
        ):
            with self.assertRaisesRegex(OSError, "simulated manifest write failure"):
                updater.update_baseline(
                    jotunn=self.other_jotunn,
                    bepinex=self.other_bepinex,
                )

        self.assertTrue(injected)
        self.assertEqual(before_model, self.model_path.read_text(encoding="utf-8"))
        self.assertEqual(before_manifest, self.manifest_path.read_text(encoding="utf-8"))

    def test_duplicate_authority_entry_is_rejected(self) -> None:
        duplicate = self.source_model.replace(
            '    "bepinex_version":',
            '    "jotunn_version": "1.2.3",\n    "bepinex_version":',
            1,
        )
        self.model_path.write_text(duplicate, encoding="utf-8")
        before = self.snapshot()

        with self.assertRaisesRegex(
            updater.BaselineUpdateError,
            "expected exactly one bootstrap/model.py Jötunn baseline entry",
        ):
            updater.update_baseline(jotunn="9.9.9", bepinex=None)

        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
