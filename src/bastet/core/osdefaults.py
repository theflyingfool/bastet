"""Per-OS defaults (roles applied and accounts expected) and the shared account-name check."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from bastet.core.errors import BastetError
from bastet.core.osinfo import ARCH_LIKE

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


class OsDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    roles: dict[str, dict] = {}
    accounts: tuple[str, ...] = ()
    path: Path | None = Field(default=None, exclude=True)  # set by load_os_defaults, so errors can name the file

    @field_validator("accounts", mode="before")
    @classmethod
    def _accounts(cls, value: object) -> tuple[str, ...]:
        return check_accounts(value, "OS defaults")


def _shipped_dir() -> Path:
    return Path(str(resources.files("bastet") / "data" / "oses"))


def load_os_defaults(directory: Path | None = None) -> dict[str, OsDefaults]:
    directory = directory or _shipped_dir()
    found: dict[str, OsDefaults] = {}
    for path in sorted(directory.glob("*.yml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            defaults = OsDefaults.model_validate(raw)
        except BastetError as exc:
            raise BastetError(f"invalid OS defaults: {exc.message}", file=path, key=exc.key) from None
        except (yaml.YAMLError, ValidationError) as exc:
            raise BastetError(f"invalid OS defaults: {exc}".splitlines()[0], file=path) from None
        defaults.path = path
        found[defaults.name] = defaults
    return found


def defaults_for(os_id: str | None, directory: Path | None = None) -> OsDefaults | None:
    """The defaults for an OS id, or None when the OS is missing or has none yet."""
    if not os_id:
        return None
    return load_os_defaults(directory).get("arch" if os_id in ARCH_LIKE else os_id)
