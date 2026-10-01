"""Users family: users and groups (spec 9.2). Authorized keys and sudoers rules live here too (Task 5)."""

import datetime as dt
import re
import shlex
from dataclasses import dataclass
from typing import ClassVar

from bastet.engine.model import ABSENT, FieldChange, Read, ReadError, Resource, Unsupported

ACCOUNT = re.compile(r"^[a-z_][a-z0-9_-]*\$?$")
EPOCH = dt.date(1970, 1, 1)


def _q(text: str) -> str:
    return shlex.quote(text)


def _check_name(kind: str, name: str) -> None:
    if not ACCOUNT.match(name or "") or len(name) > 32:
        raise ValueError(f"not a {kind} name: {name!r}")


def _joined(values) -> str:
    return ", ".join(values) if values else "(none)"


@dataclass(frozen=True, kw_only=True)
class User(Resource):
    family: ClassVar[str] = "Users"
    name: str
    uid: int | None = None
    group: str | None = None
    groups: tuple[str, ...] | None = None
    append: bool = True
    comment: str | None = None
    home: str | None = None
    create_home: bool = True
    move_home: bool = False
    shell: str | None = None
    system: bool = False
    password_hash: str | None = None
    locked: bool | None = None
    expires: str | None = None

    def __post_init__(self):
        _check_name("user", self.name)
        if self.expires not in (None, "never"):
            dt.date.fromisoformat(self.expires)

    @property
    def identity(self) -> str:
        return f"user:{self.name}"

    @property
    def label(self) -> str:
        return f"user {self.name}"

    def desired(self):
        return {"exists": True, "uid": None if self.uid is None else str(self.uid), "group": self.group,
                "groups": None if self.groups is None else tuple(sorted(set(self.groups))), "comment": self.comment,
                "home": self.home, "shell": self.shell, "password": self.password_hash, "locked": self.locked,
                "expires": self.expires}

    def reads(self):
        n = _q(self.name)
        return (
            Read("passwd", f"getent passwd {n} || true"),
            Read("groups", f"printf '%s|%s' \"$(id -gn {n} 2>/dev/null)\" \"$(id -Gn {n} 2>/dev/null)\""),
            Read("shadow", f"getent shadow {n} || true", root=True),
            Read("tools", "command -v useradd || true"),
        )

    def current(self, results):
        if not results["tools"].output.strip():
            raise Unsupported("no useradd on this host (on Alpine, install the shadow package)")
        pw = results["passwd"].output.strip()
        if not pw:
            return {"exists": False}
        fields = pw.split(":")
        if len(fields) < 7:
            raise ReadError(f"unexpected passwd entry for {self.name}")
        primary, _, supplementary = results["groups"].output.strip().partition("|")
        groups = tuple(sorted(set(supplementary.split()) - {primary}))
        shadow = (results["shadow"].output.strip().split(":") + [""] * 9)[:9]
        hashed, expire_days = shadow[1], shadow[7]
        expires = "never" if not expire_days else (EPOCH + dt.timedelta(days=int(expire_days))).isoformat()
        return {"exists": True, "uid": fields[2], "group": primary, "groups": groups, "comment": fields[4],
                "home": fields[5], "shell": fields[6], "password": hashed.lstrip("!"), "locked": hashed.startswith("!"),
                "expires": expires}

    def compare(self, current):
        if not current.get("exists"):
            return [FieldChange("exists", False, True)] + [
                FieldChange(k, ABSENT, "(new)" if k == "password" else v)
                for k, v in self.desired().items() if k != "exists" and v is not None
            ]
        changes = []
        for k, v in self.desired().items():
            if v is None or k == "exists":
                continue
            have = current.get(k, ABSENT)
            if k == "groups":
                want = tuple(sorted(set(have) | set(v))) if self.append else v
                if set(want) != set(have):
                    changes.append(FieldChange("groups", _joined(have), _joined(want)))
            elif k == "password":
                if have != v:
                    changes.append(FieldChange("password", "(hidden)", "(new)"))
            elif have != v:
                changes.append(FieldChange(k, have, v))
        return changes

    def _password_cmd(self) -> str:
        return f"printf '%s:%s\\n' {_q(self.name)} {_q(str(self.password_hash))} | chpasswd -e"

    def fix(self, changes, current):
        fields = {c.field for c in changes}
        n = _q(self.name)
        cmds: list[str] = []
        if not current.get("exists"):
            args = ["useradd"]
            if self.uid is not None:
                args += ["-u", str(self.uid)]
            if self.group:
                args += ["-g", _q(self.group)]
            if self.groups:
                args += ["-G", _q(",".join(sorted(set(self.groups))))]
            if self.comment is not None:
                args += ["-c", _q(self.comment)]
            if self.home:
                args += ["-d", _q(self.home)]
            if self.shell:
                args += ["-s", _q(self.shell)]
            if self.expires and self.expires != "never":
                args += ["-e", self.expires]
            if self.system:
                args.append("-r")
            args.append("-m" if self.create_home else "-M")
            cmds.append(" ".join(args + [n]))
        else:
            args = []
            if "uid" in fields:
                args += ["-u", str(self.uid)]
            if "group" in fields:
                args += ["-g", _q(str(self.group))]
            if "comment" in fields:
                args += ["-c", _q(str(self.comment))]
            if "home" in fields:
                args += ["-d", _q(str(self.home))] + (["-m"] if self.move_home else [])
            if "shell" in fields:
                args += ["-s", _q(str(self.shell))]
            if "expires" in fields:
                args += ["-e", "''" if self.expires == "never" else str(self.expires)]
            if args:
                cmds.append(" ".join(["usermod", *args, n]))
            if "groups" in fields:
                listed = _q(",".join(sorted(set(self.groups or ()))))
                cmds.append(f"usermod -a -G {listed} {n}" if self.append else f"usermod -G {listed} {n}")
        if "password" in fields and self.password_hash is not None:
            cmds.append(self._password_cmd())
        if "locked" in fields:
            cmds.append(f"usermod {'-L' if self.locked else '-U'} {n}")
        return cmds


