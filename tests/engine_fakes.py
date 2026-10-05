"""Small resources for engine tests. They act on files under a temp dir, so LocalRunner runs them for real."""

import re
import shlex
from dataclasses import dataclass
from typing import ClassVar

from bastet.core.remote import CommandResult
from bastet.engine.model import ABSENT, FieldChange, Read, Resource, Unsupported


def _cat(path: str, root: bool) -> Read:
    return Read("cat", f"cat {shlex.quote(path)} 2>/dev/null || true", root=root)


@dataclass(frozen=True, kw_only=True)
class Flag(Resource):
    family: ClassVar[str] = "Files"
    path: str
    value: str
    root: bool = False

    @property
    def identity(self) -> str:
        return f"flag:{self.path}"

    @property
    def label(self) -> str:
        return self.path

    def touches(self) -> str | None:
        return self.path

    def desired(self):
        return {"value": self.value}

    def reads(self):
        return (_cat(self.path, self.root),)

    def current(self, results):
        return {"value": results["cat"].output or ABSENT}

    def fix(self, changes, current):
        return [f"printf '%s' {shlex.quote(self.value)} > {shlex.quote(self.path)}"]


@dataclass(frozen=True, kw_only=True)
class Stubborn(Flag):
    def fix(self, changes, current):
        return ["true"]


@dataclass(frozen=True, kw_only=True)
class Broken(Flag):
    def fix(self, changes, current):
        return ["echo boom >&2", "exit 3"]


@dataclass(frozen=True, kw_only=True)
class NoSystemd(Flag):
    def current(self, results):
        raise Unsupported("no systemd on this host")


@dataclass(frozen=True, kw_only=True)
class Append(Resource):
    """Adds one line to a shared file; the fix rewrites the whole file from what was read."""

    family: ClassVar[str] = "Files"
    path: str
    text: str
    root: bool = False

    @property
    def identity(self) -> str:
        return f"append:{self.path}:{self.text}"

    @property
    def label(self) -> str:
        return f"{self.path} ({self.text})"

    def touches(self) -> str | None:
        return self.path

    def desired(self):
        return {"text": self.text}

    def reads(self):
        return (_cat(self.path, self.root),)

    def current(self, results):
        return {"content": results["cat"].output}

    def compare(self, current):
        lines = [line for line in str(current["content"]).split("\n") if line]
        return [] if self.text in lines else [FieldChange("text", ABSENT, self.text)]

    def fix(self, changes, current):
        lines = [line for line in str(current["content"]).split("\n") if line] + [self.text]
        return [f"printf '%s\\n' {shlex.quote(chr(10).join(lines))} > {shlex.quote(self.path)}"]


class DeniedRunner:
    """Answers every read with exit 126, as the prelude does when sudo -n isn't available."""

    name = "denied"

    def run(self, script, *, timeout=120):
        mark = re.search(r"'(@@BASTET-[0-9a-f]+@@)'", script).group(1)
        names = re.findall(r"printf '%s %s %s\\n' '[^']+' '([^']+)'", script)
        return CommandResult("".join(f"{mark} {n} 126\n\n" for n in names), "", 0)


class ExplodingRunner:
    name = "exploding"

    def run(self, script, *, timeout=120):
        raise AssertionError("nothing should have run")


@dataclass(frozen=True, kw_only=True)
class Unreadable(Flag):
    def current(self, results):
        from bastet.engine.model import ReadError
        raise ReadError("exists and isn't a regular file (dir)")


@dataclass(frozen=True, kw_only=True)
class UnreadableReportOnly(Unreadable):
    """A report-only resource (like `updates: manual`) whose read fails."""

    def report_only(self) -> bool:
        return True


class SilentRunner:
    """Returns no sections at all, as when a read script dies early."""

    name = "silent"

    def run(self, script, *, timeout=120):
        return CommandResult("", "", 0)


@dataclass(frozen=True, kw_only=True)
class GroupedFlag(Flag):
    """Like Flag, but consecutive ones are written by one script that also logs one line per call."""

    log: str = ""

    def group_key(self):
        return f"grouped:{self.log}"

    @classmethod
    def fix_group(cls, members):
        cmds = [f"echo call >> {shlex.quote(members[0][0].log)}"]
        for res, _changes, _current in members:
            cmds.append(f"printf '%s' {shlex.quote(res.value)} > {shlex.quote(res.path)}")
        return cmds

    def fix(self, changes, current):
        return type(self).fix_group([(self, changes, current)])


@dataclass(frozen=True, kw_only=True)
class BrokenGroup(GroupedFlag):
    @classmethod
    def fix_group(cls, members):
        return ["echo 'E: Unable to locate package nope' >&2", "exit 100"]
