from importlib import resources
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from bastet.core.errors import BastetError

Nature = Literal["desired", "fact", "yours"]


class HostType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    physical: bool = False
    gather: bool = True
    minimal: list[str] = []
    fields: dict[str, Nature] = {}
    roles: dict[str, dict] = {}


def _shipped_dir() -> Path:
    return Path(str(resources.files("bastet") / "data" / "types"))


def load_host_types(directory: Path | None = None) -> dict[str, HostType]:
    directory = directory or _shipped_dir()
    types: dict[str, HostType] = {}
    for path in sorted(directory.glob("*.yml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            host_type = HostType.model_validate(raw)
        except (yaml.YAMLError, ValidationError) as exc:
            raise BastetError(f"invalid host type: {exc}".splitlines()[0], file=path) from None
        types[host_type.name] = host_type
    return types