@dataclass(frozen=True, kw_only=True)
class Group(Resource):
    family: ClassVar[str] = "Users"
    name: str
    gid: int | None = None
    system: bool = False
    members: tuple[str, ...] | None = None

    def __post_init__(self):
        _check_name("group", self.name)

    @property
    def identity(self) -> str:
        return f"group:{self.name}"

    @property
    def label(self) -> str:
        return f"group {self.name}"

    def desired(self):
        return {"exists": True, "gid": None if self.gid is None else str(self.gid),
                "members": None if self.members is None else tuple(sorted(set(self.members)))}

    def reads(self):
        return (Read("group", f"getent group {_q(self.name)} || true"),)

    def current(self, results):
        line = results["group"].output.strip()
        if not line:
            return {"exists": False, "gid": ABSENT, "members": ABSENT}
        fields = (line.split(":") + ["", "", "", ""])[:4]
        return {"exists": True, "gid": fields[2], "members": tuple(sorted(m for m in fields[3].split(",") if m))}

    def compare(self, current):
        out = []
        for c in super().compare(current):
            if c.field == "members":
                out.append(FieldChange("members", _joined(c.before) if c.before != ABSENT else ABSENT, _joined(c.after)))
            else:
                out.append(c)
        return out

    def fix(self, changes, current):
        fields = {c.field for c in changes}
        n = _q(self.name)
        cmds = []
        if not current.get("exists"):
            cmds.append(" ".join(["groupadd"] + (["-g", str(self.gid)] if self.gid is not None else [])
                                 + (["-r"] if self.system else []) + [n]))
        elif "gid" in fields:
            cmds.append(f"groupmod -g {self.gid} {n}")
        if "members" in fields:
            cmds.append(f"gpasswd -M {_q(','.join(sorted(set(self.members or ()))))} {n}")
        return cmds
