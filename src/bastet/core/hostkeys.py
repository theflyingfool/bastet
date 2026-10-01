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


def scan(address: str, *, port: int = 22, timeout: int = 10) -> list[HostKey]:
    if shutil.which("ssh-keyscan") is None:
        raise BastetError("ssh-keyscan not found; install the OpenSSH client")
    try:
        r = subprocess.run(
            ["ssh-keyscan", "-T", str(timeout), "-p", str(port), address],
            capture_output=True, text=True, timeout=timeout + 10,
        )
    except subprocess.TimeoutExpired:
        raise Unreachable(f"{address}: no answer on port {port}") from None
    keys = parse_keyscan(r.stdout)
    if not keys:
        raise Unreachable(f"{address}: no SSH host keys on port {port} (host down, or SSH not running?)")
    return keys


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


def write_known_hosts(keys: list[HostKey], address: str, port: int, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    host = address if port == 22 else f"[{address}]:{port}"
    path = directory / "known_hosts"
    path.write_text("".join(f"{host} {k.line}\n" for k in keys), encoding="utf-8")
    return path
