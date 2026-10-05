import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bastet.core.errors import AuthFailed, BastetError, Unreachable


@dataclass
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


class LocalRunner:
    name = "local"

    def run(self, script: str, *, timeout: int = 120) -> CommandResult:
        try:
            r = subprocess.run(["sh", "-s"], input=script, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise BastetError(f"local commands timed out after {timeout}s") from None
        return CommandResult(r.stdout, r.stderr, r.returncode)


@dataclass
class SshTarget:
    address: str
    user: str
    key: Path | None
    known_hosts: Path | None
    port: int = 22
    control_path: Path | None = None


def ssh_args(target: SshTarget, *, interactive: bool = False) -> list[str]:
    args = ["ssh", "-p", str(target.port), "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15"]
    args += ["-o", "ServerAliveCountMax=3"]
    if target.control_path is not None:
        args += ["-o", "ControlMaster=auto", "-o", f"ControlPath={target.control_path}", "-o", "ControlPersist=60s"]
    args += ["-t"] if interactive else ["-o", "BatchMode=yes"]
    if target.key is not None:
        args += ["-i", str(target.key), "-o", "IdentitiesOnly=yes"]
    if target.known_hosts is not None:
        args += [
            "-o", f"UserKnownHostsFile={target.known_hosts}",
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "StrictHostKeyChecking=yes",
        ]
    args.append(f"{target.user}@{target.address}")
    return args


def control_path() -> Path:
    """Where multiplexed connections live: one socket per host (%C), in a private per-user directory."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime_dir) / "bastet" if runtime_dir else Path.home() / ".cache" / "bastet" / "ssh"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    return base / "%C"


def close_master(target: SshTarget) -> None:
    """Close a multiplexed connection at the end of a run; failures don't matter."""
    if target.control_path is None:
        return
    args = ssh_args(target)
    try:
        subprocess.run([*args[:-1], "-O", "exit", args[-1]], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        pass


class SshRunner:
    def __init__(self, target: SshTarget) -> None:
        self.target = target

    @property
    def name(self) -> str:
        return f"{self.target.user}@{self.target.address}"

    def run(self, script: str, *, timeout: int = 120) -> CommandResult:
        try:
            r = subprocess.run(
                [*ssh_args(self.target), "sh", "-s"], input=script, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            raise Unreachable(f"{self.name}: timed out after {timeout}s") from None
        if r.returncode == 255:
            err = r.stderr.strip()
            last = err.splitlines()[-1] if err else "ssh failed"
            if "Permission denied" in err or "Too many authentication failures" in err:
                raise AuthFailed(f"{self.name}: login refused")
            if "Host key verification failed" in err or "IDENTIFICATION HAS CHANGED" in err:
                raise BastetError(f"{self.name}: host key verification failed")
            raise Unreachable(f"{self.name}: {last}")
        return CommandResult(r.stdout, r.stderr, r.returncode)


def run_interactive(target: SshTarget, command: str) -> int:
    return subprocess.run([*ssh_args(target, interactive=True), command]).returncode
