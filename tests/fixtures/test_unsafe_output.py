import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootstrap import create_project
from bootstrap.create_project import (
    GenerationError,
    _VCS_MARKERS,
    _AtomicPromotionUnavailable,
    _dir_content_state,
    _generate_isolated_name,
    _open_dir_at,
    _safe_output_dir,
    generate,
    validate_generated,
)
from bootstrap.validate_generated import ValidationResult
from tests.fixtures._helpers import make_params


class UnsafeOutputTests(unittest.TestCase):
    def test_non_empty_output_is_refused_without_force(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        sentinel = output_dir / "pre-existing.txt"
        sentinel.write_text("do not touch", encoding="utf-8")

        with self.assertRaises(GenerationError):
            generate(make_params(), output_dir)

        self.assertTrue(sentinel.is_file())
        self.assertEqual("do not touch", sentinel.read_text(encoding="utf-8"))

    def test_non_empty_output_is_overwritten_with_force(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        (output_dir / "pre-existing.txt").write_text("stale", encoding="utf-8")

        result = generate(make_params(), output_dir, force=True)

        self.assertTrue(result.ok, result.errors)
        self.assertFalse((output_dir / "pre-existing.txt").exists())
        self.assertTrue((output_dir / "Sampleheim.sln").is_file())

    def test_safe_output_dir_rejects_root_and_home(self):
        for bad in ("/", "~"):
            with self.assertRaises(GenerationError):
                _safe_output_dir(bad)

    def test_safe_output_dir_rejects_bootstrapper_repository_and_ancestors(self):
        bootstrapper_root = Path(__file__).resolve().parents[2]
        for bad in (str(bootstrapper_root), "~/src", str(bootstrapper_root.parent)):
            with self.assertRaises(GenerationError):
                _safe_output_dir(bad)

    def test_safe_output_dir_accepts_sibling_directory(self):
        accepted = _safe_output_dir("~/src/vibeheim")
        self.assertEqual(Path.home() / "src" / "vibeheim", accepted)

    def test_safe_output_dir_rejects_bootstrapper_descendant(self):
        bootstrapper_root = Path(__file__).resolve().parents[2]
        with self.assertRaises(GenerationError):
            _safe_output_dir(str(bootstrapper_root / "template"))

    def test_generate_rejects_unsafe_targets_without_deleting_anything(self):
        bootstrapper_root = Path(__file__).resolve().parents[2]
        unsafe_targets = ("/", str(Path.home()), str(bootstrapper_root), str(bootstrapper_root / "template"))
        with mock.patch("bootstrap.create_project._renameat2_noreplace") as renameat2:
            for target in unsafe_targets:
                with self.assertRaises(GenerationError):
                    generate(make_params(), Path(target), force=True)
            renameat2.assert_not_called()
        self.assertTrue((bootstrapper_root / "template").is_dir())

    def test_generate_refuses_existing_git_repository_even_with_force(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        (output_dir / ".git").mkdir()
        (output_dir / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        (output_dir / "valuable").write_text("do not touch", encoding="utf-8")

        with self.assertRaises(GenerationError):
            generate(make_params(), output_dir, force=True)

        self.assertTrue((output_dir / ".git" / "config").is_file())
        self.assertTrue((output_dir / "valuable").is_file())

    def test_generate_rejects_mount_points_without_deleting_anything(self):
        mount_targets = ("/mnt/c", "/proc", "/dev", "/sys")
        with mock.patch("bootstrap.create_project._renameat2_noreplace") as renameat2:
            for target in mount_targets:
                with self.subTest(target=target):
                    self.assertTrue(Path(target).is_mount(), f"{target} is not a mount point in this environment")
                    with self.assertRaises(GenerationError):
                        generate(make_params(), Path(target), force=True)
            renameat2.assert_not_called()

    def test_safe_output_dir_accepts_directory_beneath_a_mount_point(self):
        mount = next(p for p in ("/mnt/c", "/proc", "/dev", "/sys") if Path(p).is_mount())
        candidate = Path(mount) / "not-a-real-mount-child"
        accepted = _safe_output_dir(str(candidate))
        self.assertEqual(candidate, accepted)

    def test_generate_refuses_vcs_marker_directory_for_hg_and_svn(self):
        for marker in (".hg", ".svn"):
            with self.subTest(marker=marker):
                output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
                (output_dir / marker).mkdir()
                (output_dir / "valuable").write_text("do not touch", encoding="utf-8")

                with self.assertRaises(GenerationError):
                    generate(make_params(), output_dir, force=True)

                self.assertTrue((output_dir / marker).is_dir())
                self.assertTrue((output_dir / "valuable").is_file())

    def test_generate_refuses_vcs_marker_represented_as_a_regular_file(self):
        for marker in _VCS_MARKERS:
            with self.subTest(marker=marker):
                output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
                (output_dir / marker).write_text("gitdir: ../.git/worktrees/x\n", encoding="utf-8")
                (output_dir / "valuable").write_text("do not touch", encoding="utf-8")

                with self.assertRaises(GenerationError):
                    generate(make_params(), output_dir, force=True)

                self.assertTrue((output_dir / marker).is_file())
                self.assertTrue((output_dir / "valuable").is_file())

    def test_generate_refuses_vcs_marker_represented_as_a_dangling_symlink(self):
        for marker in _VCS_MARKERS:
            with self.subTest(marker=marker):
                output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
                (output_dir / marker).symlink_to(output_dir / "nowhere")
                (output_dir / "valuable").write_text("do not touch", encoding="utf-8")

                with self.assertRaises(GenerationError):
                    generate(make_params(), output_dir, force=True)

                self.assertTrue((output_dir / marker).is_symlink())
                self.assertTrue((output_dir / "valuable").is_file())

    def test_dir_content_state_detects_vcs_marker_as_directory_file_and_symlink(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        is_empty, has_vcs = self._scan(output_dir)
        self.assertTrue(is_empty)
        self.assertFalse(has_vcs)

        marker_forms = {
            "directory": lambda p: p.mkdir(),
            "regular file": lambda p: p.write_text("gitdir: ../.git/worktrees/x\n", encoding="utf-8"),
            "symlink": lambda p: p.symlink_to(output_dir / "nowhere"),
        }
        for kind, make_marker in marker_forms.items():
            with self.subTest(kind=kind):
                fresh = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
                make_marker(fresh / ".git")
                is_empty, has_vcs = self._scan(fresh)
                self.assertFalse(is_empty)
                self.assertTrue(has_vcs)

    def _scan(self, output_dir):
        parent_fd = os.open(output_dir.parent, os.O_DIRECTORY)
        try:
            fd = _open_dir_at(output_dir.name, parent_fd)
            try:
                return _dir_content_state(fd)
            finally:
                os.close(fd)
        finally:
            os.close(parent_fd)

    def test_generate_does_not_promote_staging_when_validation_fails(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        sentinel = output_dir / "pre-existing.txt"
        sentinel.write_text("do not touch", encoding="utf-8")
        failing_result = ValidationResult(errors=["injected invalid output"])

        with mock.patch("bootstrap.create_project.validate_generated", return_value=failing_result):
            result = generate(make_params(), output_dir, force=True)

        self.assertFalse(result.ok)
        self.assertEqual(["injected invalid output"], result.errors)
        self.assertTrue(sentinel.is_file())
        self.assertEqual("do not touch", sentinel.read_text(encoding="utf-8"))

    def test_generate_aborts_swap_when_destination_becomes_a_vcs_checkout_during_staging(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        sentinel = output_dir / "sentinel.txt"
        sentinel.write_text("do not touch", encoding="utf-8")

        def inject_git_then_validate(staging_dir, params):
            (output_dir / ".git").mkdir()
            return validate_generated(staging_dir, params)

        with mock.patch("bootstrap.create_project.validate_generated", side_effect=inject_git_then_validate):
            with self.assertRaises(GenerationError):
                generate(make_params(), output_dir, force=True)

        self.assertTrue((output_dir / ".git").is_dir())
        self.assertTrue(sentinel.is_file())
        self.assertEqual("do not touch", sentinel.read_text(encoding="utf-8"))

    def test_generate_restores_original_when_promotion_rename_fails(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        sentinel = output_dir / "sentinel.txt"
        sentinel.write_text("original content", encoding="utf-8")
        real_renameat2 = create_project._renameat2_noreplace

        def fail_only_promotion(src_name, dst_name, dir_fd):
            if dst_name == output_dir.name and src_name.startswith(f".{output_dir.name}.staging-"):
                raise OSError("simulated promotion failure")
            return real_renameat2(src_name, dst_name, dir_fd)

        with mock.patch("bootstrap.create_project._renameat2_noreplace", side_effect=fail_only_promotion):
            with self.assertRaises(GenerationError):
                generate(make_params(), output_dir, force=True)

        self.assertTrue(output_dir.is_dir())
        self.assertEqual("original content", (output_dir / "sentinel.txt").read_text(encoding="utf-8"))
        self.assertEqual([], list(output_dir.parent.glob(f".{output_dir.name}.isolated-*")))

    def test_generate_preserves_backup_when_promotion_and_restore_both_fail(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        sentinel = output_dir / "sentinel.txt"
        sentinel.write_text("original content", encoding="utf-8")
        real_renameat2 = create_project._renameat2_noreplace

        def always_fail_into_destination(src_name, dst_name, dir_fd):
            if dst_name == output_dir.name:
                raise OSError("simulated failure")
            return real_renameat2(src_name, dst_name, dir_fd)

        with mock.patch("bootstrap.create_project._renameat2_noreplace", side_effect=always_fail_into_destination):
            with self.assertRaises(GenerationError):
                generate(make_params(), output_dir, force=True)

        backups = list(output_dir.parent.glob(f".{output_dir.name}.isolated-*"))
        self.assertEqual(1, len(backups))
        self.assertEqual("original content", (backups[0] / "sentinel.txt").read_text(encoding="utf-8"))
        for backup in backups:
            shutil.rmtree(backup, ignore_errors=True)

    def test_generate_leaves_no_backup_directories_after_successful_overwrite(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        (output_dir / "stale.txt").write_text("stale", encoding="utf-8")

        result = generate(make_params(), output_dir, force=True)

        self.assertTrue(result.ok, result.errors)
        self.assertFalse((output_dir / "stale.txt").exists())
        self.assertEqual([], list(output_dir.parent.glob(f".{output_dir.name}.isolated-*")))
        self.assertEqual([], list(output_dir.parent.glob(f".{output_dir.name}.staging-*")))

    def test_generate_rejects_output_dir_that_is_already_a_symlink(self):
        workspace = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        victim = workspace / "victim"
        victim.mkdir()
        (victim / "precious.bin").write_bytes(b"do not touch\x00\x01")
        link = workspace / "link"
        link.symlink_to(victim)

        with self.assertRaises(GenerationError):
            generate(make_params(), link, force=True)

        self.assertTrue(link.is_symlink())
        self.assertEqual(victim, Path(os.readlink(link)))
        self.assertEqual(b"do not touch\x00\x01", (victim / "precious.bin").read_bytes())

    def test_generate_aborts_when_destination_appears_during_staging_without_force(self):
        workspace = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        output_dir = workspace / "brand-new-project"

        def inject_destination_then_validate(staging_dir, params):
            output_dir.mkdir()
            (output_dir / "sentinel.bin").write_bytes(b"unrelated user data\x00\x01")
            return validate_generated(staging_dir, params)

        with mock.patch("bootstrap.create_project.validate_generated", side_effect=inject_destination_then_validate):
            with self.assertRaises(GenerationError):
                generate(make_params(), output_dir, force=False)

        self.assertTrue((output_dir / "sentinel.bin").is_file())
        self.assertEqual(b"unrelated user data\x00\x01", (output_dir / "sentinel.bin").read_bytes())
        self.assertFalse((output_dir / "Sampleheim.sln").exists())

    def test_generate_aborts_when_destination_appears_during_staging_with_force(self):
        workspace = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        output_dir = workspace / "brand-new-project"

        def inject_destination_then_validate(staging_dir, params):
            output_dir.mkdir()
            (output_dir / "sentinel.bin").write_bytes(b"unrelated user data\x00\x01")
            return validate_generated(staging_dir, params)

        with mock.patch("bootstrap.create_project.validate_generated", side_effect=inject_destination_then_validate):
            with self.assertRaises(GenerationError):
                generate(make_params(), output_dir, force=True)

        self.assertTrue((output_dir / "sentinel.bin").is_file())
        self.assertEqual(b"unrelated user data\x00\x01", (output_dir / "sentinel.bin").read_bytes())
        self.assertFalse((output_dir / "Sampleheim.sln").exists())

    def test_generate_aborts_when_destination_becomes_a_symlink_to_a_victim_directory(self):
        workspace = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        output_dir = workspace / "brand-new-project"
        victim = workspace / "victim"
        victim.mkdir()
        (victim / "precious.bin").write_bytes(b"victim data\x00\x01")

        def inject_symlink_then_validate(staging_dir, params):
            output_dir.symlink_to(victim)
            return validate_generated(staging_dir, params)

        with mock.patch("bootstrap.create_project.validate_generated", side_effect=inject_symlink_then_validate):
            with self.assertRaises(GenerationError):
                generate(make_params(), output_dir, force=False)

        self.assertTrue(output_dir.is_symlink())
        self.assertEqual(victim, Path(os.readlink(output_dir)))
        self.assertEqual(b"victim data\x00\x01", (victim / "precious.bin").read_bytes())

    def test_generate_aborts_when_approved_destination_is_swapped_for_a_different_object(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        (output_dir / "original.txt").write_text("original content", encoding="utf-8")
        replacement = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-replacement-"))
        (replacement / "swapped.txt").write_text("swapped content", encoding="utf-8")

        def inject_swap_then_validate(staging_dir, params):
            shutil.rmtree(output_dir)
            replacement.rename(output_dir)
            return validate_generated(staging_dir, params)

        with mock.patch("bootstrap.create_project.validate_generated", side_effect=inject_swap_then_validate):
            with self.assertRaises(GenerationError):
                generate(make_params(), output_dir, force=True)

        self.assertTrue((output_dir / "swapped.txt").is_file())
        self.assertEqual("swapped content", (output_dir / "swapped.txt").read_text(encoding="utf-8"))

    def test_generate_survives_a_new_entry_created_between_isolation_and_promotion(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        sentinel = output_dir / "sentinel.txt"
        sentinel.write_text("original content", encoding="utf-8")
        real_renameat2 = create_project._renameat2_noreplace

        def race_condition_renameat2(src_name, dst_name, dir_fd):
            if dst_name == output_dir.name and src_name.startswith(f".{output_dir.name}.staging-"):
                output_dir.mkdir()
                (output_dir / "interloper.txt").write_text("interloper content", encoding="utf-8")
            return real_renameat2(src_name, dst_name, dir_fd)

        with mock.patch("bootstrap.create_project._renameat2_noreplace", side_effect=race_condition_renameat2):
            with self.assertRaises(GenerationError):
                generate(make_params(), output_dir, force=True)

        self.assertTrue((output_dir / "interloper.txt").is_file())
        self.assertEqual("interloper content", (output_dir / "interloper.txt").read_text(encoding="utf-8"))
        backups = list(output_dir.parent.glob(f".{output_dir.name}.isolated-*"))
        self.assertEqual(1, len(backups))
        self.assertEqual("original content", (backups[0] / "sentinel.txt").read_text(encoding="utf-8"))
        for backup in backups:
            shutil.rmtree(backup, ignore_errors=True)

    def test_renaming_a_symlink_entry_moves_the_link_not_its_target(self):
        workspace = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        victim = workspace / "victim"
        victim.mkdir()
        (victim / "data.bin").write_bytes(b"\x00\x01precious\xff")
        link = workspace / "link"
        link.symlink_to(victim)

        moved = workspace / "moved"
        os.rename(link, moved)

        self.assertTrue(moved.is_symlink())
        self.assertEqual(victim, Path(os.readlink(moved)))
        self.assertTrue(victim.is_dir())
        self.assertEqual(b"\x00\x01precious\xff", (victim / "data.bin").read_bytes())

    def test_generate_aborts_when_initially_empty_destination_gains_content_before_promotion(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        # output_dir exists and is empty; approved with force=False.

        def inject_content_then_validate(staging_dir, params):
            (output_dir / "sentinel.bin").write_bytes(b"unrelated user data\x00\x01")
            return validate_generated(staging_dir, params)

        with mock.patch("bootstrap.create_project.validate_generated", side_effect=inject_content_then_validate):
            with self.assertRaises(GenerationError):
                generate(make_params(), output_dir, force=False)

        self.assertTrue((output_dir / "sentinel.bin").is_file())
        self.assertEqual(b"unrelated user data\x00\x01", (output_dir / "sentinel.bin").read_bytes())
        self.assertFalse((output_dir / "Sampleheim.sln").exists())

    def test_generate_survives_parent_directory_renamed_during_staging(self):
        workspace = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        approved_parent = workspace / "approved-parent"
        approved_parent.mkdir()
        output_dir = approved_parent / "project"

        def inject_parent_rebind_then_validate(staging_dir, params):
            moved_parent = workspace / "approved-parent-moved"
            approved_parent.rename(moved_parent)
            replacement_parent = approved_parent  # recreated at the OLD pathname
            replacement_parent.mkdir()
            (replacement_parent / "unrelated.bin").write_bytes(b"UNRELATED DATA - DO NOT TOUCH")
            return validate_generated(staging_dir, params)

        with mock.patch(
            "bootstrap.create_project.validate_generated", side_effect=inject_parent_rebind_then_validate
        ):
            result = generate(make_params(), output_dir, force=False)

        self.assertTrue(result.ok, result.errors)
        moved_parent = workspace / "approved-parent-moved"
        self.assertTrue((moved_parent / "project" / "Sampleheim.sln").is_file())
        replacement_parent = workspace / "approved-parent"
        self.assertTrue((replacement_parent / "unrelated.bin").is_file())
        self.assertEqual(b"UNRELATED DATA - DO NOT TOUCH", (replacement_parent / "unrelated.bin").read_bytes())
        self.assertFalse((replacement_parent / "project").exists())

    def test_generate_preserves_content_added_to_isolated_backup_before_cleanup(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        # output_dir exists and is empty; approved with force=False.
        backup_name = f".{output_dir.name}.isolated-fixed-for-test"
        backup_path = output_dir.parent / backup_name
        real_renameat2 = create_project._renameat2_noreplace

        def inject_after_isolation(src_name, dst_name, dir_fd):
            if src_name.startswith(f".{output_dir.name}.staging-"):
                # isolation + verification already happened; sneak content
                # into the (still undeleted) backup before promotion.
                (backup_path / "late.bin").write_bytes(b"added after verification\x00")
            return real_renameat2(src_name, dst_name, dir_fd)

        with mock.patch("bootstrap.create_project._generate_isolated_name", return_value=backup_name), mock.patch(
            "bootstrap.create_project._renameat2_noreplace", side_effect=inject_after_isolation
        ):
            result = generate(make_params(), output_dir, force=False)

        self.assertTrue(result.ok, result.errors)
        self.assertTrue((output_dir / "Sampleheim.sln").is_file())
        # the backup was preserved (not deleted) because unexpected content
        # appeared in it after verification but before cleanup
        self.assertTrue(backup_path.is_dir())
        self.assertEqual(b"added after verification\x00", (backup_path / "late.bin").read_bytes())
        shutil.rmtree(backup_path, ignore_errors=True)

    def test_generate_never_deletes_a_replacement_planted_under_the_isolated_backup_name(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        (output_dir / "sentinel.txt").write_text("original content", encoding="utf-8")
        backup_name = f".{output_dir.name}.isolated-fixed-for-test"
        backup_path = output_dir.parent / backup_name
        moved_away = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-moved-away-"))
        moved_away.rmdir()
        real_renameat2 = create_project._renameat2_noreplace

        def swap_backup_before_promotion(src_name, dst_name, dir_fd):
            if src_name.startswith(f".{output_dir.name}.staging-"):
                # the backup has already been isolated and verified; move
                # it away and plant an unrelated non-empty directory at
                # its old name.
                shutil.move(str(backup_path), str(moved_away))
                backup_path.mkdir()
                (backup_path / "unrelated.bin").write_bytes(b"UNRELATED - DO NOT DELETE")
            return real_renameat2(src_name, dst_name, dir_fd)

        with mock.patch("bootstrap.create_project._generate_isolated_name", return_value=backup_name), mock.patch(
            "bootstrap.create_project._renameat2_noreplace", side_effect=swap_backup_before_promotion
        ):
            result = generate(make_params(), output_dir, force=True)

        self.assertTrue(result.ok, result.errors)
        # the unrelated replacement planted at the old backup pathname
        # must survive untouched -- deletion is tied to the verified fd
        self.assertTrue((backup_path / "unrelated.bin").is_file())
        self.assertEqual(b"UNRELATED - DO NOT DELETE", (backup_path / "unrelated.bin").read_bytes())
        # the ORIGINAL (authorized, force=True) content was correctly
        # cleared through the anchored fd wherever it ended up; only the
        # empty shell remains, since the final by-name rmdir targeted the
        # (now attacker-occupied) old name, not this relocated path
        self.assertTrue(moved_away.is_dir())
        self.assertEqual([], list(moved_away.iterdir()))
        shutil.rmtree(moved_away, ignore_errors=True)
        shutil.rmtree(backup_path, ignore_errors=True)

    def test_generate_never_deletes_a_vcs_marker_injected_into_isolated_backup_before_cleanup(self):
        for marker in _VCS_MARKERS:
            with self.subTest(marker=marker):
                output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
                (output_dir / "original.txt").write_text("original content", encoding="utf-8")
                backup_name = f".{output_dir.name}.isolated-fixed-for-test-{marker.lstrip('.')}"
                backup_path = output_dir.parent / backup_name
                real_renameat2 = create_project._renameat2_noreplace

                def inject_marker_before_promotion(src_name, dst_name, dir_fd, marker=marker):
                    if src_name.startswith(f".{output_dir.name}.staging-"):
                        # isolation and the VCS-free authorization check
                        # already happened; plant a protected marker (with
                        # its own data) right before recursive cleanup runs.
                        marker_dir = backup_path / marker
                        marker_dir.mkdir()
                        (marker_dir / "HEAD").write_bytes(b"ref: refs/heads/main\x00")
                    return real_renameat2(src_name, dst_name, dir_fd)

                with mock.patch(
                    "bootstrap.create_project._generate_isolated_name", return_value=backup_name
                ), mock.patch(
                    "bootstrap.create_project._renameat2_noreplace", side_effect=inject_marker_before_promotion
                ):
                    result = generate(make_params(), output_dir, force=True)

                self.assertTrue(result.ok, result.errors)
                self.assertTrue((output_dir / "Sampleheim.sln").is_file())
                # the marker, and its own data, must survive -- cleanup
                # never deletes a protected top-level VCS marker, even one
                # injected after isolation/inspection, even under force=True
                self.assertTrue(backup_path.is_dir())
                self.assertTrue((backup_path / marker).is_dir())
                self.assertEqual(b"ref: refs/heads/main\x00", (backup_path / marker / "HEAD").read_bytes())
                # ordinary content of the force=True-approved directory is
                # still recursively removed as intended
                self.assertFalse((backup_path / "original.txt").exists())
                shutil.rmtree(backup_path, ignore_errors=True)

    def test_generate_reports_recovery_path_when_atomic_restore_primitive_is_unavailable(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        sentinel = output_dir / "sentinel.txt"
        sentinel.write_text("original content", encoding="utf-8")
        real_renameat2 = create_project._renameat2_noreplace
        call_count = {"n": 0}

        def flaky_renameat2(src_name, dst_name, dir_fd):
            if dst_name == output_dir.name:
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise OSError("simulated promotion failure")
                raise _AtomicPromotionUnavailable("simulated: renameat2 missing during restore")
            return real_renameat2(src_name, dst_name, dir_fd)

        with mock.patch("bootstrap.create_project._renameat2_noreplace", side_effect=flaky_renameat2):
            with self.assertRaises(GenerationError) as ctx:
                generate(make_params(), output_dir, force=True)

        backups = list(output_dir.parent.glob(f".{output_dir.name}.isolated-*"))
        self.assertEqual(1, len(backups))
        # the message must name the actual preserved backup, not merely
        # mention the destination path somewhere
        self.assertIn(str(backups[0]), str(ctx.exception))
        self.assertEqual("original content", (backups[0] / "sentinel.txt").read_text(encoding="utf-8"))
        for backup in backups:
            shutil.rmtree(backup, ignore_errors=True)

    def test_generate_fails_closed_when_approved_parent_becomes_a_symlink_before_open(self):
        workspace = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        approved_parent = workspace / "approved-parent"
        approved_parent.mkdir()
        victim = workspace / "victim"
        victim.mkdir()
        (victim / "precious.bin").write_bytes(b"do not touch\x00\x01")
        output_dir = approved_parent / "project"
        real_open = os.open
        triggered = {"done": False}

        def sabotage_open(path, flags, *args, **kwargs):
            if not triggered["done"] and "dir_fd" not in kwargs and str(path) == str(approved_parent):
                triggered["done"] = True
                approved_parent.rmdir()
                approved_parent.symlink_to(victim)
            return real_open(path, flags, *args, **kwargs)

        with mock.patch("bootstrap.create_project.os.open", side_effect=sabotage_open):
            with self.assertRaises(GenerationError):
                generate(make_params(), output_dir, force=False)

        self.assertTrue(triggered["done"])
        self.assertTrue(approved_parent.is_symlink())
        self.assertEqual(victim, Path(os.readlink(approved_parent)))
        self.assertFalse((victim / "project").exists())
        self.assertEqual(b"do not touch\x00\x01", (victim / "precious.bin").read_bytes())

    def test_generate_preserves_content_added_immediately_before_final_rmdir(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        # output_dir exists and is empty; approved with force=False.
        backup_name = f".{output_dir.name}.isolated-fixed-for-test"
        backup_path = output_dir.parent / backup_name
        real_rmdir = os.rmdir

        def inject_immediately_before_rmdir(name, *, dir_fd=None):
            if name == backup_name:
                (backup_path / "last-moment.bin").write_bytes(b"appeared right before rmdir\x00")
            return real_rmdir(name, dir_fd=dir_fd)

        with mock.patch("bootstrap.create_project._generate_isolated_name", return_value=backup_name), mock.patch(
            "bootstrap.create_project.os.rmdir", side_effect=inject_immediately_before_rmdir
        ):
            result = generate(make_params(), output_dir, force=False)

        self.assertTrue(result.ok, result.errors)
        self.assertTrue((output_dir / "Sampleheim.sln").is_file())
        # the rmdir attempt itself is the sole safety check -- content
        # present at the instant it runs is preserved, not deleted
        self.assertTrue(backup_path.is_dir())
        self.assertEqual(b"appeared right before rmdir\x00", (backup_path / "last-moment.bin").read_bytes())
        shutil.rmtree(backup_path, ignore_errors=True)

    def test_generate_reports_recovery_path_at_current_location_after_parent_rename(self):
        workspace = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        original_parent = workspace / "original-parent"
        original_parent.mkdir()
        output_dir = original_parent / "project"
        output_dir.mkdir()
        (output_dir / "sentinel.txt").write_text("original content", encoding="utf-8")
        relocated_parent = workspace / "relocated-parent"
        real_renameat2 = create_project._renameat2_noreplace
        renamed = {"done": False}

        def fail_and_rename_parent(src_name, dst_name, dir_fd):
            if dst_name == "project":
                if not renamed["done"]:
                    original_parent.rename(relocated_parent)
                    renamed["done"] = True
                raise OSError("simulated failure")
            return real_renameat2(src_name, dst_name, dir_fd)

        with mock.patch("bootstrap.create_project._renameat2_noreplace", side_effect=fail_and_rename_parent):
            with self.assertRaises(GenerationError) as ctx:
                generate(make_params(), output_dir, force=True)

        backups = list(relocated_parent.glob(".project.isolated-*"))
        self.assertEqual(1, len(backups))
        self.assertIn(str(backups[0]), str(ctx.exception))
        self.assertNotIn(str(original_parent), str(ctx.exception))
        self.assertEqual("original content", (backups[0] / "sentinel.txt").read_text(encoding="utf-8"))
        shutil.rmtree(backups[0], ignore_errors=True)

    def test_generate_fails_closed_when_isolation_backup_name_collides(self):
        output_dir = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        sentinel = output_dir / "sentinel.txt"
        sentinel.write_text("original content", encoding="utf-8")
        collision_name = f".{output_dir.name}.isolated-collision"
        collision_path = output_dir.parent / collision_name
        collision_path.mkdir()
        (collision_path / "decoy.bin").write_bytes(b"decoy data - do not touch")

        with mock.patch("bootstrap.create_project._generate_isolated_name", return_value=collision_name):
            with self.assertRaises(GenerationError):
                generate(make_params(), output_dir, force=True)

        self.assertTrue(output_dir.is_dir())
        self.assertEqual("original content", (output_dir / "sentinel.txt").read_text(encoding="utf-8"))
        self.assertEqual(b"decoy data - do not touch", (collision_path / "decoy.bin").read_bytes())
        shutil.rmtree(collision_path, ignore_errors=True)

    def test_safe_output_dir_rejects_dot_and_dotdot_final_components(self):
        bootstrapper_root = Path(__file__).resolve().parents[2]
        for bad in (".", "..", str(bootstrapper_root / "template" / "..")):
            with self.subTest(bad=bad):
                with self.assertRaises(GenerationError):
                    _safe_output_dir(bad)

    def test_generate_rejects_dot_and_dotdot_final_components(self):
        workspace = Path(tempfile.mkdtemp(prefix="valheimsuite-bootstrap-fixture-"))
        for bad_candidate in (".", str(workspace / "..")):
            with self.subTest(bad_candidate=bad_candidate):
                with self.assertRaises(GenerationError):
                    generate(make_params(), Path(bad_candidate), force=True)


if __name__ == "__main__":
    unittest.main()
