"""Packages family: packages for apt, pacman, dnf, zypper and apk, and their repositories (spec 9.2)."""

import re
import shlex
from dataclasses import dataclass
from typing import ClassVar

from bastet.engine.model import ABSENT, Read, ReadError, Resource, Unsupported

MANAGERS = ("apt-get", "pacman", "dnf", "zypper", "apk")
DETECT = ("for m in apt-get pacman dnf zypper apk; do "
          "command -v $m >/dev/null 2>&1 && { echo $m; exit 0; }; done; exit 127")
NAME = re.compile(r"^[A-Za-z0-9@._+:][A-Za-z0-9@._+:-]*$")
APT = "apt-get -o DPkg::Lock::Timeout=120"
REFRESH = {"apt-get": f"{APT} update -q", "dnf": "dnf makecache -q", "zypper": "zypper --non-interactive refresh",
           "apk": "apk update -q"}


def _q(text: str) -> str:
    return shlex.quote(text)


def _query(name: str) -> str:
    n = _q(name)
    return (f"case \"$({DETECT})\" in "
            f"apt-get) dpkg-query -W -f='${{db:Status-Abbrev}}|${{Version}}\\n' -- {n} 2>/dev/null;; "
            f"pacman) pacman -Q -- {n} 2>/dev/null;; "
            f"dnf|zypper) rpm -q --qf '%{{VERSION}}-%{{RELEASE}}\\n' -- {n} 2>/dev/null;; "
            f"apk) apk info -e -v {n} 2>/dev/null;; esac; true")


def _installed(manager: str, name: str, output: str) -> str | None:
    out = output.strip()
    if not out:
        return None
    first = out.splitlines()[0]
    if manager == "apt-get":
        status, _, version = first.partition("|")
        return version.strip() if status.startswith("ii") else None
    if manager == "pacman":
        parts = first.split()
        return parts[1] if len(parts) > 1 else None
    if manager in ("dnf", "zypper"):
        return None if first.startswith("package ") or "not installed" in first else first.strip()
    if manager == "apk":
        return first[len(name) + 1:] if first.startswith(name + "-") else None
    return None


@dataclass(frozen=True, kw_only=True)
class Package(Resource):
    family: ClassVar[str] = "Packages"
    name: str
    state: str = "present"
    version: str | None = None
    refresh: bool = True
    install_recommends: bool | None = None
    purge: bool = False
    full_upgrade: bool = False
    manager: str | None = None

    def __post_init__(self):
        if not NAME.match(self.name or ""):
            raise ValueError(f"not a package name: {self.name!r}")
        if self.state not in ("present", "absent"):
            raise ValueError(f"package state must be present or absent, not {self.state!r}")
        if self.manager is not None and self.manager not in MANAGERS:
            raise ValueError(f"unknown package manager {self.manager!r}")

    @property
    def identity(self) -> str:
        return f"package:{self.name}"

    @property
    def label(self) -> str:
        return f"{self.name} {self.version}" if self.version else self.name

    def desired(self):
        return {"state": self.state, "version": self.version if self.state == "present" else None}

    def reads(self):
        return (Read("manager", DETECT), Read("query", _query(self.name)))

    def current(self, results):
        m = results["manager"]
        if not m.ok or not m.output.strip():
            raise Unsupported("no supported package manager (apt, pacman, dnf, zypper, apk)")
        manager = m.output.strip()
        if self.manager is not None and self.manager != manager:
            raise ReadError(f"expected {self.manager}, but this host uses {manager}")
        if self.version is not None and manager == "pacman":
            raise Unsupported("pacman can't install a specific version")
        version = _installed(manager, self.name, results["query"].output)
        return {"state": "present" if version else "absent", "version": version or ABSENT, "manager": manager}

    def group_key(self):
        return f"package:{self.state}:{self.refresh}:{self.install_recommends}:{self.purge}:{self.full_upgrade}"

    def _spec(self, manager: str) -> str:
        if self.version is None or self.state == "absent":
            return self.name
        return f"{self.name}-{self.version}" if manager == "dnf" else f"{self.name}={self.version}"

    @classmethod
    def fix_group(cls, members):
        first, _, current = members[0]
        manager = str(current["manager"])
        specs = " ".join(_q(p._spec(manager)) for p, _, _ in members)
        if first.state == "absent":
            return [{
                "apt-get": f"DEBIAN_FRONTEND=noninteractive {APT} {'purge' if first.purge else 'remove'} -y -q -- {specs}",
                "pacman": f"pacman {'-Rns' if first.purge else '-R'} --noconfirm -- {specs}",
                "dnf": f"dnf remove -y -q -- {specs}",
                "zypper": f"zypper --non-interactive remove -- {specs}",
                "apk": f"apk del -q {specs}",
            }[manager]]
        cmds = [REFRESH[manager]] if first.refresh and manager in REFRESH else []
        recommends = {True: " --install-recommends", False: " --no-install-recommends", None: ""}[first.install_recommends]
        cmds.append({
            "apt-get": f"DEBIAN_FRONTEND=noninteractive {APT} install -y -q{recommends} -- {specs}",
            "pacman": f"pacman {'-Syu' if first.full_upgrade else '-S'} --noconfirm --needed -- {specs}",
            "dnf": f"dnf install -y -q -- {specs}",
            "zypper": f"zypper --non-interactive install -- {specs}",
            "apk": f"apk add -q {specs}",
        }[manager])
        return cmds

    def fix(self, changes, current):
        return type(self).fix_group([(self, changes, current)])
