from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures._helpers import NO_BYTECODE_ENV, clone_generated_temp, import_deploy_from, write_fake_artifacts


_FAKE_SSH = r'''#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

script = sys.stdin.read()
if "actual_entries=" in script:
    operation = "promote"
elif "mkdir -- \"$stage\"" in script:
    operation = "prepare"
elif "VALHEIMSUITE_MANIFEST" in script:
    operation = "manifest"
elif "exec docker restart" in script:
    operation = "restart"
else:
    operation = "cleanup-or-detect"
with Path(os.environ["FAKE_SSH_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(operation + "\n")
command = sys.argv[2:]
if command and command[0].lower().startswith("powershell"):
    sys.stderr.write("PowerShell unavailable in POSIX fake\n")
    raise SystemExit(127)
result = subprocess.run(command, input=script, text=True)
raise SystemExit(result.returncode)
'''

_FAKE_SCP = r'''#!/usr/bin/env python3
import os
import shutil
import sys
from pathlib import Path

with Path(os.environ["FAKE_SSH_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write("upload\n")
mode = os.environ.get("FAKE_SCP_MODE", "ok")
if mode == "fail":
    sys.stderr.write("simulated upload failure\n")
    raise SystemExit(9)
args = sys.argv[1:]
if args and args[0] == "-s":
    args = args[1:]
if args and args[0] == "--":
    args = args[1:]
sources, target = args[:-1], args[-1]
_destination_host, destination = target.split(":", 1)
dest = Path(destination)
for source in sources:
    shutil.copy2(source, dest / Path(source).name)
if mode == "extra":
    (dest / "unexpected.dll").write_bytes(b"unexpected")
elif mode == "corrupt":
    (dest / Path(sources[0]).name).write_bytes(b"corrupt")
'''

_FAKE_MV = r'''#!/usr/bin/env python3
import os
import sys
from pathlib import Path

fail_at = os.environ.get("FAKE_MV_FAIL_AT")
if fail_at is not None:
    counter = Path(os.environ["FAKE_MV_COUNT"])
    count = int(counter.read_text(encoding="utf-8") or "0") + 1
    counter.write_text(str(count), encoding="utf-8")
    if count == int(fail_at):
        sys.stderr.write("simulated move failure\n")
        raise SystemExit(17)
os.execv(os.environ["REAL_MV"], ["mv", *sys.argv[1:]])
'''


_FAKE_DOCKER = r'''#!/usr/bin/env python3
import os
import sys
from pathlib import Path

with Path(os.environ["FAKE_DOCKER_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\n")
print(sys.argv[-1])
'''


class RemoteDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _, cls.output_dir, result = clone_generated_temp()
        if not result.ok:
            raise AssertionError(result.errors)
        cls.cfg = json.loads((cls.output_dir / "suite.config.json").read_text(encoding="utf-8"))
        write_fake_artifacts(cls.output_dir, cls.cfg)
        cls.server_modules = [cls.cfg["packages"]["commonModule"], *cls.cfg["packages"]["serverModules"]]
        cls.manifest_name = f".{cls.cfg['suiteName']}.deploy-manifest.json"
        cls.fake_bin = Path(tempfile.mkdtemp(prefix="valheimsuite-fake-ssh-bin-"))
        for name, content in (
            ("ssh override", _FAKE_SSH),
            ("scp override", _FAKE_SCP),
            ("docker", _FAKE_DOCKER),
            ("mv", _FAKE_MV),
        ):
            path = cls.fake_bin / name
            path.write_text(content, encoding="utf-8")
            path.chmod(0o755)
        cls.ssh = cls.fake_bin / "ssh override"
        cls.scp = cls.fake_bin / "scp override"
        cls.real_mv = shutil.which("mv")
        if cls.real_mv is None:
            raise AssertionError("mv is required")

    def setUp(self) -> None:
        self.ssh_log = Path(tempfile.mkstemp(prefix="valheimsuite-ssh-log-")[1])
        self.docker_log = Path(tempfile.mkstemp(prefix="valheimsuite-docker-log-")[1])

    def _destination(self, leaf: str = "Sampleheim") -> Path:
        root = Path(tempfile.mkdtemp(prefix="valheimsuite-remote-root-"))
        parent = root / "BepInEx" / "plugins"
        parent.mkdir(parents=True)
        return parent / leaf

    def _write_v2(self, destination: Path, *, deployment: str = "ssh", lifecycle: str = "none") -> None:
        if deployment == "ssh":
            deployment_config = {
                "type": "ssh",
                "host": "game-server",
                "remotePlatform": "posix",
                "pluginDir": str(destination),
                "sshExecutable": str(self.ssh),
                "scpExecutable": str(self.scp),
            }
        else:
            deployment_config = {"type": "local", "pluginDir": str(destination)}
        lifecycle_config = (
            {"type": "docker", "container": "valheim-server"}
            if lifecycle == "docker"
            else {"type": "none"}
        )
        payload = {
            "schemaVersion": 2,
            "developmentOnly": True,
            "server": {"deployment": deployment_config, "lifecycle": lifecycle_config},
        }
        path = self.output_dir / ".valheim" / "dev.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _run(
        self,
        *extra: str,
        mode: str = "ok",
        wrapper: bool = False,
        path: str | None = None,
        mv_fail_at: int | None = None,
    ) -> subprocess.CompletedProcess:
        env = dict(NO_BYTECODE_ENV)
        env.update(
            {
                "PATH": path or f"{self.fake_bin}:{os.environ.get('PATH', '')}",
                "FAKE_SSH_LOG": str(self.ssh_log),
                "FAKE_DOCKER_LOG": str(self.docker_log),
                "FAKE_SCP_MODE": mode,
                "REAL_MV": self.real_mv,
            }
        )
        if mv_fail_at is not None:
            env["FAKE_MV_FAIL_AT"] = str(mv_fail_at)
            env["FAKE_MV_COUNT"] = tempfile.mkstemp(prefix="valheimsuite-mv-count-")[1]
        command = (
            ["bash", "scripts/deploy-server.sh", "Debug", *extra]
            if wrapper
            else ["python3", "scripts/deploy.py", "--target", "server", "--configuration", "Debug", *extra]
        )
        return subprocess.run(
            command,
            cwd=self.output_dir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def test_local_and_ssh_deploy_same_server_artifacts(self) -> None:
        local_destination = self._destination()
        self._write_v2(local_destination, deployment="local")
        local_result = self._run()
        self.assertEqual(local_result.returncode, 0, local_result.stderr)

        remote_destination = self._destination()
        self._write_v2(remote_destination)
        remote_result = self._run()
        self.assertEqual(remote_result.returncode, 0, remote_result.stderr)

        expected = sorted(f"{module}.dll" for module in self.server_modules)
        local_files = json.loads(
            (local_destination / self.manifest_name).read_text(encoding="utf-8")
        )["files"]
        remote_files = json.loads(
            (remote_destination / self.manifest_name).read_text(encoding="utf-8")
        )["files"]
        self.assertEqual(local_files, expected)
        self.assertEqual(remote_files, expected)

    def test_v2_local_deployment_uses_hardened_local_backend(self) -> None:
        destination = self._destination()
        self._write_v2(destination, deployment="local")
        result = self._run()
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual(
            {*(f"{module}.dll" for module in self.server_modules), self.manifest_name},
            {item.name for item in destination.iterdir()},
        )
        self.assertEqual("", self.ssh_log.read_text(encoding="utf-8"))

    def test_posix_remote_stages_then_promotes_exact_artifacts(self) -> None:
        destination = self._destination()
        self._write_v2(destination)
        result = self._run()
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual(
            {*(f"{module}.dll" for module in self.server_modules), self.manifest_name},
            {item.name for item in destination.iterdir()},
        )
        operations = self.ssh_log.read_text(encoding="utf-8").splitlines()
        self.assertLess(operations.index("prepare"), operations.index("upload"))
        self.assertLess(operations.index("upload"), operations.index("promote"))

    def test_failed_upload_leaves_live_deployment_unchanged(self) -> None:
        destination = self._destination()
        self._write_v2(destination)
        first = self._run()
        self.assertEqual(0, first.returncode, first.stdout)
        before = {item.name: item.read_bytes() for item in destination.iterdir()}
        result = self._run(mode="fail")
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("remote upload failed", result.stdout)
        self.assertEqual(before, {item.name: item.read_bytes() for item in destination.iterdir()})

    def test_prepare_collision_does_not_delete_preexisting_remote_directory(self) -> None:
        destination = self._destination()
        deploy = import_deploy_from(self.output_dir / "scripts")
        remote = sys.modules["remote_deploy"]
        deployment = sys.modules["dev_config"].ServerDeployment(
            type="ssh",
            plugin_dir=str(destination),
            host="game-server",
            remote_platform="posix",
            ssh_executable=str(self.ssh),
            scp_executable=str(self.scp),
        )
        stage = destination.parent / f".valheimsuite.deploy-{'a' * 32}"
        stage.mkdir()
        sentinel = stage / "unrelated"
        sentinel.write_bytes(b"keep")
        plan = deploy.build_deployment_plan(self.cfg, "server", "Debug")
        fixed_uuid = mock.Mock(hex="a" * 32)
        with mock.patch.object(remote.uuid, "uuid4", return_value=fixed_uuid):
            with mock.patch.dict(os.environ, {"FAKE_SSH_LOG": str(self.ssh_log)}):
                with self.assertRaises(remote.RemoteDeployError):
                    remote.deploy_ssh(
                        deployment,
                        [source for _module, source in plan.artifacts],
                        plan.manifest_filename,
                        plan.manifest_payload,
                    )
        self.assertEqual(b"keep", sentinel.read_bytes())

    def test_failed_staging_verification_leaves_live_deployment_unchanged(self) -> None:
        destination = self._destination()
        self._write_v2(destination)
        first = self._run()
        self.assertEqual(0, first.returncode, first.stdout)
        before = {item.name: item.read_bytes() for item in destination.iterdir()}
        result = self._run(mode="extra")
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("does not contain exactly the expected files", result.stdout)
        self.assertEqual(before, {item.name: item.read_bytes() for item in destination.iterdir()})

    def test_hash_mismatch_leaves_live_deployment_unchanged(self) -> None:
        destination = self._destination()
        self._write_v2(destination)
        first = self._run()
        self.assertEqual(0, first.returncode, first.stdout)
        before = {item.name: item.read_bytes() for item in destination.iterdir()}
        result = self._run(mode="corrupt")
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("staged file hash mismatch", result.stdout)
        self.assertEqual(before, {item.name: item.read_bytes() for item in destination.iterdir()})

    def test_backup_move_failure_restores_every_original_live_entry(self) -> None:
        destination = self._destination()
        self._write_v2(destination)
        first = self._run()
        self.assertEqual(0, first.returncode, first.stdout)
        before = {item.name: item.read_bytes() for item in destination.iterdir()}
        result = self._run(mv_fail_at=2)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("simulated move failure", result.stdout)
        self.assertEqual(before, {item.name: item.read_bytes() for item in destination.iterdir()})

    def test_remote_cleanup_removes_only_stale_owned_files(self) -> None:
        destination = self._destination()
        destination.mkdir()
        stale = destination / "Old.Server.dll"
        unrelated = destination / "OtherSuite.dll"
        stale.write_bytes(b"old")
        unrelated.write_bytes(b"other")
        (destination / self.manifest_name).write_text(
            json.dumps({"version": 1, "files": [stale.name]}) + "\n", encoding="utf-8"
        )
        self._write_v2(destination)
        result = self._run()
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertFalse(stale.exists())
        self.assertEqual(b"other", unrelated.read_bytes())
        self.assertIn("Old.Server.dll", result.stdout)

    def test_raw_remote_plugin_root_is_rejected_before_ssh(self) -> None:
        destination = self._destination().parent
        self._write_v2(destination)
        result = self._run()
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("shared remote BepInEx/plugins", result.stdout)
        self.assertEqual("", self.ssh_log.read_text(encoding="utf-8"))

    def test_hostile_looking_posix_path_is_literal(self) -> None:
        marker = self.output_dir / "SHOULD_NOT_EXIST"
        destination = self._destination("Sampleheim $(touch SHOULD_NOT_EXIST) ; spaces")
        self._write_v2(destination)
        result = self._run()
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertTrue(destination.is_dir())
        self.assertFalse(marker.exists())

    def test_posix_backend_does_not_require_gnu_realpath_find_or_sha256sum(self) -> None:
        destination = self._destination("Sampleheim ' quoted")
        self._write_v2(destination)
        portable_bin = Path(tempfile.mkdtemp(prefix="valheimsuite-portable-posix-bin-"))
        for command in (
            "base64", "cut", "dotnet", "mkdir", "mv", "python3",
            "rm", "rmdir", "sh", "shasum", "sort", "tr",
        ):
            executable = shutil.which(command)
            self.assertIsNotNone(executable, command)
            os.symlink(executable, portable_bin / command)
        result = self._run(path=str(portable_bin))
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertTrue(destination.is_dir())

    def test_no_restart_occurs_without_explicit_flag(self) -> None:
        destination = self._destination()
        self._write_v2(destination, lifecycle="docker")
        result = self._run()
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual("", self.docker_log.read_text(encoding="utf-8"))

    def test_explicit_restart_uses_remote_docker_context(self) -> None:
        destination = self._destination()
        self._write_v2(destination, lifecycle="docker")
        result = self._run("--restart")
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual("restart valheim-server\n", self.docker_log.read_text(encoding="utf-8"))
        self.assertIn("restarted Docker container: valheim-server", result.stdout)

    def test_server_wrapper_forwards_explicit_restart(self) -> None:
        destination = self._destination()
        self._write_v2(destination, deployment="local", lifecycle="docker")
        result = self._run("--restart", wrapper=True)
        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual("restart valheim-server\n", self.docker_log.read_text(encoding="utf-8"))

    def test_none_lifecycle_reports_post_deployment_restart_failure(self) -> None:
        destination = self._destination()
        self._write_v2(destination, deployment="local", lifecycle="none")
        result = self._run("--restart")
        self.assertEqual(3, result.returncode, result.stdout)
        self.assertIn("lifecycle error (deployment succeeded)", result.stdout)
        self.assertTrue((destination / f"{self.server_modules[0]}.dll").is_file())

    def test_windows_paths_and_commands_remain_literal(self) -> None:
        import_deploy_from(self.output_dir / "scripts")
        remote = sys.modules["remote_deploy"]
        self.assertEqual(
            "H:/server path/$(hostile)/BepInEx/plugins/Sampleheim",
            remote.validate_remote_destination(
                "H:/server path/$(hostile)/BepInEx/plugins/Sampleheim", "windows"
            ),
        )

        class CapturingTransport:
            def __init__(self):
                self.calls = []

            def _invoke(self, platform, script, check=True):
                self.calls.append((platform, script, check))
                return subprocess.CompletedProcess([], 0, "", "")

        transport = CapturingTransport()
        host = remote.WindowsRemoteHost(
            transport,
            "H:/server path/$(hostile)/BepInEx/plugins/Sampleheim",
            ".Sampleheim.deploy-abc123",
            ".Sampleheim.backup-abc123",
        )
        host.prepare()
        platform, script, _check = transport.calls[0]
        self.assertEqual("windows", platform)
        self.assertNotIn("$(hostile)", script)
        self.assertIn("FromBase64String", script)
        self.assertIn("-LiteralPath", script)
        self.assertNotIn("Split-Path -LiteralPath", script)

    def test_maximum_valid_suite_destination_uses_portable_staging_component(self) -> None:
        import_deploy_from(self.output_dir / "scripts")
        remote = sys.modules["remote_deploy"]
        deployment = sys.modules["dev_config"].ServerDeployment(
            type="ssh",
            plugin_dir=str(self._destination("S" * 233)),
            host="game-server",
            remote_platform="posix",
            ssh_executable=str(self.ssh),
            scp_executable=str(self.scp),
        )
        host, _platform = remote.create_remote_host(deployment)
        with mock.patch.dict(os.environ, {"FAKE_SSH_LOG": str(self.ssh_log)}):
            try:
                host.prepare()
                self.assertTrue(Path(host.stage).is_dir())
            finally:
                host.cleanup()

    def test_windows_transport_reads_complete_script_before_execution(self) -> None:
        import_deploy_from(self.output_dir / "scripts")
        remote = sys.modules["remote_deploy"]
        deployment = sys.modules["dev_config"].ServerDeployment(
            type="ssh",
            plugin_dir="H:/server/BepInEx/plugins/Sampleheim",
            host="game-server",
        )
        completed = subprocess.CompletedProcess([], 0, "done\n", "")
        with mock.patch.object(remote.subprocess, "run", return_value=completed) as run:
            result = remote.SSHTransport(deployment)._invoke(
                "windows", "if ($true) { Write-Output 'complete script' }\n"
            )
        self.assertEqual("done\n", result.stdout)
        argv = run.call_args.args[0]
        self.assertIn("-EncodedCommand", argv)
        self.assertNotIn("-Command", argv)
        runner = base64.b64decode(argv[-1]).decode("utf-16le")
        self.assertIn("[Console]::In.ReadToEnd()", runner)
        self.assertIn("[ScriptBlock]::Create", runner)
        self.assertEqual(
            "if ($true) { Write-Output 'complete script' }\n",
            run.call_args.kwargs["input"],
        )

    def test_scp_upload_forces_sftp_instead_of_remote_shell_parsing(self) -> None:
        import_deploy_from(self.output_dir / "scripts")
        remote = sys.modules["remote_deploy"]
        deployment = sys.modules["dev_config"].ServerDeployment(
            type="ssh",
            plugin_dir="/srv/BepInEx/plugins/Sampleheim",
            host="game-server",
        )
        completed = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(remote.subprocess, "run", return_value=completed) as run:
            remote.SSHTransport(deployment).upload([Path("/tmp/Sampleheim.dll")], "/srv/stage with 'quotes")
        self.assertEqual(
            ["scp", "-s", "--", "/tmp/Sampleheim.dll", "game-server:/srv/stage with 'quotes/"],
            run.call_args.args[0],
        )

    def test_remote_destination_rejects_roots_and_raw_plugin_directories(self) -> None:
        import_deploy_from(self.output_dir / "scripts")
        remote = sys.modules["remote_deploy"]
        for path, platform in (("/", "posix"), ("H:/", "windows"), ("/srv/BepInEx/plugins", "posix")):
            with self.subTest(path=path), self.assertRaises(remote.RemoteDeployError):
                remote.validate_remote_destination(path, platform)

    def test_windows_destination_rejects_non_drive_and_ambiguous_components(self) -> None:
        import_deploy_from(self.output_dir / "scripts")
        remote = sys.modules["remote_deploy"]
        for path in (
            "H:/server/BepInEx/plugins.",
            "H:/server/BepInEx/plugins ",
            "H:/server/BepInEx/plugins/Suite::$DATA",
            r"\\server\share\BepInEx\plugins\Suite",
            r"\\?\H:\server\BepInEx\plugins\Suite",
        ):
            with self.subTest(path=path), self.assertRaises(remote.RemoteDeployError):
                remote.validate_remote_destination(path, "windows")


if __name__ == "__main__":
    unittest.main()
