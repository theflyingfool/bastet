"""Password hashes for the users block, made by the system crypt library (libcrypt) on the machine running Bastet."""

import ctypes
import ctypes.util
import functools
import os
import re
import secrets

from bastet.core.errors import BastetError

_PREFIX = {"yescrypt": "$y$", "sha512": "$6$", "sha256": "$5$"}
_METHOD = {"YESCRYPT": "yescrypt", "SHA512": "sha512", "SHA256": "sha256"}
_ALPHABET = "./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_MISSING = ("hashing a plain-text password needs libcrypt (libxcrypt) on the machine running Bastet; "
            "install it, or give password_hash instead")


def _load():
    lib = ctypes.CDLL(ctypes.util.find_library("crypt") or "libcrypt.so.1")
    lib.crypt_r.restype = ctypes.c_char_p
    lib.crypt_r.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p]
    try:
        lib.crypt_gensalt_rn.restype = ctypes.c_char_p
        lib.crypt_gensalt_rn.argtypes = [ctypes.c_char_p, ctypes.c_ulong, ctypes.c_char_p, ctypes.c_int,
                                         ctypes.c_char_p, ctypes.c_int]
    except AttributeError:
        pass
    return lib


@functools.lru_cache(maxsize=1)  # loaded once per process; a failure is not cached, so the next call tries again
def _library():
    try:
        return _load()
    except OSError as e:
        raise BastetError(_MISSING) from e


def _crypt(lib, password: str, setting: str) -> str | None:
    data = ctypes.create_string_buffer(1 << 18)  # 256 KiB covers glibc's and libxcrypt's crypt_data; one per call: crypt_r is thread-safe with its own data
    out = lib.crypt_r(password.encode("utf-8"), setting.encode("utf-8"), data)
    text = out.decode("utf-8") if out else None
    return None if text is None or text.startswith("*") else text


def new_setting(lib, scheme: str) -> str:
    prefix = _PREFIX[scheme]
    if hasattr(lib, "crypt_gensalt_rn"):
        out = ctypes.create_string_buffer(256)
        made = lib.crypt_gensalt_rn(prefix.encode(), 0, os.urandom(32), 32, out, len(out))
        if made and not made.startswith(b"*"):
            return made.decode()
    if scheme != "sha512":
        raise BastetError(f"this machine's libcrypt can't make {scheme} hashes; install libxcrypt here, "
                          "or give password_hash instead")
    return prefix + "".join(secrets.choice(_ALPHABET) for _ in range(16))


def hash(password: str, scheme: str = "sha512") -> str:
    if scheme not in _PREFIX:
        raise ValueError(f"unknown password scheme: {scheme}")
    if "\n" in password or "\r" in password:
        raise BastetError("a password can't contain a line break")
    lib = _library()
    out = _crypt(lib, password, new_setting(lib, scheme))
    if out is None:
        raise BastetError("the system crypt library could not hash the password")
    return out


def matches(password: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) < 4 or parts[0] != "" or not all(parts[1:4]):
        return False
    out = _crypt(_library(), password, stored)
    return out is not None and secrets.compare_digest(out, stored)


def scheme_for(login_defs: str) -> str:
    for line in login_defs.splitlines():
        found = re.match(r"\s*ENCRYPT_METHOD\s+(\S+)", line, re.IGNORECASE)
        if found:
            return _METHOD.get(found.group(1).upper(), "sha512")
    return "sha512"
