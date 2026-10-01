"""Files family: whole files, directories, symlinks, and a block or line inside someone else's file."""

import base64
import binascii
import difflib
import posixpath
import re
import shlex
from dataclasses import dataclass
from typing import ClassVar

from bastet.core.collect import ProbeResult
from bastet.engine.model import ABSENT, FieldChange, Read, ReadError, Resource


def _q(text: str) -> str:
    return shlex.quote(text)


def _mode(text: object) -> str | None:
    return None if text in (None, "", ABSENT) else format(int(str(text), 8), "04o")


def _known(value: object) -> str | None:
    return None if value in (None, ABSENT) else str(value)


def _lines(r: ProbeResult) -> list[str]:
    if not r.ok:
        raise ReadError(f"read failed (exit {r.returncode})")
    return r.output.split("\n")


def _file_read(path: str, root: bool) -> Read:
    command = (
        f"p={_q(path)}; if [ -L \"$p\" ]; then echo link; elif [ -f \"$p\" ]; then echo file; "
        "stat -c '%U %G %a' \"$p\"; base64 < \"$p\" | tr -d '\\n'; echo; "
        "elif [ -e \"$p\" ]; then echo other; else echo absent; fi"
    )
    return Read("file", command, root=root)


def _parse_file(r: ProbeResult) -> dict[str, object]:
    lines = _lines(r)
    kind = lines[0].strip()
    if kind == "absent":
        return {"content": ABSENT, "owner": ABSENT, "group": ABSENT, "mode": ABSENT}
    if kind != "file":
        raise ReadError(f"exists and isn't a regular file ({kind})")
    owner, group, mode = lines[1].split()
    try:
        content = base64.b64decode(lines[2] if len(lines) > 2 else "", validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        raise ReadError("isn't a text file") from None
    return {"content": content, "owner": owner, "group": group, "mode": _mode(mode)}


def _chown(owner: str | None, group: str | None, target: str) -> list[str]:
    if not owner and not group:
        return []
    spec = (owner or "") + (f":{group}" if group else "")
    return [f"chown {_q(spec)} {target}"]


def _write(path: str, content: str, *, owner, group, mode, validate, in_place: bool) -> list[str]:
    """Write via a temporary file: validated first; renamed into place (new file) or copied over (keeps inode)."""
    p, tmp = _q(path), _q(path + ".bastet-tmp")
    data = base64.b64encode(content.encode("utf-8")).decode("ascii")
    cmds = [f"mkdir -p {_q(posixpath.dirname(path) or '/')}", f"printf '%s' '{data}' | base64 -d > {tmp}"]
    if validate:
        cmds.append(f"{validate.replace('%s', tmp)} || {{ rm -f {tmp}; exit 1; }}")
    if in_place:
        cmds += [f"cat {tmp} > {p}", f"rm -f {tmp}"]
        cmds += _chown(owner, group, p) + ([f"chmod {mode} {p}"] if mode else [])
    else:
        cmds += _chown(owner, group, tmp) + ([f"chmod {mode} {tmp}"] if mode else [])
        cmds.append(f"mv -f {tmp} {p}")
    return cmds


def _diff(before: object, after: str) -> str:
    old = "" if before == ABSENT else str(before)
    lines = list(difflib.unified_diff(old.splitlines(), after.splitlines(), lineterm="", n=1))[2:]
    if len(lines) > 40:
        lines = lines[:40] + [f"… {len(lines) - 40} more lines"]
    return "\n".join(lines)


@dataclass(frozen=True, kw_only=True)
class File(Resource):
    family: ClassVar[str] = "Files"
    path: str
    content: str
    owner: str | None = None
    group: str | None = None
    mode: str | None = None
    validate: str | None = None

    @property
    def identity(self) -> str:
        return f"file:{self.path}"

    @property
    def label(self) -> str:
        return self.path

    def touches(self) -> str | None:
        return self.path

    def desired(self):
        return {"content": self.content, "owner": self.owner, "group": self.group, "mode": _mode(self.mode)}

    def reads(self):
        return (_file_read(self.path, self.root),)

    def current(self, results):
        return _parse_file(results["file"])

    def fix(self, changes, current):
        fields = {c.field for c in changes}
        if "content" in fields:
            return _write(
                self.path, self.content,
                owner=self.owner or _known(current.get("owner")), group=self.group or _known(current.get("group")),
                mode=_mode(self.mode) or _known(current.get("mode")), validate=self.validate, in_place=False,
            )
        cmds = _chown(self.owner, self.group, _q(self.path)) if fields & {"owner", "group"} else []
        if "mode" in fields:
            cmds.append(f"chmod {_mode(self.mode)} {_q(self.path)}")
        return cmds

    def diff_text(self, current):
        return _diff(current.get("content", ABSENT), self.content)


@dataclass(frozen=True, kw_only=True)
class Directory(Resource):
    family: ClassVar[str] = "Files"
    path: str
    owner: str | None = None
    group: str | None = None
    mode: str | None = None

    @property
    def identity(self) -> str:
        return f"dir:{self.path}"

    @property
    def label(self) -> str:
        return self.path.rstrip("/") + "/"

    def touches(self) -> str | None:
        return self.path

    def desired(self):
        return {"exists": True, "owner": self.owner, "group": self.group, "mode": _mode(self.mode)}

    def reads(self):
        command = (
            f"p={_q(self.path)}; if [ -d \"$p\" ] && [ ! -L \"$p\" ]; then echo dir; stat -c '%U %G %a' \"$p\"; "
            "elif [ -e \"$p\" ]; then echo other; else echo absent; fi"
        )
        return (Read("dir", command, root=self.root),)

    def current(self, results):
        lines = _lines(results["dir"])
        kind = lines[0].strip()
        if kind == "absent":
            return {"exists": False, "owner": ABSENT, "group": ABSENT, "mode": ABSENT}
        if kind != "dir":
            raise ReadError("exists and isn't a directory")
        owner, group, mode = lines[1].split()
        return {"exists": True, "owner": owner, "group": group, "mode": _mode(mode)}

    def fix(self, changes, current):
        fields = {c.field for c in changes}
        p = _q(self.path)
        cmds = [f"mkdir -p {p}"] if "exists" in fields else []
        if (self.owner or self.group) and fields & {"exists", "owner", "group"}:
            cmds += _chown(self.owner, self.group, p)
        if self.mode and fields & {"exists", "mode"}:
            cmds.append(f"chmod {_mode(self.mode)} {p}")
        return cmds


@dataclass(frozen=True, kw_only=True)
class Symlink(Resource):
    family: ClassVar[str] = "Files"
    path: str
    target: str

    @property
    def identity(self) -> str:
        return f"link:{self.path}"

    @property
    def label(self) -> str:
        return self.path

    def touches(self) -> str | None:
        return self.path

    def desired(self):
        return {"target": self.target}

    def reads(self):
        command = (
            f"p={_q(self.path)}; if [ -L \"$p\" ]; then echo link; readlink \"$p\"; "
            "elif [ -e \"$p\" ]; then echo other; else echo absent; fi"
        )
        return (Read("link", command, root=self.root),)

    def current(self, results):
        lines = _lines(results["link"])
        kind = lines[0].strip()
        if kind == "absent":
            return {"target": ABSENT}
        if kind != "link":
            raise ReadError("exists and isn't a symlink; not replacing it")
        return {"target": lines[1].strip()}

    def fix(self, changes, current):
        return [f"mkdir -p {_q(posixpath.dirname(self.path) or '/')}", f"ln -sfn {_q(self.target)} {_q(self.path)}"]


@dataclass(frozen=True, kw_only=True)
class _Edit(Resource):
    """Shared by Block and Line: edits part of a file someone else owns, keeping its owner and mode."""

    family: ClassVar[str] = "Files"
    path: str
    validate: str | None = None

    def touches(self) -> str | None:
        return self.path

    def reads(self):
        return (_file_read(self.path, self.root),)

    def current(self, results):
        return _parse_file(results["file"])

    def wanted(self, content: object) -> str:
        raise NotImplementedError

    def compare(self, current):
        old = current["content"]
        if self.wanted(old) == old:
            return []
        return [FieldChange("content", ABSENT if old == ABSENT else "current", "desired")]

    def fix(self, changes, current):
        old = current["content"]
        exists = old != ABSENT
        return _write(self.path, self.wanted(old), owner=None, group=None, mode=None if exists else "0644",
                      validate=self.validate, in_place=exists)

    def diff_text(self, current):
        return _diff(current["content"], self.wanted(current["content"]))


@dataclass(frozen=True, kw_only=True)
class Block(_Edit):
    block: str
    marker: str
    comment: str = "#"

    @property
    def identity(self) -> str:
        return f"block:{self.path}:{self.marker}"

    @property
    def label(self) -> str:
        return f"{self.path} ({self.marker})"

    def desired(self):
        return {"block": self.block}

    def wanted(self, content):
        text = "" if content == ABSENT else str(content)
        begin, end = f"{self.comment} BEGIN {self.marker}", f"{self.comment} END {self.marker}"
        new = f"{begin}\n{self.block.rstrip(chr(10))}\n{end}\n"
        lines = text.splitlines(keepends=True)
        stripped = [line.rstrip("\n") for line in lines]
        if begin in stripped:
            i = stripped.index(begin)
            j = next((k for k in range(i + 1, len(stripped)) if stripped[k] == end), None)
            if j is not None:
                return "".join(lines[:i]) + new + "".join(lines[j + 1:])
        sep = "" if not text or text.endswith("\n") else "\n"
        return text + sep + new


@dataclass(frozen=True, kw_only=True)
class Line(_Edit):
    line: str
    match: str | None = None

    @property
    def identity(self) -> str:
        return f"line:{self.path}:{self.match or self.line}"

    @property
    def label(self) -> str:
        return f"{self.path} ({self.line})"

    def desired(self):
        return {"line": self.line, "match": self.match}

    def wanted(self, content):
        text = "" if content == ABSENT else str(content)
        lines = text.splitlines(keepends=True)
        stripped = [line.rstrip("\n") for line in lines]
        if self.match:
            hits = [i for i, line in enumerate(stripped) if re.search(self.match, line)]
            if hits:
                lines[hits[-1]] = self.line + "\n"
                return "".join(lines)
        elif self.line in stripped:
            return text
        sep = "" if not text or text.endswith("\n") else "\n"
        return text + sep + self.line + "\n"
