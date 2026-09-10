from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Sequence

from dev_config import ServerDeployment
import suite_metadata as metadata


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



class RemoteDeployError(RuntimeError):
    pass


def _posix_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _reject_control_characters(value: str, field: str) -> None:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise RemoteDeployError(f"{field} must not contain control characters")


def validate_remote_destination(raw: str, platform: str) -> str:
    _reject_control_characters(raw, "remote deployment destination")
    if platform == "posix":
        path = PurePosixPath(raw)
        if not path.is_absolute() or ".." in path.parts:
            raise RemoteDeployError(f"remote POSIX deployment destination must be an absolute normalized path: {raw}")
        normalized = path.as_posix()
        if normalized == "/":
            raise RemoteDeployError("refusing remote filesystem root as deployment destination")
        parts = path.parts
    elif platform == "windows":
        if not re.match(r"^[A-Za-z]:[/\\]", raw):
            raise RemoteDeployError(f"remote Windows deployment destination must be an absolute drive path: {raw}")
        path = PureWindowsPath(raw)
        if not path.is_absolute() or ".." in path.parts:
            raise RemoteDeployError(f"remote Windows deployment destination must be an absolute drive path: {raw}")
        normalized = path.as_posix()
        if len(path.parts) == 1:
            raise RemoteDeployError("refusing remote drive root as deployment destination")
        for component in path.parts[1:]:
            if component.endswith((" ", ".")) or any(char in '<>:"|?*' for char in component):
                raise RemoteDeployError(
                    f"remote Windows deployment destination contains an ambiguous or invalid component: {raw}"
                )
        parts = path.parts
    else:
        raise RemoteDeployError(f"unsupported remote platform: {platform}")

    if len(parts) >= 2 and parts[-1].lower() == "plugins" and parts[-2].lower() == "bepinex":
        raise RemoteDeployError(
            "refusing to deploy directly into the shared remote BepInEx/plugins directory; "
            "configure a suite-specific subdirectory instead"
        )
    return normalized

_WINDOWS_STDIN_RUNNER = base64.b64encode(
    (
        "$source = [Console]::In.ReadToEnd()\n"
        "try { & ([ScriptBlock]::Create($source)) }\n"
        "catch { [Console]::Error.WriteLine(($_ | Out-String)); exit 1 }\n"
    ).encode("utf-16le")
).decode("ascii")



