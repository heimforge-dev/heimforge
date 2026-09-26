from __future__ import annotations

import shutil
import unittest
import zipfile

from tests.fixtures._helpers import (
    clone_generated_temp,
    import_scripts_from,
    write_fake_artifacts,
)


class ReleaseLicensingTests(unittest.TestCase):
    def setUp(self) -> None:
        _params, self.root, result = clone_generated_temp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.assertTrue(result.ok, result.errors)

        self.metadata, self.package = import_scripts_from(self.root / "scripts")
        self.cfg = self.metadata.load_config()

    def release_error(self) -> str:
        with self.assertRaises(self.metadata.MetadataError) as ctx:
            self.metadata.validate(
                self.cfg,
                release=True,
                structural_only=True,
            )
        return str(ctx.exception)

    def test_generated_scaffold_retains_mit0_provenance(self) -> None:
        license_path = self.root / "LICENSES" / "MIT-0.txt"

        self.assertTrue(license_path.is_file())
        self.assertIn("MIT No Attribution", license_path.read_text(encoding="utf-8"))
        self.assertTrue((self.root / "LICENSE.todo").is_file())
        self.assertFalse((self.root / "LICENSE").exists())

    def test_release_rejects_missing_license(self) -> None:
        (self.root / "LICENSE.todo").unlink()

        error = self.release_error()

        self.assertIn("LICENSE", error)
        self.assertNotIn("LICENSE.todo", error)

    def test_release_rejects_empty_license(self) -> None:
        (self.root / "LICENSE.todo").unlink()
        (self.root / "LICENSE").write_text("", encoding="utf-8")

        error = self.release_error()

        self.assertIn("LICENSE", error)
        self.assertNotIn("LICENSE.todo", error)

    def test_release_rejects_non_utf8_license(self) -> None:
        (self.root / "LICENSE.todo").unlink()
        (self.root / "LICENSE").write_bytes(b"\xff\xfe\xfd")

        error = self.release_error()

        self.assertIn("LICENSE", error)

    def test_release_rejects_lingering_license_todo(self) -> None:
        (self.root / "LICENSE").write_text(
            "Example selected project license\n",
            encoding="utf-8",
        )

        error = self.release_error()

        self.assertIn("LICENSE.todo", error)

    def test_release_accepts_selected_license_and_removed_todo(self) -> None:
        (self.root / "LICENSE").write_text(
            "Example selected project license\n",
            encoding="utf-8",
        )
        (self.root / "LICENSE.todo").unlink()

        self.metadata.validate(
            self.cfg,
            release=True,
            structural_only=True,
        )


    def create_packages(self):
        write_fake_artifacts(
            self.root,
            self.cfg,
            configuration="Release",
        )
        (self.root / "artifacts" / "packages").mkdir(
            parents=True,
            exist_ok=True,
        )

        archives = []
        for name, modules, kind in self.metadata.package_definitions(self.cfg):
            archives.append(
                self.package.create_package(
                    name,
                    self.cfg["suiteVersion"],
                    modules,
                    self.cfg,
                    kind,
                )
            )
        return archives

    def test_packaging_without_selected_license_does_not_invent_one(self) -> None:
        self.assertFalse((self.root / "LICENSE").exists())
        self.assertTrue((self.root / "LICENSE.todo").is_file())

        for archive in self.create_packages():
            with self.subTest(archive=archive.name):
                with zipfile.ZipFile(archive) as package:
                    self.assertNotIn("LICENSE", package.namelist())

    def test_packaging_includes_selected_license_verbatim(self) -> None:
        license_text = "Example selected project license\nSecond line\n"
        (self.root / "LICENSE").write_text(
            license_text,
            encoding="utf-8",
        )

        # Packaging is intentionally less strict than the public-release
        # gate: development packages may still be produced while the
        # LICENSE.todo reminder remains.
        self.assertTrue((self.root / "LICENSE.todo").is_file())

        for archive in self.create_packages():
            with self.subTest(archive=archive.name):
                with zipfile.ZipFile(archive) as package:
                    self.assertEqual(
                        license_text,
                        package.read("LICENSE").decode("utf-8"),
                    )


if __name__ == "__main__":
    unittest.main()
