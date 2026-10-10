"""The engine's vocabulary: resources, reads, field changes and triggers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from bastet.core.shell import ProbeResult

ABSENT = "(absent)"


class ReadError(Exception):
    """A resource's read output couldn't be understood."""


class Unsupported(Exception):
    """This host can't have the resource (e.g. no systemd); the item is skipped with this reason."""


@dataclass(frozen=True)
class Read:
    name: str
    command: str
    root: bool = False


@dataclass(frozen=True)
class Trigger:
    """An action run once at the end of a host's run when a resource that names it changed (restart, reload…)."""

    label: str
    command: str
    order: int = 50
    root: bool = True
    check: str | None = None  # run after the command succeeds; must pass within check_tries tries
    check_tries: int = 5
    check_wait: float = 1.0


@dataclass(frozen=True)
class FieldChange:
    field: str
    before: object
    after: object


def show_value(value: object, *, secret: bool = False) -> str:
    if secret and value != ABSENT:
        return "(secret)"
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value is None:
        return "(unset)"
    text = str(value)
    return "(contents)" if "\n" in text or len(text) > 60 else text


@dataclass(frozen=True, kw_only=True)
class Resource(ABC):
    """The desired state of one thing on one host."""

    family: ClassVar[str] = "Other"
    slot: ClassVar[str] = "commands"
    on_change: tuple[Trigger, ...] = ()
    root: bool = True
    secret: bool = False
    run_before: str | None = None
    run_after: str | None = None
    provides: tuple[str, ...] = ()

    @property
    @abstractmethod
    def identity(self) -> str:
        """Stable key: two resources with the same identity describe the same thing."""

    @property
    @abstractmethod
    def label(self) -> str:
        """What the report calls it."""

    @abstractmethod
    def desired(self) -> dict[str, object]:
        """Fields Bastet makes true; None means 'leave as it is'."""

    @abstractmethod
    def reads(self) -> tuple[Read, ...]: ...

    @abstractmethod
    def current(self, results: dict[str, ProbeResult]) -> dict[str, object]:
        """Parse read output into current field values; raise ReadError or Unsupported."""

    def compare(self, current: dict[str, object]) -> list[FieldChange]:
        return [
            FieldChange(k, current.get(k, ABSENT), v)
            for k, v in self.desired().items()
            if v is not None and current.get(k, ABSENT) != v
        ]

    @abstractmethod
    def fix(self, changes: list[FieldChange], current: dict[str, object]) -> list[str]:
        """Shell commands that make the changes."""

    def diff_text(self, current: dict[str, object]) -> str | None:
        return None

    def group_key(self) -> str | None:
        """Consecutive changed items in a batch with the same key are fixed by one fix_group call."""
        return None

    @classmethod
    def fix_group(cls, members: list[tuple["Resource", list[FieldChange], dict[str, object]]]) -> list[str]:
        raise NotImplementedError

    def report_only(self) -> bool:
        """Findings to report, never to fix (pending manual updates, packages nothing accounts for)."""
        return False

    def touches(self) -> str | None:
        """Path this resource edits, so a later edit of the same file in one run re-reads it first."""
        return None
