from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


_HOST_ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_CONTAINER_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_V2_FIELDS = {
    "schemaVersion",
    "developmentOnly",
    "valheimInstall",
    "clientPluginDir",
    "server",
    "serverLogFile",
    "solution",
    "configuration",
}


@dataclass(frozen=True)
class ServerDeployment:
    type: str
    plugin_dir: str | None
    host: str | None = None
    remote_platform: str = "auto"
    ssh_executable: str = "ssh"
    scp_executable: str = "scp"


@dataclass(frozen=True)
class ServerLifecycle:
    type: str
    container: str | None = None


@dataclass(frozen=True)
class DevelopmentConfig:
    raw: dict
    server_deployment: ServerDeployment
    server_lifecycle: ServerLifecycle


def _object(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be a JSON object")
    return value


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value


def _optional_executable(value: object, field: str, default: str) -> str:
    if value is None:
        return default
    return _required_string(value, field)


def _reject_unknown(value: dict, allowed: set[str], field: str) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ConfigError(f"{field} contains unsupported field(s): {', '.join(unexpected)}")


def _reject_credential_fields(value: dict) -> None:
    credential_fields = []
    for field in value:
        normalized = field.replace("-", "").replace("_", "").casefold()
        if (
            "password" in normalized
            or "privatekey" in normalized
            or normalized.endswith("token")
            or normalized in {"identityfile", "sshkey", "keymaterial"}
        ):
            credential_fields.append(field)
    if credential_fields:
        raise ConfigError(
            f".valheim/dev.json contains prohibited credential field(s): {', '.join(sorted(credential_fields))}; "
            "keep SSH authentication material in SSH configuration"
        )


def parse_development_config(payload: dict) -> DevelopmentConfig:
    version = payload.get("schemaVersion")
    if type(version) is not int or version not in {1, 2}:
        raise ConfigError("schemaVersion must be the JSON integer 1 or 2")
    if payload.get("developmentOnly") is not True:
        raise ConfigError("developmentOnly must be true before deployment")
    _reject_credential_fields(payload)
    configuration = payload.get("configuration", "Debug")
    if configuration not in {"Debug", "Release"}:
        raise ConfigError("configuration must be Debug or Release")

    if version == 1:
        plugin_dir = payload.get("serverPluginDir")
        if plugin_dir is not None:
            plugin_dir = _required_string(plugin_dir, "serverPluginDir")
        return DevelopmentConfig(
            raw=payload,
            server_deployment=ServerDeployment(type="local", plugin_dir=plugin_dir),
            server_lifecycle=ServerLifecycle(type="none"),
        )

    _reject_unknown(payload, _V2_FIELDS, ".valheim/dev.json")
    server = _object(payload.get("server"), "server")
    _reject_unknown(server, {"deployment", "lifecycle"}, "server")

    deployment = _object(server.get("deployment"), "server.deployment")
    deployment_type = deployment.get("type")
    if deployment_type == "local":
        _reject_unknown(deployment, {"type", "pluginDir"}, "server.deployment")
        parsed_deployment = ServerDeployment(
            type="local",
            plugin_dir=_required_string(deployment.get("pluginDir"), "server.deployment.pluginDir"),
        )
    elif deployment_type == "ssh":
        _reject_unknown(
            deployment,
            {"type", "host", "pluginDir", "remotePlatform", "sshExecutable", "scpExecutable"},
            "server.deployment",
        )
        host = _required_string(deployment.get("host"), "server.deployment.host")
        if not _HOST_ALIAS.fullmatch(host):
            raise ConfigError("server.deployment.host must be an SSH config alias without whitespace, user, port, or options")
        remote_platform = deployment.get("remotePlatform", "auto")
        if remote_platform not in {"auto", "windows", "posix"}:
            raise ConfigError("server.deployment.remotePlatform must be auto, windows, or posix")
        parsed_deployment = ServerDeployment(
            type="ssh",
            host=host,
            plugin_dir=_required_string(deployment.get("pluginDir"), "server.deployment.pluginDir"),
            remote_platform=remote_platform,
            ssh_executable=_optional_executable(
                deployment.get("sshExecutable"), "server.deployment.sshExecutable", "ssh"
            ),
            scp_executable=_optional_executable(
                deployment.get("scpExecutable"), "server.deployment.scpExecutable", "scp"
            ),
        )
    else:
        raise ConfigError("server.deployment.type must be local or ssh")

    lifecycle = _object(server.get("lifecycle"), "server.lifecycle")
    lifecycle_type = lifecycle.get("type")
    if lifecycle_type == "none":
        _reject_unknown(lifecycle, {"type"}, "server.lifecycle")
        parsed_lifecycle = ServerLifecycle(type="none")
    elif lifecycle_type == "docker":
        _reject_unknown(lifecycle, {"type", "container"}, "server.lifecycle")
        container = _required_string(lifecycle.get("container"), "server.lifecycle.container")
        if not _CONTAINER_NAME.fullmatch(container):
            raise ConfigError("server.lifecycle.container must be a Docker container name")
        parsed_lifecycle = ServerLifecycle(type="docker", container=container)
    else:
        raise ConfigError("server.lifecycle.type must be none or docker")

    return DevelopmentConfig(raw=payload, server_deployment=parsed_deployment, server_lifecycle=parsed_lifecycle)


def load_development_config(path: Path) -> DevelopmentConfig:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return parse_development_config(payload)
