"""Sealing and opening secret values: a JSON payload (path, value, next) as armored age text."""

import json
from dataclasses import dataclass
from pathlib import Path

import pyrage
import pyrage.ssh
import pyrage.x25519

from bastet.core.errors import BastetError


class SecretError(BastetError):
    """A secret couldn't be sealed, opened or found."""


@dataclass
class Sealed:
    value: str
    next: str | None


def recipient(line: str):
    """Parse an `ssh-ed25519 …` or `age1…` line into a pyrage recipient."""
    line = line.strip()
    try:
        if line.startswith("age1"):
            return pyrage.x25519.Recipient.from_str(line)
        return pyrage.ssh.Recipient.from_str(line)
    except pyrage.RecipientError:
        raise SecretError(f"{line!r} isn't an SSH or age public key") from None


def identity(path: Path):
    """Read an SSH private key, or an `AGE-SECRET-KEY-…` file, into a pyrage identity."""
    data = path.read_bytes()
    try:
        return pyrage.ssh.Identity.from_buffer(data)
    except pyrage.IdentityError:
        pass
    for line in data.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("AGE-SECRET-KEY-"):
            try:
                return pyrage.x25519.Identity.from_str(line)
            except pyrage.IdentityError:
                break
    raise SecretError(
        f"{path}: isn't an SSH or age private key "
        "(passphrase-protected keys aren't supported; Bastet's own key decrypts)"
    )


def seal(path: str, value: str, recipients: list[str], *, next_value: str | None = None) -> str:
    payload: dict[str, str] = {"path": path, "value": value}
    if next_value is not None:
        payload["next"] = next_value
    recips = [recipient(line) for line in recipients]
    armored = pyrage.encrypt(json.dumps(payload).encode(), recips, armored=True)
    return armored.decode("ascii")


def open_sealed(armored: str, path: str, identities) -> Sealed:
    try:
        plaintext = pyrage.decrypt(armored.encode("ascii"), identities)
    except pyrage.DecryptError:
        raise SecretError(f"{path}: can't decrypt (not a recipient?)") from None
    try:
        payload = json.loads(plaintext)
        value = payload["value"]
    except (json.JSONDecodeError, KeyError, TypeError):
        raise SecretError(f"{path}: can't decrypt (not sealed by Bastet?)") from None
    if payload.get("path") != path:
        raise SecretError(f"{path}: sealed for {payload.get('path')}")
    return Sealed(value=value, next=payload.get("next"))
