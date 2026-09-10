from __future__ import annotations

import importlib.util
import sys
import unittest
import uuid
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[2] / "template" / "scripts"


def load_dev_config_module():
    name = f"dev_config_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / "dev_config.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


class DevelopmentConfigSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_dev_config_module()

    def test_direct_import_does_not_contaminate_the_template(self) -> None:
        self.assertFalse((SCRIPTS / "__pycache__").exists())

    def test_v1_server_plugin_dir_maps_to_local_deployment(self) -> None:
        parsed = self.module.parse_development_config(
            {"schemaVersion": 1, "developmentOnly": True, "serverPluginDir": "/srv/plugins/Sampleheim"}
        )
        self.assertEqual("local", parsed.server_deployment.type)
        self.assertEqual("/srv/plugins/Sampleheim", parsed.server_deployment.plugin_dir)
        self.assertEqual("none", parsed.server_lifecycle.type)

    def test_v2_local_deployment_and_none_lifecycle(self) -> None:
        parsed = self.module.parse_development_config(
            {
                "schemaVersion": 2,
                "developmentOnly": True,
                "server": {
                    "deployment": {"type": "local", "pluginDir": "/srv/plugins/Sampleheim"},
                    "lifecycle": {"type": "none"},
                },
            }
        )
        self.assertEqual("local", parsed.server_deployment.type)
        self.assertEqual("none", parsed.server_lifecycle.type)

    def test_v2_ssh_deployment_parses_overrides(self) -> None:
        parsed = self.module.parse_development_config(
            {
                "schemaVersion": 2,
                "developmentOnly": True,
                "server": {
                    "deployment": {
                        "type": "ssh",
                        "host": "game-server",
                        "remotePlatform": "windows",
                        "pluginDir": "H:/server/BepInEx/plugins/Sampleheim",
                        "sshExecutable": "/opt/openssh/bin/ssh",
                        "scpExecutable": "/opt/openssh/bin/scp",
                    },
                    "lifecycle": {"type": "docker", "container": "valheim-server"},
                },
            }
        )
        self.assertEqual("ssh", parsed.server_deployment.type)
        self.assertEqual("windows", parsed.server_deployment.remote_platform)
        self.assertEqual("/opt/openssh/bin/ssh", parsed.server_deployment.ssh_executable)
        self.assertEqual("/opt/openssh/bin/scp", parsed.server_deployment.scp_executable)
        self.assertEqual("docker", parsed.server_lifecycle.type)
        self.assertEqual("valheim-server", parsed.server_lifecycle.container)

    def test_ssh_defaults_use_path_and_auto_detection(self) -> None:
        parsed = self.module.parse_development_config(
            {
                "schemaVersion": 2,
                "developmentOnly": True,
                "server": {
                    "deployment": {
                        "type": "ssh",
                        "host": "game-server",
                        "pluginDir": "/srv/plugins/Sampleheim",
                    },
                    "lifecycle": {"type": "none"},
                },
            }
        )
        self.assertEqual("auto", parsed.server_deployment.remote_platform)
        self.assertEqual("ssh", parsed.server_deployment.ssh_executable)
        self.assertEqual("scp", parsed.server_deployment.scp_executable)

    def test_invalid_deployment_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(self.module.ConfigError, "deployment.type must be local or ssh"):
            self.module.parse_development_config(
                {
                    "schemaVersion": 2,
                    "developmentOnly": True,
                    "server": {
                        "deployment": {"type": "smb", "pluginDir": "/srv/plugins/Sampleheim"},
                        "lifecycle": {"type": "none"},
                    },
                }
            )

    def test_invalid_lifecycle_type_is_rejected(self) -> None:
        with self.assertRaisesRegex(self.module.ConfigError, "lifecycle.type must be none or docker"):
            self.module.parse_development_config(
                {
                    "schemaVersion": 2,
                    "developmentOnly": True,
                    "server": {
                        "deployment": {"type": "local", "pluginDir": "/srv/plugins/Sampleheim"},
                        "lifecycle": {"type": "compose", "container": "valheim"},
                    },
                }
            )

    def test_credential_fields_are_rejected(self) -> None:
        for field in ("password", "privateKey", "privateKeyContents"):
            with self.subTest(field=field), self.assertRaisesRegex(self.module.ConfigError, "unsupported field"):
                self.module.parse_development_config(
                    {
                        "schemaVersion": 2,
                        "developmentOnly": True,
                        "server": {
                            "deployment": {
                                "type": "ssh",
                                "host": "game-server",
                                "pluginDir": "/srv/plugins/Sampleheim",
                                field: "secret",
                            },
                            "lifecycle": {"type": "none"},
                        },
                    }
                )

    def test_schema_v1_rejects_credential_material(self) -> None:
        for field in ("password", "privateKey", "privateKeyContents", "identityFile", "authToken"):
            with self.subTest(field=field), self.assertRaisesRegex(self.module.ConfigError, "credential"):
                self.module.parse_development_config(
                    {
                        "schemaVersion": 1,
                        "developmentOnly": True,
                        "serverPluginDir": "/srv/plugins/Sampleheim",
                        field: "secret",
                    }
                )


    def test_ssh_host_rejects_inline_user_port_and_options(self) -> None:
        for host in ("user@server", "server:2222", "-oProxyJump=other"):
            with self.subTest(host=host), self.assertRaisesRegex(self.module.ConfigError, "SSH config alias"):
                self.module.parse_development_config(
                    {
                        "schemaVersion": 2,
                        "developmentOnly": True,
                        "server": {
                            "deployment": {"type": "ssh", "host": host, "pluginDir": "/srv/plugins/Sampleheim"},
                            "lifecycle": {"type": "none"},
                        },
                    }
                )


if __name__ == "__main__":
    unittest.main()
