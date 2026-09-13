from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.fixtures._helpers import NO_BYTECODE_ENV, clone_generated_temp


_FAKE_DOCKER = r'''#!/usr/bin/env python3
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["FAKE_DOCKER_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(" ".join(args) + "\n")
if args[0] == "inspect":
    print("running")
elif args[0] == "logs":
    print("server log line")
elif args[0] == "compose" and "ps" in args:
    print("legacy running")
else:
    print("legacy log line")
'''

_FAKE_SSH = r'''#!/usr/bin/env python3
import subprocess
import sys

result = subprocess.run(sys.argv[2:], input=sys.stdin.read(), text=True)
raise SystemExit(result.returncode)
'''


class ServerRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _params, cls.output_dir, result = clone_generated_temp()
        if not result.ok:
            raise AssertionError(result.errors)
        cls.fake_bin = Path(tempfile.mkdtemp(prefix="valheimsuite-runtime-bin-"))
        for name, content in (("docker", _FAKE_DOCKER), ("ssh override", _FAKE_SSH)):
            path = cls.fake_bin / name
            path.write_text(content, encoding="utf-8")
            path.chmod(0o755)

    def setUp(self) -> None:
        self.docker_log = Path(tempfile.mkstemp(prefix="valheimsuite-runtime-log-")[1])

    def _write_config(self, deployment: dict) -> None:
        config = {
            "schemaVersion": 2,
            "developmentOnly": True,
            "server": {
                "deployment": deployment,
                "lifecycle": {"type": "docker", "container": "valheim-server"},
            },
        }
        (self.output_dir / ".valheim" / "dev.json").write_text(json.dumps(config), encoding="utf-8")

    def _run(self, action: str) -> subprocess.CompletedProcess[str]:
        env = dict(NO_BYTECODE_ENV)
        env.update(
            {
                "PATH": f"{self.fake_bin}:{os.environ.get('PATH', '')}",
                "FAKE_DOCKER_LOG": str(self.docker_log),
            }
        )
        return subprocess.run(
            ["python3", "scripts/server_runtime.py", action, "--tail", "10"],
            cwd=self.output_dir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def test_local_status_and_logs_use_fixed_docker_actions(self) -> None:
        self._write_config({"type": "local", "pluginDir": "/srv/plugins/Sampleheim"})
        status = self._run("status")
        logs = self._run("logs")
        self.assertEqual((0, "running"), (status.returncode, status.stdout.strip()))
        self.assertEqual((0, "server log line"), (logs.returncode, logs.stdout.strip()))
        self.assertEqual(
            [
                "inspect --format {{.State.Status}} valheim-server",
                "logs --tail 10 valheim-server",
            ],
            self.docker_log.read_text(encoding="utf-8").splitlines(),
        )

    def test_ssh_status_and_logs_execute_beside_remote_container(self) -> None:
        self._write_config(
            {
                "type": "ssh",
                "host": "game-server",
                "remotePlatform": "posix",
                "pluginDir": "/srv/BepInEx/plugins/Sampleheim",
                "sshExecutable": str(self.fake_bin / "ssh override"),
            }
        )
        status = self._run("status")
        logs = self._run("logs")
        self.assertEqual((0, "running"), (status.returncode, status.stdout.strip()))
        self.assertEqual((0, "server log line"), (logs.returncode, logs.stdout.strip()))
        self.assertEqual(
            [
                "inspect --format {{.State.Status}} valheim-server",
                "logs --tail 10 valheim-server",
            ],
            self.docker_log.read_text(encoding="utf-8").splitlines(),
        )

    def test_schema_v1_compose_status_and_logs_remain_compatible(self) -> None:
        config = {
            "schemaVersion": 1,
            "developmentOnly": True,
            "dockerComposeFile": "/srv/docker-compose.yml",
            "dockerService": "valheim",
        }
        (self.output_dir / ".valheim" / "dev.json").write_text(json.dumps(config), encoding="utf-8")
        status = self._run("status")
        logs = self._run("logs")
        self.assertEqual((0, "legacy running"), (status.returncode, status.stdout.strip()))
        self.assertEqual((0, "legacy log line"), (logs.returncode, logs.stdout.strip()))
        self.assertEqual(
            [
                "compose -f /srv/docker-compose.yml ps valheim",
                "compose -f /srv/docker-compose.yml logs --tail 10 valheim",
            ],
            self.docker_log.read_text(encoding="utf-8").splitlines(),
        )


if __name__ == "__main__":
    unittest.main()
