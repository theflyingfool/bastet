import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from bastet.core.errors import BastetError


class InventoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remote: str | None = None
    path: Path | None = None

    @field_validator("path")
    @classmethod
    def _absolute(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        value = value.expanduser()
        if not value.is_absolute():
            raise ValueError("must be an absolute path or start with ~")
        return value

    @model_validator(mode="after")
    def _remote_or_path(self) -> "InventoryConfig":
        if self.remote is None and self.path is None:
            raise ValueError("set at least one of 'remote' or 'path'")
        return self


class SecretsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age_identity: Path | None = None

    @field_validator("age_identity")
    @classmethod
    def _expand(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None


class SshConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Path | None = None
    bootstrap_user: str | None = None

    @field_validator("key")
    @classmethod
    def _absolute_key(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        value = value.expanduser()
        if not value.is_absolute():
            raise ValueError("must be an absolute path or start with ~")
        return value


class GatherConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    install_tools: Literal["ask", "always", "never"] = "ask"


class ParallelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: int = 8

    @field_validator("jobs")
    @classmethod
    def _at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("must be at least 1")
        return value


class RunsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_runs: int | None = None  # None: keep every run
    keep_days: int | None = None

    @field_validator("keep_runs", "keep_days")
    @classmethod
    def _at_least_one(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("must be at least 1, or empty to keep every run")
        return value


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory: InventoryConfig
    secrets: SecretsConfig = SecretsConfig()
    ssh: SshConfig = SshConfig()
    gather: GatherConfig = GatherConfig()
    parallel: ParallelConfig = ParallelConfig()
    runs: RunsConfig = RunsConfig()


def config_path(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("BASTET_CONFIG"):
        return Path(env["BASTET_CONFIG"]).expanduser()
    base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else Path.home() / ".config"
    return base / "bastet" / "bastet.yml"


def data_dir(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    base = Path(env["XDG_DATA_HOME"]) if env.get("XDG_DATA_HOME") else Path.home() / ".local" / "share"
    return base / "bastet"


def inventory_dir(config: Config, data: Path) -> Path:
    return config.inventory.path if config.inventory.path is not None else data / "inventory"


def _key_line(text: str, loc: Sequence[str | int]) -> int | None:
    """1-based line where the last key of `loc` appears, searching keys in order."""
    lines = text.splitlines()
    start = 0
    found = None
    for part in loc:
        if not isinstance(part, str):
            continue
        pattern = re.compile(rf"^\s*{re.escape(part)}\s*:")
        for i in range(start, len(lines)):
            if pattern.match(lines[i]):
                found = i + 1
                start = i + 1
                break
        else:
            return found
    return found


def load_config(path: Path) -> Config:
    if not path.exists():
        raise BastetError("config file not found", file=path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BastetError(f"cannot read config: {exc.__class__.__name__}", file=path) from None
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        problem = getattr(exc, "problem", None) or str(exc)
        raise BastetError(
            f"invalid YAML: {problem}",
            file=path,
            line=mark.line + 1 if mark is not None else None,
        ) from None
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BastetError("expected a mapping of settings at the top level", file=path)
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        errors = exc.errors()
        err = next((e for e in errors if e["type"] == "extra_forbidden"), errors[0])
        loc = [p for p in err["loc"] if isinstance(p, (str, int))]
        message = err["msg"].removeprefix("Value error, ")
        raise BastetError(
            message,
            file=path,
            line=_key_line(text, loc),
            key=".".join(str(p) for p in loc) or None,
        ) from None
