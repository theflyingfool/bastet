"""Per-OS defaults (roles applied and accounts expected) and the shared account-name check."""

from __future__ import annotations

import re
from pathlib import Path

from bastet.core.errors import BastetError

ACCOUNT = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*\$?")


def _valid(name: object) -> bool:
    return isinstance(name, str) and ACCOUNT.fullmatch(name) is not None


def check_accounts(value: object, where: str, path: Path | None = None) -> tuple[str, ...]:
    """A list of account names (accounts a role or an OS expects on a host), or () when absent."""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(_valid(v) for v in value):
        bad = next((v for v in value if not _valid(v)), None) if isinstance(value, list) else value
        raise BastetError(f"{where}: accounts must be a list of account names (letters, digits, _ . -), not {bad!r}",
                          file=path, key="accounts")
    return tuple(dict.fromkeys(value))
