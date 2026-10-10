"""Users family: users and groups. Authorized keys and sudoers rules live here too."""

import base64
import datetime as dt
import re
import shlex
from dataclasses import dataclass
from typing import ClassVar

from bastet.core.shell import ProbeResult
from bastet.engine.files import FILE_TAIL, File, _parse_file
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
    slot: ClassVar[str] = "users"
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
    update_password: str = "always"
    locked: bool | None = None
    expires: str | None = None
    max_days: int | None = None
    min_days: int | None = None
    warn_days: int | None = None
    inactive_days: int | None = None
    non_unique: bool = False
    skeleton: str | None = None

    def __post_init__(self):
        _check_name("user", self.name)
        if self.update_password not in ("always", "on_create"):
            raise ValueError("update_password must be always or on_create")
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
                "expires": self.expires, **{k: None if v is None else str(v) for k, v in self._ageing().items()}}

    def _ageing(self) -> dict[str, int | None]:
        return {"max_days": self.max_days, "min_days": self.min_days, "warn_days": self.warn_days,
                "inactive_days": self.inactive_days}

    def reads(self):
        n = _q(self.name)
        return (
            Read("passwd", f"getent passwd {n} || true"),
            Read("groups", f"printf '%s|%s' \"$(id -gn {n} 2>/dev/null)\" \"$(id -Gn {n} 2>/dev/null)\""),
            Read("shadow", f"getent shadow {n} || true", root=True),
            Read("tools", "command -v useradd || true", root=True),
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
        ageing = {"min_days": shadow[3], "max_days": shadow[4], "warn_days": shadow[5], "inactive_days": shadow[6]}
        return {"exists": True, "uid": fields[2], "group": primary, "groups": groups, "comment": fields[4],
                "home": fields[5], "shell": fields[6], "password": hashed.lstrip("!"), "locked": hashed.startswith("!"),
                "expires": expires, **{k: v or ABSENT for k, v in ageing.items()}}

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
                if have != v and self.update_password == "always":
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
                args += ["-u", str(self.uid)] + (["-o"] if self.non_unique else [])
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
            if self.skeleton and self.create_home:
                args += ["-k", _q(self.skeleton)]
            args.append("-m" if self.create_home else "-M")
            cmds.append(" ".join(args + [n]))
        else:
            args = []
            if "uid" in fields:
                args += ["-u", str(self.uid)] + (["-o"] if self.non_unique else [])
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
        ageing = [(flag, k) for flag, k in (("-M", "max_days"), ("-m", "min_days"), ("-W", "warn_days"),
                                              ("-I", "inactive_days")) if k in fields]
        if ageing:
            cmds.append(" ".join(["chage"] + [f"{flag} {self._ageing()[k]}" for flag, k in ageing] + [n]))
        if "password" in fields and self.password_hash is not None:
            cmds.append(self._password_cmd())
        if "locked" in fields:
            cmds.append(f"usermod {'-L' if self.locked else '-U'} {n}")
        elif "password" in fields and (self.locked is True or (self.locked is None and current.get("locked") is True)):
            cmds.append(f"usermod -L {n}")  # chpasswd drops the lock; put it back
        return cmds


@dataclass(frozen=True, kw_only=True)
class Group(Resource):
    family: ClassVar[str] = "Users"
    slot: ClassVar[str] = "users"
    name: str
    gid: int | None = None
    system: bool = False
    members: tuple[str, ...] | None = None
    append_members: bool = False

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
            if c.field == "members" and self.append_members and current.get("exists"):
                have = set(current["members"])
                if not set(self.members or ()) <= have:
                    out.append(FieldChange("members", _joined(tuple(sorted(have))),
                                           _joined(tuple(sorted(have | set(self.members or ()))))))
            elif c.field == "members":
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
        if "members" in fields and self.append_members and current.get("exists"):
            have = set(current.get("members") or ())
            cmds += [f"gpasswd -a {_q(m)} {n}" for m in sorted(set(self.members or ()) - have)]
        elif "members" in fields:
            cmds.append(f"gpasswd -M {_q(','.join(sorted(set(self.members or ()))))} {n}")
        return cmds


SUDOERS_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True, kw_only=True)
class AuthorizedKey(Resource):
    family: ClassVar[str] = "Users"
    slot: ClassVar[str] = "users"
    user: str
    key: str
    options: str | None = None
    path: str | None = None
    state: str = "present"

    def __post_init__(self):
        _check_name("user", self.user)
        if self.state not in ("present", "absent"):
            raise ValueError("key state must be present or absent")
        if len(self.key.split()) < 2:
            raise ValueError(f"not an SSH public key: {self.key[:30]!r}")

    @property
    def body(self) -> str:
        return self.key.split()[1]

    @property
    def identity(self) -> str:
        return f"authkey:{self.user}:{self.body}"

    @property
    def label(self) -> str:
        parts = self.key.split()
        return f"{self.user} key {parts[2] if len(parts) > 2 else self.body[-12:]}"

    def touches(self) -> str | None:
        return self.path or f"~{self.user}/.ssh/authorized_keys"

    def _where(self) -> str:
        n = _q(self.user)
        p = _q(self.path) if self.path else '"$h/.ssh/authorized_keys"'
        return f"n={n}; h=$(getent passwd \"$n\" | cut -d: -f6); p={p}"

    def desired(self):
        return {"key": self.key.strip(), "options": self.options, "state": self.state}

    def reads(self):
        command = f"{self._where()}; if [ -z \"$h\" ]; then echo nouser; exit 0; fi; echo \"$p\"; {FILE_TAIL}"
        return (Read("keys", command, root=True),)

    def current(self, results):
        out = results["keys"].output
        if out.strip() == "nouser":
            return {"content": ABSENT, "mode": ABSENT}
        path, _, rest = out.partition("\n")
        state = _parse_file(ProbeResult(results["keys"].returncode, rest))
        return {"path": path, "content": state["content"], "mode": state["mode"]}

    def line(self) -> str:
        return f"{self.options} {self.key.strip()}" if self.options else self.key.strip()

    def wanted(self, content: object) -> str:
        text = "" if content == ABSENT else str(content)
        lines = text.splitlines(keepends=True)
        if self.state == "absent":
            return "".join(line for line in lines if self.body not in line.split())
        for i, line in enumerate(lines):
            if self.body in line.split():
                lines[i] = self.line() + "\n"
                return "".join(lines)
        sep = "" if not text or text.endswith("\n") else "\n"
        return text + sep + self.line() + "\n"

    def compare(self, current):
        old = current["content"]
        if self.state == "absent":
            return [] if old == ABSENT or self.wanted(old) == old else [FieldChange("key", "present", "absent")]
        changes = []
        if self.wanted(old) != old:
            changes.append(FieldChange("key", ABSENT if old == ABSENT or self.body not in str(old) else "(other options)", "present"))
        if old != ABSENT and current.get("mode") != "0600":
            changes.append(FieldChange("mode", current.get("mode"), "0600"))
        return changes

    def fix(self, changes, current):
        data = base64.b64encode(self.wanted(current["content"]).encode("utf-8")).decode("ascii")
        n = _q(self.user)
        return [
            self._where(),
            'test -n "$h" || { echo "user $n does not exist" >&2; exit 1; }',
            'g=$(id -gn "$n")',
            'd=$(dirname "$p"); mkdir -p "$d"' + ('; chown "$n:$g" "$d"; chmod 700 "$d"' if self.path is None else ""),
            't="$p.bastet-tmp"; trap \'rm -f -- "$t"\' EXIT',
            f"printf '%s' '{data}' | base64 -d > \"$t\"",
            'chown "$n:$g" "$t"; chmod 600 "$t"; mv -f "$t" "$p"',
        ]


def sudoer(name: str, *, rules: tuple[str, ...] = (), user: str | None = None, group: str | None = None,
           commands: tuple[str, ...] = ("ALL",), runas: str = "ALL", hosts: str = "ALL", nopasswd: bool = False,
           setenv: bool = False, defaults: tuple[str, ...] = ()) -> File:
    """A validated file in /etc/sudoers.d: a rule for a user or %group, Defaults lines, and raw rules."""
    if not SUDOERS_NAME.match(name or ""):
        raise ValueError(f"not a sudoers file name (letters, digits, - and _ only; sudo skips others): {name!r}")
    who = user if user else (f"%{group}" if group else None)
    lines = ["# Managed by Bastet"]
    lines += [f"Defaults:{who} {d}" if who else f"Defaults {d}" for d in defaults]
    if who:
        tags = " ".join(t for t, on in (("NOPASSWD:", nopasswd), ("SETENV:", setenv)) if on)
        lines.append(f"{who} {hosts}=({runas}) {tags + ' ' if tags else ''}{', '.join(commands)}")
    lines += list(rules)
    return File(path=f"/etc/sudoers.d/{name}", content="\n".join(lines) + "\n", owner="root", group="root",
                mode="0440", validate="visudo -cf %s")
