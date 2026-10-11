"""Password hashes for the users block: SHA-512 crypt made by `openssl passwd` on the machine running Bastet."""

import secrets
import shutil
import subprocess

from bastet.core.errors import BastetError

_ALPHABET = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def new_salt() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(16))


def hash(password: str, salt: str) -> str:
    if "\n" in password or "\r" in password:
        raise BastetError("a password can't contain a line break")
    if shutil.which("openssl") is None:
        raise BastetError("hashing a plain-text password needs openssl on the machine running Bastet; "
                          "install it, or give password_hash instead")
    done = subprocess.run(["openssl", "passwd", "-6", "-salt", salt[:16], "-stdin"], input=password + "\n",
                          capture_output=True, text=True, check=False)
    out = done.stdout.strip()
    if done.returncode != 0 or not out.startswith("$6$"):
        first = (done.stderr.strip().splitlines() or ["no output"])[0]
        raise BastetError(f"openssl could not hash the password: {first}")
    return out


def matches(password: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) != 4 or parts[1] != "6" or not parts[2] or not parts[3] or parts[2].startswith("rounds="):
        return False
    return secrets.compare_digest(hash(password, parts[2]), stored)