class SSHTransport:
    def __init__(self, deployment: ServerDeployment):
        if deployment.host is None:
            raise RemoteDeployError("SSH deployment requires a host")
        self.host = deployment.host
        self.ssh_executable = deployment.ssh_executable
        self.scp_executable = deployment.scp_executable

    def _invoke(self, platform: str, script: str, *, check: bool = True) -> subprocess.CompletedProcess:
        command = (
            ["sh", "-s"]
            if platform == "posix"
            else ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", _WINDOWS_STDIN_RUNNER]
        )
        try:
            result = subprocess.run(
                [self.ssh_executable, self.host, *command],
                input=script,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise RemoteDeployError(f"cannot execute {self.ssh_executable}: {exc}") from exc
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise RemoteDeployError(f"remote {platform} operation failed: {detail}")
        return result

    def detect_platform(self) -> str:
        windows = self._invoke(
            "windows",
            "if ($env:OS -ne 'Windows_NT') { exit 1 }; Write-Output 'VALHEIMSUITE_PLATFORM_WINDOWS'\n",
            check=False,
        )
        if windows.returncode == 0 and "VALHEIMSUITE_PLATFORM_WINDOWS" in windows.stdout:
            return "windows"
        posix = self._invoke(
            "posix",
            "case \"$(uname -s)\" in Linux*|Darwin*|*BSD*) printf '%s\\n' VALHEIMSUITE_PLATFORM_POSIX ;; *) exit 1 ;; esac\n",
            check=False,
        )
        if posix.returncode == 0 and "VALHEIMSUITE_PLATFORM_POSIX" in posix.stdout:
            return "posix"
        details = "; ".join(
            item for item in (windows.stderr.strip(), posix.stderr.strip()) if item
        )
        raise RemoteDeployError(f"cannot detect remote platform{': ' + details if details else ''}; configure remotePlatform")

    def upload(self, sources: Sequence[Path], remote_directory: str) -> None:
        remote_directory = remote_directory.rstrip("/\\")
        target = f"{self.host}:{remote_directory}/"
        try:
            result = subprocess.run(
                [self.scp_executable, "-s", "--", *(str(source) for source in sources), target],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            raise RemoteDeployError(f"cannot execute {self.scp_executable}: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise RemoteDeployError(f"remote upload failed: {detail}")


_POSIX_SAFETY = r'''
fail() { printf '%s\n' "$1" >&2; exit 1; }
assert_safe_destination() {
    case "$destination" in /*) ;; *) fail "destination is not absolute" ;; esac
    [ "$destination" != "/" ] || fail "refusing filesystem root"
    [ "$destination" != "$HOME" ] || fail "refusing remote home directory"
    parent=${destination%/*}
    base=${destination##*/}
    [ -n "$parent" ] && [ -n "$base" ] || fail "destination has no suite component"
    parent_real=$(CDPATH= cd -P "$parent" 2>/dev/null && pwd -P) || fail "destination parent does not exist"
    [ "$parent_real" = "$parent" ] || fail "destination parent contains a symlink or non-canonical component"
    lower_base=$(printf '%s' "$base" | tr '[:upper:]' '[:lower:]')
    lower_parent=$(printf '%s' "${parent##*/}" | tr '[:upper:]' '[:lower:]')
    if [ "$lower_base" = plugins ] && [ "$lower_parent" = bepinex ]; then
        fail "refusing shared BepInEx/plugins destination"
    fi
    [ ! -L "$destination" ] || fail "destination is a symlink"
    if [ -e "$destination" ] && [ ! -d "$destination" ]; then
        fail "destination is not a directory"
    fi
}
sha256_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum -- "$1" | cut -d ' ' -f 1
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | cut -d ' ' -f 1
    else
        fail "remote POSIX host has neither sha256sum nor shasum"
    fi
}
'''


def _posix_variables(values: dict[str, str]) -> str:
    return "\n".join(f"{name}={_posix_quote(value)}" for name, value in values.items())


class PosixRemoteHost:
    def __init__(self, transport: SSHTransport, destination: str, stage_name: str, backup_name: str):
        self.transport = transport
        self.destination = destination
        self.parent = PurePosixPath(destination).parent.as_posix()
        self.stage_name = stage_name
        self.backup_name = backup_name
        self.stage = f"{self.parent}/{stage_name}"

    def prepare(self) -> None:
        variables = _posix_variables({"destination": self.destination, "stage_name": self.stage_name})
        script = f"""set -eu
{variables}
{_POSIX_SAFETY}
assert_safe_destination
stage="$parent/$stage_name"
case "$stage_name" in .*.deploy-[0-9a-f]*) ;; *) fail "unsafe staging name" ;; esac
[ ! -e "$stage" ] && [ ! -L "$stage" ] || fail "staging path already exists"
mkdir -- "$stage"
"""
        self.transport._invoke("posix", script)

    def read_manifest(self, manifest: str) -> bytes | None:
        variables = _posix_variables({"destination": self.destination, "manifest_name": manifest})
        script = f"""set -eu
{variables}
{_POSIX_SAFETY}
assert_safe_destination
manifest="$destination/$manifest_name"
if [ ! -e "$manifest" ] && [ ! -L "$manifest" ]; then
    printf '%s\\n' VALHEIMSUITE_MANIFEST_ABSENT
    exit 0
fi
[ -f "$manifest" ] && [ ! -L "$manifest" ] || fail "deployment manifest is not a regular file"
printf 'VALHEIMSUITE_MANIFEST:'
base64 < "$manifest" | tr -d '\\n'
printf '\\n'
"""
        output = self.transport._invoke("posix", script).stdout
        return _parse_manifest_output(output)

    def promote(
        self,
        manifest: str,
        expected_manifest: bytes,
        hashes: dict[str, str],
        previous_manifest: bytes | None,
        stale: set[str],
    ) -> None:
        expected_entries = sorted([*hashes, manifest])
        desired = sorted(hashes)
        affected = sorted(set(desired) | stale | {manifest})
        variables = _posix_variables(
            {
                "destination": self.destination,
                "stage_name": self.stage_name,
                "backup_name": self.backup_name,
                "manifest_name": manifest,
                "expected_entries": "\n".join(expected_entries),
                "hash_lines": "\n".join(f"{name}|{hashes[name]}" for name in desired),
                "desired_entries": "\n".join([*desired, manifest]),
                "affected_entries": "\n".join(affected),
                "previous_manifest": "" if previous_manifest is None else base64.b64encode(previous_manifest).decode("ascii"),
                "previous_state": "absent" if previous_manifest is None else "present",
                "expected_manifest_hash": hashlib.sha256(expected_manifest).hexdigest(),
            }
        )
        open_brace = "{"
        close_brace = "}"
        script = f"""set -eu
{variables}
{_POSIX_SAFETY}
assert_safe_destination
stage="$parent/$stage_name"
backup="$parent/$backup_name"
case "$stage_name" in .*.deploy-[0-9a-f]*) ;; *) fail "unsafe staging name" ;; esac
case "$backup_name" in .*.backup-[0-9a-f]*) ;; *) fail "unsafe backup name" ;; esac
[ -d "$stage" ] && [ ! -L "$stage" ] || fail "staging directory is missing or unsafe"
[ ! -e "$backup" ] && [ ! -L "$backup" ] || fail "backup path already exists"
actual_entries=$(
    for entry in "$stage"/* "$stage"/.[!.]* "$stage"/..?*; do
        if [ -e "$entry" ] || [ -L "$entry" ]; then
            printf '%s\n' "${open_brace}entry##*/{close_brace}"
        fi
    done | LC_ALL=C sort
)
[ "$actual_entries" = "$expected_entries" ] || fail "staged deployment does not contain exactly the expected files"
printf '%s\\n' "$hash_lines" | while IFS='|' read -r name expected_hash; do
    [ -n "$name" ] || continue
    file="$stage/$name"
    [ -f "$file" ] && [ ! -L "$file" ] || fail "staged entry is not a regular file: $name"
    actual_hash=$(sha256_file "$file")
    [ "$actual_hash" = "$expected_hash" ] || fail "staged file hash mismatch: $name"
done
staged_manifest="$stage/$manifest_name"
[ -f "$staged_manifest" ] && [ ! -L "$staged_manifest" ] || fail "staged manifest is not a regular file"
[ "$(sha256_file "$staged_manifest")" = "$expected_manifest_hash" ] || fail "staged manifest hash mismatch"
current_manifest="$destination/$manifest_name"
if [ "$previous_state" = absent ]; then
    [ ! -e "$current_manifest" ] && [ ! -L "$current_manifest" ] || fail "live manifest changed during deployment"
else
    [ -f "$current_manifest" ] && [ ! -L "$current_manifest" ] || fail "live manifest changed during deployment"
    current_encoded=$(base64 < "$current_manifest" | tr -d '\\n')
    [ "$current_encoded" = "$previous_manifest" ] || fail "live manifest changed during deployment"
fi
if [ ! -e "$destination" ]; then
    mkdir -- "$destination"
    live_created=1
else
    live_created=0
fi
printf '%s\\n' "$affected_entries" | while IFS= read -r name; do
    [ -n "$name" ] || continue
    entry="$destination/$name"
    if [ -e "$entry" ] || [ -L "$entry" ]; then
        if [ ! -f "$entry" ] && [ ! -L "$entry" ]; then
            fail "refusing non-regular owned destination entry: $name"
        fi
    fi
done
mkdir -- "$backup"
success=0
rollback() {open_brace}
    [ "$success" -eq 0 ] || return 0
    set +e
    printf '%s\\n' "$desired_entries" | while IFS= read -r name; do
        [ -n "$name" ] || continue
        staged="$stage/$name"
        entry="$destination/$name"
        if [ ! -e "$staged" ] && [ ! -L "$staged" ]; then
            if [ -f "$entry" ] || [ -L "$entry" ]; then rm -f -- "$entry"; fi
        fi
    done
    printf '%s\\n' "$affected_entries" | while IFS= read -r name; do
        [ -n "$name" ] || continue
        if [ -e "$backup/$name" ] || [ -L "$backup/$name" ]; then mv -- "$backup/$name" "$destination/$name"; fi
    done
    rmdir -- "$backup" 2>/dev/null || true
    if [ "$live_created" -eq 1 ]; then rmdir -- "$destination" 2>/dev/null || true; fi
{close_brace}
trap rollback EXIT HUP INT TERM
printf '%s\\n' "$affected_entries" | while IFS= read -r name; do
    [ -n "$name" ] || continue
    if [ -e "$destination/$name" ] || [ -L "$destination/$name" ]; then
        mv -- "$destination/$name" "$backup/$name"
    fi
done
printf '%s\\n' "$desired_entries" | while IFS= read -r name; do
    [ -n "$name" ] || continue
    mv -- "$stage/$name" "$destination/$name"
done
success=1
trap - EXIT HUP INT TERM
rm -rf -- "$stage"
rm -rf -- "$backup"
"""
        self.transport._invoke("posix", script)

    def cleanup(self) -> None:
        variables = _posix_variables({"destination": self.destination, "stage_name": self.stage_name})
        script = f"""set -eu
{variables}
{_POSIX_SAFETY}
assert_safe_destination
stage="$parent/$stage_name"
case "$stage_name" in .*.deploy-[0-9a-f]*) ;; *) fail "unsafe staging name" ;; esac
if [ -L "$stage" ]; then fail "refusing symlinked staging cleanup"; fi
if [ -e "$stage" ]; then [ -d "$stage" ] || fail "staging cleanup target is not a directory"; rm -rf -- "$stage"; fi
"""
        self.transport._invoke("posix", script)

    def restart_docker(self, container: str) -> str:
        variables = _posix_variables({"container": container})
        script = f"""set -eu
{variables}
exec docker restart "$container"
"""
        return self.transport._invoke("posix", script).stdout.strip()

    def docker_status(self, container: str) -> str:
        status_format = "{" * 2 + ".State.Status" + "}" * 2
        variables = _posix_variables({"container": container, "status_format": status_format})
        script = f"""set -eu
{variables}
exec docker inspect --format "$status_format" "$container"
"""
        return self.transport._invoke("posix", script).stdout.strip()

    def docker_logs(self, container: str, line_count: int) -> str:
        variables = _posix_variables({"container": container, "line_count": str(line_count)})
        script = f"""set -eu
{variables}
exec docker logs --tail "$line_count" "$container"
"""
        return self.transport._invoke("posix", script).stdout.strip()



_WINDOWS_SAFETY = r'''
$ErrorActionPreference = 'Stop'
function Fail([string]$Message) { throw $Message }
function Assert-SafeDestination([string]$Destination) {
    if ($Destination -notmatch '^[A-Za-z]:[/\\]') { Fail 'destination is not an absolute drive path' }
    $full = [System.IO.Path]::GetFullPath($Destination)
    $root = [System.IO.Path]::GetPathRoot($full)
    if ($full.TrimEnd('\') -eq $root.TrimEnd('\')) { Fail 'refusing drive root' }
    if (-not [string]::IsNullOrWhiteSpace($HOME)) {
        $homeFull = [IO.Path]::GetFullPath($HOME)
        if ($full.TrimEnd('\') -ieq $homeFull.TrimEnd('\')) { Fail 'refusing remote home directory' }
    }
    $parent = [IO.Path]::GetDirectoryName($full)
    $base = [IO.Path]::GetFileName($full)
    $parentBase = [IO.Path]::GetFileName($parent)
    if ($base -ieq 'plugins' -and $parentBase -ieq 'BepInEx') {
        Fail 'refusing shared BepInEx/plugins destination'
    }
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { Fail 'destination parent does not exist' }
    $cursor = Get-Item -LiteralPath $parent -Force
    while ($null -ne $cursor) {
        if (($cursor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            Fail "destination parent contains a reparse point: $($cursor.FullName)"
        }
        $cursor = $cursor.Parent
    }
    if (Test-Path -LiteralPath $full) {
        $item = Get-Item -LiteralPath $full -Force
        if (-not $item.PSIsContainer -or (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            Fail 'destination is not a plain directory'
        }
        if ($item.Name -ieq 'plugins' -and $item.Parent.Name -ieq 'BepInEx') {
            Fail 'refusing shared BepInEx/plugins destination'
        }
    }
    return $full
}
'''


def _powershell_payload(payload: dict) -> str:
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    return (
        "$payload = ConvertFrom-Json "
        f"([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')))\n"
    )


class WindowsRemoteHost:
    def __init__(self, transport: SSHTransport, destination: str, stage_name: str, backup_name: str):
        self.transport = transport
        self.destination = destination
        self.parent = PureWindowsPath(destination).parent.as_posix()
        self.stage_name = stage_name
        self.backup_name = backup_name
        self.stage = f"{self.parent}/{stage_name}"

    def prepare(self) -> None:
        script = _powershell_payload({"destination": self.destination, "stageName": self.stage_name}) + _WINDOWS_SAFETY + r'''
$destination = Assert-SafeDestination $payload.destination
if ($payload.stageName -notmatch '^\..+\.deploy-[0-9a-f]+$') { Fail 'unsafe staging name' }
$stage = Join-Path ([IO.Path]::GetDirectoryName($destination)) $payload.stageName
if (Test-Path -LiteralPath $stage) { Fail 'staging path already exists' }
$null = [IO.Directory]::CreateDirectory($stage)
'''
        self.transport._invoke("windows", script)

    def read_manifest(self, manifest: str) -> bytes | None:
        script = _powershell_payload({"destination": self.destination, "manifest": manifest}) + _WINDOWS_SAFETY + r'''
$destination = Assert-SafeDestination $payload.destination
$manifest = Join-Path $destination $payload.manifest
if (-not (Test-Path -LiteralPath $manifest)) {
    Write-Output 'VALHEIMSUITE_MANIFEST_ABSENT'
    exit 0
}
$item = Get-Item -LiteralPath $manifest -Force
if ($item.PSIsContainer -or (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
    Fail 'deployment manifest is not a plain file'
}
Write-Output ('VALHEIMSUITE_MANIFEST:' + [Convert]::ToBase64String([IO.File]::ReadAllBytes($manifest)))
'''
        output = self.transport._invoke("windows", script).stdout
        return _parse_manifest_output(output)

    def promote(
        self,
        manifest: str,
        expected_manifest: bytes,
        hashes: dict[str, str],
        previous_manifest: bytes | None,
        stale: set[str],
    ) -> None:
        desired = sorted(hashes)
        affected = sorted(set(desired) | stale | {manifest})
        payload = {
            "destination": self.destination,
            "stageName": self.stage_name,
            "backupName": self.backup_name,
            "manifest": manifest,
            "expectedEntries": sorted([*desired, manifest]),
            "hashes": hashes,
            "desiredEntries": [*desired, manifest],
            "affectedEntries": affected,
            "previousManifest": None if previous_manifest is None else base64.b64encode(previous_manifest).decode("ascii"),
            "expectedManifestHash": hashlib.sha256(expected_manifest).hexdigest(),
        }
        script = _powershell_payload(payload) + _WINDOWS_SAFETY + r'''
$destination = Assert-SafeDestination $payload.destination
$parent = [IO.Path]::GetDirectoryName($destination)
if ($payload.stageName -notmatch '^\..+\.deploy-[0-9a-f]+$') { Fail 'unsafe staging name' }
if ($payload.backupName -notmatch '^\..+\.backup-[0-9a-f]+$') { Fail 'unsafe backup name' }
$stage = Join-Path $parent $payload.stageName
$backup = Join-Path $parent $payload.backupName
if (-not (Test-Path -LiteralPath $stage -PathType Container)) { Fail 'staging directory is missing' }
$stageItem = Get-Item -LiteralPath $stage -Force
if (($stageItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { Fail 'staging directory is a reparse point' }
if (Test-Path -LiteralPath $backup) { Fail 'backup path already exists' }
$actual = @((Get-ChildItem -LiteralPath $stage -Force | Sort-Object Name | ForEach-Object Name))
$expected = @($payload.expectedEntries | Sort-Object)
if ([string]::Join("`n", $actual) -cne [string]::Join("`n", $expected)) {
    Fail 'staged deployment does not contain exactly the expected files'
}
foreach ($property in $payload.hashes.PSObject.Properties) {
    $file = Join-Path $stage $property.Name
    $item = Get-Item -LiteralPath $file -Force
    if ($item.PSIsContainer -or (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        Fail "staged entry is not a plain file: $($property.Name)"
    }
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -cne $property.Value.ToUpperInvariant()) {
        Fail "staged file hash mismatch: $($property.Name)"
    }
}
$stagedManifest = Join-Path $stage $payload.manifest
$stagedManifestItem = Get-Item -LiteralPath $stagedManifest -Force
if ($stagedManifestItem.PSIsContainer -or (($stagedManifestItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
    Fail 'staged manifest is not a plain file'
}
if ((Get-FileHash -LiteralPath $stagedManifest -Algorithm SHA256).Hash -cne $payload.expectedManifestHash.ToUpperInvariant()) {
    Fail 'staged manifest hash mismatch'
}
$currentManifest = Join-Path $destination $payload.manifest
if ($null -eq $payload.previousManifest) {
    if (Test-Path -LiteralPath $currentManifest) { Fail 'live manifest changed during deployment' }
} else {
    if (-not (Test-Path -LiteralPath $currentManifest -PathType Leaf)) { Fail 'live manifest changed during deployment' }
    $currentItem = Get-Item -LiteralPath $currentManifest -Force
    if (($currentItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { Fail 'live manifest changed during deployment' }
    $currentEncoded = [Convert]::ToBase64String([IO.File]::ReadAllBytes($currentManifest))
    if ($currentEncoded -cne $payload.previousManifest) { Fail 'live manifest changed during deployment' }
}
$liveCreated = $false
if (-not (Test-Path -LiteralPath $destination)) {
    $null = [IO.Directory]::CreateDirectory($destination)
    $liveCreated = $true
}
foreach ($name in $payload.affectedEntries) {
    $entry = Join-Path $destination $name
    if (Test-Path -LiteralPath $entry) {
        $item = Get-Item -LiteralPath $entry -Force
        if ($item.PSIsContainer -or (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
            Fail "refusing non-regular or reparse-point owned destination entry: $name"
        }
    }
}
$null = [IO.Directory]::CreateDirectory($backup)
try {
    foreach ($name in $payload.affectedEntries) {
        $entry = Join-Path $destination $name
        if (Test-Path -LiteralPath $entry) { Move-Item -LiteralPath $entry -Destination (Join-Path $backup $name) }
    }
    foreach ($name in $payload.desiredEntries) {
        Move-Item -LiteralPath (Join-Path $stage $name) -Destination (Join-Path $destination $name)
    }
} catch {
    $original = $_
    $rollbackErrors = [Collections.Generic.List[string]]::new()
    foreach ($name in $payload.desiredEntries) {
        $staged = Join-Path $stage $name
        if (-not (Test-Path -LiteralPath $staged)) {
            $entry = Join-Path $destination $name
            if (Test-Path -LiteralPath $entry) {
                try {
                    $item = Get-Item -LiteralPath $entry -Force
                    if ($item.PSIsContainer -or (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
                        throw "rollback target became unsafe: $name"
                    }
                    Remove-Item -LiteralPath $entry -Force
                } catch { $rollbackErrors.Add($_.Exception.Message) }
            }
        }
    }
    foreach ($name in $payload.affectedEntries) {
        $saved = Join-Path $backup $name
        if (Test-Path -LiteralPath $saved) {
            try { Move-Item -LiteralPath $saved -Destination (Join-Path $destination $name) }
            catch { $rollbackErrors.Add($_.Exception.Message) }
        }
    }
    try { Remove-Item -LiteralPath $backup -Force }
    catch { $rollbackErrors.Add($_.Exception.Message) }
    if ($liveCreated) {
        try { Remove-Item -LiteralPath $destination -Force }
        catch { $rollbackErrors.Add($_.Exception.Message) }
    }
    if ($rollbackErrors.Count -gt 0) {
        throw "$($original.Exception.Message); rollback also failed: $([string]::Join('; ', $rollbackErrors))"
    }
    throw $original
}
Remove-Item -LiteralPath $stage -Force
Remove-Item -LiteralPath $backup -Recurse -Force
'''
        self.transport._invoke("windows", script)

    def cleanup(self) -> None:
        script = _powershell_payload({"destination": self.destination, "stageName": self.stage_name}) + _WINDOWS_SAFETY + r'''
$destination = Assert-SafeDestination $payload.destination
if ($payload.stageName -notmatch '^\..+\.deploy-[0-9a-f]+$') { Fail 'unsafe staging name' }
$stage = Join-Path ([IO.Path]::GetDirectoryName($destination)) $payload.stageName
if (Test-Path -LiteralPath $stage) {
    $item = Get-Item -LiteralPath $stage -Force
    if (-not $item.PSIsContainer -or (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) {
        Fail 'refusing unsafe staging cleanup target'
    }
    Remove-Item -LiteralPath $stage -Recurse -Force
}
'''
        self.transport._invoke("windows", script)

    def restart_docker(self, container: str) -> str:
        script = _powershell_payload({"container": container}) + r'''
$ErrorActionPreference = 'Stop'
& docker restart $payload.container
if ($LASTEXITCODE -ne 0) { throw "docker restart failed with exit code $LASTEXITCODE" }
'''
        return self.transport._invoke("windows", script).stdout.strip()

    def docker_status(self, container: str) -> str:
        status_format = "{" * 2 + ".State.Status" + "}" * 2
        script = _powershell_payload({"container": container, "statusFormat": status_format}) + r'''
$ErrorActionPreference = 'Stop'
& docker inspect --format $payload.statusFormat $payload.container
if ($LASTEXITCODE -ne 0) { throw "docker inspect failed with exit code $LASTEXITCODE" }
'''
        return self.transport._invoke("windows", script).stdout.strip()

    def docker_logs(self, container: str, line_count: int) -> str:
        script = _powershell_payload({"container": container, "lineCount": line_count}) + r'''
$ErrorActionPreference = 'Stop'
& docker logs --tail $payload.lineCount $payload.container
if ($LASTEXITCODE -ne 0) { throw "docker logs failed with exit code $LASTEXITCODE" }
'''
        return self.transport._invoke("windows", script).stdout.strip()



def _parse_manifest_output(output: str) -> bytes | None:
    for line in reversed(output.splitlines()):
        if line == "VALHEIMSUITE_MANIFEST_ABSENT":
            return None
        if line.startswith("VALHEIMSUITE_MANIFEST:"):
            try:
                return base64.b64decode(line.partition(":")[2], validate=True)
            except ValueError as exc:
                raise RemoteDeployError("remote host returned an invalid manifest payload") from exc
    raise RemoteDeployError("remote host did not return a deployment manifest status")


def create_remote_host(deployment: ServerDeployment):
    transport = SSHTransport(deployment)
    platform = deployment.remote_platform
    if platform == "auto":
        platform = transport.detect_platform()
    destination = validate_remote_destination(deployment.plugin_dir or "", platform)
    suffix = uuid.uuid4().hex
    stage_name = f".valheimsuite.deploy-{suffix}"
    backup_name = f".valheimsuite.backup-{suffix}"
    host = (
        PosixRemoteHost(transport, destination, stage_name, backup_name)
        if platform == "posix"
        else WindowsRemoteHost(transport, destination, stage_name, backup_name)
    )
    return host, platform


def deploy_ssh(
    deployment: ServerDeployment,
    artifacts: Sequence[Path],
    manifest_name: str,
    manifest_payload: bytes,
) -> tuple[object, str, set[str]]:
    host, platform = create_remote_host(deployment)
    host.prepare()
    try:
        previous_payload = host.read_manifest(manifest_name)
        previous_owned: set[str] = set()
        if previous_payload is not None:
            try:
                parsed = json.loads(previous_payload)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RemoteDeployError(f"remote deployment manifest {manifest_name} is not valid JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise RemoteDeployError(f"remote deployment manifest {manifest_name} must contain a JSON object")
            if type(parsed.get("version")) is not int or parsed.get("version") != 1:
                raise RemoteDeployError(f"remote deployment manifest {manifest_name} has an unsupported or missing version")
            files = parsed.get("files")
            if not isinstance(files, list) or not all(isinstance(item, str) for item in files) or len(set(files)) != len(files):
                raise RemoteDeployError(f"remote deployment manifest {manifest_name} has an invalid files list")
            try:
                for item in files:
                    metadata.validate_path_component(item, "remote deployment manifest entry")
            except metadata.MetadataError as exc:
                raise RemoteDeployError(f"remote deployment manifest {manifest_name} contains an unsafe filename: {exc}") from exc
            previous_owned = set(files)
        desired = {artifact.name for artifact in artifacts}
        stale = previous_owned - desired
        hashes = {artifact.name: _sha256_file(artifact) for artifact in artifacts}
        with tempfile.TemporaryDirectory(prefix="valheimsuite-remote-manifest-") as temp_dir:
            manifest_file = Path(temp_dir) / manifest_name
            manifest_file.write_bytes(manifest_payload)
            host.transport.upload([*artifacts, manifest_file], host.stage)
        host.promote(manifest_name, manifest_payload, hashes, previous_payload, stale)
        return host, platform, stale
    except BaseException as exc:
        try:
            host.cleanup()
        except RemoteDeployError as cleanup_error:
            raise RemoteDeployError(f"{exc}; additionally, staging cleanup failed: {cleanup_error}") from exc
        raise
