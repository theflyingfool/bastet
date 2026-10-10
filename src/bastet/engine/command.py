"""The escape hatch: a command plus a check that decides whether it needs to run. Always explicit."""

from dataclasses import dataclass
from typing import ClassVar

from bastet.engine.model import FieldChange, Read, Resource


@dataclass(frozen=True, kw_only=True)
class Command(Resource):
    family: ClassVar[str] = "Commands"
    slot: ClassVar[str] = "commands"
    name: str
    run: str
    unless: str

    @property
    def identity(self) -> str:
        return f"command:{self.name}"

    @property
    def label(self) -> str:
        return self.name

    def desired(self):
        return {"run": self.run, "unless": self.unless}

    def reads(self):
        return (Read("unless", self.unless, root=self.root),)

    def current(self, results):
        return {"done": results["unless"].returncode == 0}

    def compare(self, current):
        return [] if current["done"] else [FieldChange("done", False, True)]

    def fix(self, changes, current):
        return [self.run]
