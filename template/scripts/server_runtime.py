#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from collections import deque
from pathlib import Path

from dev_config import ConfigError, DevelopmentConfig, load_development_config
from remote_deploy import RemoteDeployError, create_remote_host

ROOT = Path(__file__).resolve().parents[1]


class ServerRuntimeError(RuntimeError):
    pass


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise ServerRuntimeError(f"cannot execute {command[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise ServerRuntimeError(f"server runtime command failed: {detail}")
    return result.stdout.strip()


def _tail_file(raw: object, line_count: int) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ServerRuntimeError("serverLogFile must be a non-empty absolute WSL/Linux path")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ServerRuntimeError("serverLogFile must be an absolute WSL/Linux path")
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return "".join(deque(handle, maxlen=line_count)).strip()
    except OSError as exc:
        raise ServerRuntimeError(f"cannot read server log file {path}: {exc}") from exc


def _legacy_action(development: DevelopmentConfig, action: str, tail: int) -> str:
    raw = development.raw
    if action == "logs" and raw.get("serverLogFile") is not None:
        return _tail_file(raw.get("serverLogFile"), tail)
    compose = raw.get("dockerComposeFile")
    service = raw.get("dockerService")
    if not isinstance(compose, str) or not compose.strip() or not isinstance(service, str) or not service.strip():
        raise ServerRuntimeError(
            "schema-v1 server runtime requires serverLogFile for logs or both dockerComposeFile and dockerService"
        )
    args = ["docker", "compose", "-f", compose]
    args.extend(["logs", "--tail", str(tail), service] if action == "logs" else ["ps", service])
    return _run(args)


def _docker_action(development: DevelopmentConfig, action: str, tail: int) -> str:
    lifecycle = development.server_lifecycle
    if lifecycle.type != "docker" or lifecycle.container is None:
        raise ServerRuntimeError("server runtime action requires a Docker lifecycle")
    deployment = development.server_deployment
    if deployment.type == "local":
        if action == "logs":
            return _run(["docker", "logs", "--tail", str(tail), lifecycle.container])
        status_format = "{" * 2 + ".State.Status" + "}" * 2
        return _run(["docker", "inspect", "--format", status_format, lifecycle.container])
    if deployment.type == "ssh":
        host, _platform = create_remote_host(deployment)
        return host.docker_logs(lifecycle.container, tail) if action == "logs" else host.docker_status(lifecycle.container)
    raise ServerRuntimeError(f"unsupported deployment type: {deployment.type}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "logs"))
    parser.add_argument("--tail", type=int, default=250)
    args = parser.parse_args()
    if not 10 <= args.tail <= 2000:
        parser.error("--tail must be between 10 and 2000")

    try:
        development = load_development_config(ROOT / ".valheim" / "dev.json")
        if development.raw["schemaVersion"] == 1:
            output = _legacy_action(development, args.action, args.tail)
        elif args.action == "logs" and development.raw.get("serverLogFile") is not None:
            output = _tail_file(development.raw.get("serverLogFile"), args.tail)
        else:
            output = _docker_action(development, args.action, args.tail)
        if output:
            print(output)
        return 0
    except (ConfigError, RemoteDeployError, ServerRuntimeError) as exc:
        print(f"server runtime error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
