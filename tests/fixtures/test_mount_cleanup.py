import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap import create_project as generator


class MountCleanupTests(unittest.TestCase):
    def test_normal_nested_cleanup_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dest = root / "dest"
            (dest / "nested").mkdir(parents=True)
            victim = root / "victim"
            victim.write_bytes(b"external")
            (dest / "nested" / "file").write_bytes(b"local")
            (dest / "link").symlink_to(victim)
            fd = os.open(dest, os.O_RDONLY | os.O_DIRECTORY)
            try:
                generator._clear_dir_contents(fd)
            finally:
                os.close(fd)
            self.assertEqual([], list(dest.iterdir()))
            self.assertEqual(b"external", victim.read_bytes())

    def test_different_mount_id_blocks_child_even_on_same_device(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child = root / "child"
            child.mkdir()
            sentinel = child / "sentinel"
            sentinel.write_bytes(b"keep")
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with mock.patch.object(generator, "_mount_id", side_effect=lambda opened: 1 if opened == fd else 2):
                    with self.assertRaisesRegex(OSError, "mount boundary"):
                        generator._clear_dir_contents(fd)
            finally:
                os.close(fd)
            self.assertEqual(b"keep", sentinel.read_bytes())

    def test_missing_mount_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "sentinel").write_bytes(b"keep")
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with mock.patch("builtins.open", side_effect=FileNotFoundError):
                    with self.assertRaises(OSError):
                        generator._clear_dir_contents(fd)
            finally:
                os.close(fd)
            self.assertEqual(b"keep", (root / "sentinel").read_bytes())

    def test_real_mount_boundaries_preserve_external_and_rejected_destination(self):
        if not all(shutil.which(command) for command in ("unshare", "mount", "umount")):
            self.skipTest("Linux unshare/mount/umount unavailable")
        probe = subprocess.run(
            ["unshare", "--user", "--map-root-user", "--mount", "true"], capture_output=True, text=True
        )
        if probe.returncode:
            self.skipTest("isolated mount namespace unavailable: " + probe.stderr.strip())
        result = subprocess.run(
            ["unshare", "--user", "--map-root-user", "--mount", "--propagation", "private",
             sys.executable, "-c", MOUNT_SCENARIO],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=120,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("bind and tmpfs boundaries preserved", result.stdout)


MOUNT_SCENARIO = '''
import os, subprocess, tempfile
from pathlib import Path
from unittest import mock
from bootstrap import create_project as generator
from bootstrap.validate_generated import ValidationResult
from tests.fixtures._helpers import make_params
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    for kind in ("bind", "tmpfs"):
        dest = root / kind
        nested = dest / "nested"
        nested.mkdir(parents=True)
        local = dest / "local"
        local.write_bytes(b"original")
        external = root / (kind + "-external")
        external.mkdir()
        if kind == "bind":
            (external / "sentinel").write_bytes(b"external")
            command = ["mount", "--bind", str(external), str(nested)]
        else:
            command = ["mount", "-t", "tmpfs", "tmpfs", str(nested)]
        subprocess.run(command, check=True)
        try:
            if kind == "tmpfs":
                (nested / "sentinel").write_bytes(b"external")
            fd = os.open(dest, os.O_RDONLY | os.O_DIRECTORY)
            child_fd = os.open(nested, os.O_RDONLY | os.O_DIRECTORY)
            try:
                assert generator._mount_id(fd) != generator._mount_id(child_fd)
                if kind == "bind":
                    assert os.fstat(fd).st_dev == os.fstat(child_fd).st_dev
                try:
                    generator._check_directory_mounts(fd, generator._mount_id(fd))
                except OSError:
                    pass
                else:
                    raise AssertionError("mounted child accepted")
            finally:
                os.close(child_fd); os.close(fd)
            with mock.patch.object(generator, "validate_generated", return_value=ValidationResult()):
                try:
                    generator.generate(make_params(), dest, force=True)
                except generator.GenerationError as exc:
                    assert "mount boundary" in str(exc), str(exc)
                else:
                    raise AssertionError("force generation accepted nested mount")
            assert local.read_bytes() == b"original"
            assert (nested / "sentinel").read_bytes() == b"external"
            # The destructive helper itself must remain safe even after preflight.
            fd = os.open(dest, os.O_RDONLY | os.O_DIRECTORY)
            try:
                try:
                    generator._clear_dir_contents(fd)
                except OSError:
                    pass
                else:
                    raise AssertionError("cleanup accepted nested mount")
            finally:
                os.close(fd)
            assert (nested / "sentinel").read_bytes() == b"external"
        finally:
            subprocess.run(["umount", str(nested)], check=True)
print("bind and tmpfs boundaries preserved")
'''
