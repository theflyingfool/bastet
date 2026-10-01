import base64
import binascii
import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bastet.core.errors import BastetError, Unreachable

PREFERENCE = (
    "ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
    "rsa-sha2-512", "rsa-sha2-256", "ssh-rsa",
)


@dataclass
class HostKey:
    type: str
    fingerprint: str
    line: str


def parse_keyscan(output: str) -> list[HostKey]:
    keys = []
    for raw in output.splitlines():
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split()
        if len(parts) < 3:
            continue
        _, ktype, blob = parts[:3]
        try:
            data = base64.b64decode(blob, validate=True)
        except (binascii.Error, ValueError):
            continue
        digest = base64.b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
        keys.append(HostKey(ktype, f"SHA256:{digest}", f"{ktype} {blob}"))
    return keys


KEYSCAN_TYPES = {
    "ssh-ed25519": "ed25519",
    "sk-ssh-ed25519@openssh.com": "ed25519-sk",
    "sk-ecdsa-sha2-nistp256@openssh.com": "ecdsa-sk",
    "ssh-rsa": "rsa",
    "rsa-sha2-256": "rsa",
    "rsa-sha2-512": "rsa",
}
ALL_TYPES = "ed25519,ecdsa,rsa"


def _keyscan_type(key_type: str) -> str:
    if key_type.startswith("ecdsa-sha2-"):
        return "ecdsa"
    return KEYSCAN_TYPES.get(key_type, ALL_TYPES)


def _keyscan(address: str, port: int, timeout: int, types: str) -> tuple[list[HostKey], bool]:
    """One ssh-keyscan connection per requested type; also reports whether SSH answered at all."""
    try:
        r = subprocess.run(
            ["ssh-keyscan", "-T", str(timeout), "-p", str(port), "-t", types, address],
            capture_output=True, text=True, timeout=timeout + 10,
        )
    except subprocess.TimeoutExpired:
        return [], False
    answered = any(line.startswith("#") and "SSH-" in line for line in (r.stdout + r.stderr).splitlines())
    keys = parse_keyscan(r.stdout)
    return keys, answered or bool(keys)


def scan(address: str, *, port: int = 22, timeout: int = 10, recorded: str | None = None) -> list[HostKey]:
    """Ask for as few key types as possible: each type is a separate connection that never logs in,
    which intrusion-prevention tools (fail2ban, sshguard) may count against us."""
    if shutil.which("ssh-keyscan") is None:
        raise BastetError("ssh-keyscan not found; install the OpenSSH client")
    if recorded:
        attempts = [_keyscan_type(str(recorded).split()[0]), ALL_TYPES]
    else:
        attempts = ["ed25519", "ecdsa,rsa"]
    for types in dict.fromkeys(attempts):
        keys, answered = _keyscan(address, port, timeout, types)
        if keys:
            return keys
        if not answered:
            raise Unreachable(
                f"{address}: nothing answered on port {port} within {timeout}s "
                "(host down, firewall, or a ban such as fail2ban?)"
            )
    raise Unreachable(f"{address}: SSH answered on port {port} but offered no usable host key")


def preferred(keys: list[HostKey]) -> HostKey:
    def rank(k: HostKey) -> int:
        return PREFERENCE.index(k.type) if k.type in PREFERENCE else len(PREFERENCE)
    return sorted(keys, key=rank)[0]


def record(key: HostKey) -> str:
    return f"{key.type} {key.fingerprint}"


def check(recorded: str | None, keys: list[HostKey]) -> str:
    if not recorded:
        return "new"
    fingerprint = str(recorded).split()[-1]
    return "match" if any(k.fingerprint == fingerprint for k in keys) else "changed"


def pinned(recorded: str, keys: list[HostKey]) -> list[HostKey]:
    """Only the scanned key(s) whose fingerprint equals the recorded one."""
    fingerprint = str(recorded).split()[-1]
    return [k for k in keys if k.fingerprint == fingerprint]


def write_known_hosts(keys: list[HostKey], address: str, port: int, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    host = address if port == 22 else f"[{address}]:{port}"
    path = directory / "known_hosts"
    path.write_text("".join(f"{host} {k.line}\n" for k in keys), encoding="utf-8")
    return path
