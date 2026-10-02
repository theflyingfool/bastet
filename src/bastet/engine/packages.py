"""Packages family: packages for apt, pacman, dnf, zypper and apk, and their repositories (spec 9.2).

Every knob either works on a manager or raises Unsupported there; nothing is silently ignored.
"""

import re
import shlex
from dataclasses import dataclass
from typing import ClassVar

from bastet.engine.files import Block, File, Line
from bastet.engine.model import ABSENT, FieldChange, Read, ReadError, Resource, Unsupported

MANAGERS = ("apt-get", "pacman", "dnf", "zypper", "apk")
DETECT = ("for m in apt-get pacman dnf zypper apk; do "
          "command -v $m >/dev/null 2>&1 && { echo $m; exit 0; }; done; exit 127")
NAME = re.compile(r"^[A-Za-z0-9@._+:][A-Za-z0-9@._+:-]*$")
APT = "apt-get -o DPkg::Lock::Timeout=120"
DPKG_DEFAULT = ("--force-confdef", "--force-confold")
REFRESH = {"apt-get": f"{APT} update -q", "dnf": "dnf makecache -q", "zypper": "zypper --non-interactive refresh",
           "apk": "apk update -q"}
UPGRADE = {"dnf": "dnf upgrade -y -q", "zypper": "zypper --non-interactive update", "apk": "apk upgrade -q"}
RPM = ("dnf", "zypper")


def _q(text: str) -> str:
    return shlex.quote(text)


def _query(name: str) -> str:
    n = _q(name)
    return (f"case \"$({DETECT})\" in "
            f"apt-get) dpkg-query -W -f='${{db:Status-Abbrev}}|${{Version}}\\n' -- {n} 2>/dev/null;; "
            f"pacman) pacman -Q -- {n} 2>/dev/null;; "
            f"dnf|zypper) rpm -q --qf '%{{EPOCH}}:%{{VERSION}}-%{{RELEASE}}\\n' -- {n} 2>/dev/null;; "
            f"apk) apk info -e -v {n} 2>/dev/null;; esac; true")


def _installed(manager: str, name: str, output: str) -> list[str]:
    """Installed versions (several for rpm packages like kernels); empty when not installed."""
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    if not lines:
        return []
    first = lines[0]
    if manager == "apt-get":
        status, _, version = first.partition("|")
        # the second letter is the current state: i = installed (ii, hi held, ri/pi marked but still installed)
        return [version.strip()] if len(status) > 1 and status[1] == "i" else []
    if manager == "pacman":
        parts = first.split()
        return [parts[1]] if len(parts) > 1 else []
    if manager in RPM:
        if first.startswith("package ") or "not installed" in first:
            return []
        return [line.removeprefix("(none):") for line in lines]
    if manager == "apk":
        return [first[len(name) + 1:]] if first.startswith(name + "-") else []
    return []


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
    default_release: str | None = None
    allow_change_held: bool = False
    dpkg_options: tuple[str, ...] = DPKG_DEFAULT
    extra_args: tuple[str, ...] = ()
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

    def _check(self, manager: str) -> None:
        if manager != "apt-get":
            for knob, used in (("default_release", self.default_release is not None),
                               ("allow_change_held", self.allow_change_held),
                               ("dpkg_options", tuple(self.dpkg_options) != DPKG_DEFAULT)):
                if used:
                    raise Unsupported(f"{knob} only applies to apt; this host uses {manager}")
        if self.install_recommends is not None and manager in ("pacman", "apk"):
            raise Unsupported(f"{manager} has no recommended packages to turn on or off")
        if self.purge and manager in RPM:
            raise Unsupported(f"{manager} has no purge; removing already drops unchanged config")
        if self.version is not None and manager == "pacman":
            raise Unsupported("pacman can't install a specific version")

    def current(self, results):
        m = results["manager"]
        if not m.ok or not m.output.strip():
            raise Unsupported("no supported package manager (apt, pacman, dnf, zypper, apk)")
        manager = m.output.strip()
        if self.manager is not None and self.manager != manager:
            raise ReadError(f"expected {self.manager}, but this host uses {manager}")
        self._check(manager)
        versions = _installed(manager, self.name, results["query"].output)
        return {"state": "present" if versions else "absent", "version": versions[0] if versions else ABSENT,
                "versions": versions, "manager": manager}

    def _version_ok(self, current) -> bool:
        want = str(self.version)
        for have in current.get("versions") or []:
            if have == want:
                return True
            if current.get("manager") in RPM:
                bare = have.split(":", 1)[-1]
                if bare == want or bare.startswith(want + "-") or have.startswith(want + "-"):
                    return True
        return False

    def compare(self, current):
        changes = []
        if current["state"] != self.state:
            changes.append(FieldChange("state", current["state"], self.state))
        elif self.state == "present" and self.version is not None and not self._version_ok(current):
            changes.append(FieldChange("version", current["version"], self.version))
        return changes

    def group_key(self):
        return (f"package:{self.state}:{self.refresh}:{self.install_recommends}:{self.purge}:{self.full_upgrade}:"
                f"{self.default_release}:{self.allow_change_held}:{self.dpkg_options}:{self.extra_args}")

    def _spec(self, manager: str) -> str:
        if self.version is None or self.state == "absent":
            return self.name
        return f"{self.name}-{self.version}" if manager == "dnf" else f"{self.name}={self.version}"

    @classmethod
    def fix_group(cls, members):
        first, _, current = members[0]
        manager = str(current["manager"])
        specs = " ".join(_q(p._spec(manager)) for p, _, _ in members)
        pinned = any(p.version is not None and p.state == "present" for p, _, _ in members)
        extra = "".join(f" {_q(a)}" for a in first.extra_args)
        apt = f"DEBIAN_FRONTEND=noninteractive {APT}" + "".join(f" -o Dpkg::Options::={o}" for o in first.dpkg_options)
        held = " --allow-change-held-packages" if first.allow_change_held else ""
        if first.state == "absent":
            return [{
                "apt-get": f"{apt} {'purge' if first.purge else 'remove'} -y -q{held}{extra} -- {specs}",
                "pacman": f"pacman {'-Rns' if first.purge else '-R'} --noconfirm{extra} -- {specs}",
                "dnf": f"dnf remove -y -q{extra} -- {specs}",
                "zypper": f"zypper --non-interactive remove{extra} -- {specs}",
                "apk": f"apk del -q{' --purge' if first.purge else ''}{extra} {specs}",
            }[manager]]
        cmds = [REFRESH[manager]] if first.refresh and manager in REFRESH else []
        if first.full_upgrade and manager != "pacman":
            cmds.append(f"{apt} full-upgrade -y -q" if manager == "apt-get" else UPGRADE[manager])
        rec = first.install_recommends
        apt_rec = {True: " --install-recommends", False: " --no-install-recommends", None: ""}[rec]
        dnf_rec = "" if rec is None else f" --setopt=install_weak_deps={rec}"
        zyp_rec = {True: " --recommends", False: " --no-recommends", None: ""}[rec]
        release = f" -t {_q(first.default_release)}" if first.default_release else ""
        cmds.append({
            "apt-get": f"{apt} install -y -q{apt_rec}{release}{held}{' --allow-downgrades' if pinned else ''}{extra} -- {specs}",
            "pacman": f"pacman {'-Syu' if first.full_upgrade else '-S'} --noconfirm --needed{extra} -- {specs}",
            "dnf": f"dnf install -y -q{dnf_rec}{extra} -- {specs}",
            "zypper": f"zypper --non-interactive install{zyp_rec}{' --oldpackage' if pinned else ''}{extra} -- {specs}",
            "apk": f"apk add -q{extra} {specs}",
        }[manager])
        return cmds

    def fix(self, changes, current):
        return type(self).fix_group([(self, changes, current)])


REPO_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
KEY_NAME = re.compile(r"^[A-Za-z0-9@_][A-Za-z0-9@._+-]*$")


@dataclass(frozen=True, kw_only=True)
class Repository(Resource):
    family: ClassVar[str] = "Packages"
    name: str
    uris: tuple[str, ...]
    suites: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    types: tuple[str, ...] = ("deb",)
    architectures: tuple[str, ...] = ()
    key: str | None = None
    key_name: str | None = None
    signed_by: str | None = None
    enabled: bool = True
    trusted: bool | None = None
    options: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        if not REPO_NAME.match(self.name or ""):
            raise ValueError(f"not a repository name: {self.name!r}")
        if not self.uris:
            raise ValueError(f"repository {self.name} needs at least one URI")
        if self.key and self.signed_by:
            raise ValueError(f"repository {self.name}: give key or signed_by, not both")
        if self.key_name is not None and not KEY_NAME.match(self.key_name):
            raise ValueError(f"not a key file name: {self.key_name!r}")

    @property
    def identity(self) -> str:
        return f"repo:{self.name}"

    @property
    def label(self) -> str:
        return f"repository {self.name}"

    def touches(self) -> str | None:
        # pacman.conf and /etc/apk/repositories are shared, so a second repository in a run re-reads first
        return "package-repositories"

    def desired(self):
        return {"uris": self.uris, "suites": self.suites, "components": self.components, "types": self.types,
                "architectures": self.architectures, "key": self.key, "key_name": self.key_name,
                "signed_by": self.signed_by, "enabled": self.enabled, "trusted": self.trusted, "options": self.options}

    def _deb822(self) -> str:
        lines = [f"Types: {' '.join(self.types)}", f"URIs: {' '.join(self.uris)}", f"Suites: {' '.join(self.suites)}"]
        if self.components:
            lines.append(f"Components: {' '.join(self.components)}")
        if self.architectures:
            lines.append(f"Architectures: {' '.join(self.architectures)}")
        if not self.enabled:
            lines.append("Enabled: no")
        if self.trusted is not None:
            lines.append(f"Trusted: {'yes' if self.trusted else 'no'}")
        if self.key:
            lines.append("Signed-By:")
            lines += [f" {line}" if line.strip() else " ." for line in self.key.strip().splitlines()]
        elif self.signed_by:
            lines.append(f"Signed-By: {self.signed_by}")
        lines += [f"{k}: {v}" for k, v in self.options]
        return "\n".join(lines) + "\n"

    def _rpm_key_path(self) -> str:
        return f"/etc/pki/rpm-gpg/RPM-GPG-KEY-bastet-{self.name}"

    def _ini(self, manager: str) -> str:
        if manager == "zypper" and len(self.uris) != 1:
            raise ValueError(f"repository {self.name}: zypper takes exactly one URI")
        baseurl = "\n        ".join(self.uris)
        signed = (bool(self.key or self.signed_by) or self.trusted is False) and self.trusted is not True
        lines = [f"[{self.name}]", f"name={self.name}", f"baseurl={baseurl}", f"enabled={1 if self.enabled else 0}",
                 f"gpgcheck={1 if signed else 0}"]
        if self.key:
            lines.append(f"gpgkey=file://{self._rpm_key_path()}")
        elif self.signed_by:
            lines.append(f"gpgkey={self.signed_by}")
        lines += [f"{k}={v}" for k, v in self.options]
        return "\n".join(lines) + "\n"

    def _pacman(self) -> str:
        lines = [f"[{self.name}]"]
        if self.trusted is True and not any(k == "SigLevel" for k, _ in self.options):
            lines.append("SigLevel = Never")
        lines += [f"Server = {u}" for u in self.uris]
        lines += [f"{k} = {v}" for k, v in self.options]
        if not self.enabled:
            lines = [f"#{line}" for line in lines]
        return "\n".join(lines)

    def _apk_key_path(self) -> str:
        return f"/etc/apk/keys/{self.key_name or self.name + '.rsa.pub'}"

    def parts(self, manager: str) -> list[Resource]:
        common = {"root": self.root}
        if manager == "apt-get":
            return [File(path=f"/etc/apt/sources.list.d/{self.name}.sources", content=self._deb822(), mode="0644", **common)]
        if manager in RPM:
            folder = "/etc/yum.repos.d" if manager == "dnf" else "/etc/zypp/repos.d"
            parts: list[Resource] = [File(path=f"{folder}/{self.name}.repo", content=self._ini(manager), mode="0644", **common)]
            if self.key:
                parts.append(File(path=self._rpm_key_path(), content=self.key, mode="0644", **common))
            return parts
        if manager == "pacman":
            return [Block(path="/etc/pacman.conf", block=self._pacman(), marker=f"bastet repo {self.name}", **common)]
        if manager == "apk":
            parts = [Line(path="/etc/apk/repositories", line=("" if self.enabled else "#") + u,
                          match=r"^#?" + re.escape(u) + r"$", **common) for u in self.uris]
            if self.key:
                parts.append(File(path=self._apk_key_path(), content=self.key, mode="0644", **common))
            return parts
        return []

    def reads(self):
        reads = [Read("manager", DETECT)]
        for m in MANAGERS:
            try:
                parts = self.parts(m)
            except ValueError:
                continue
            for j, part in enumerate(parts):
                reads += [Read(f"{m}.{j}.{r.name}", r.command, root=r.root) for r in part.reads()]
        return tuple(reads)

    def _check(self, manager: str) -> None:
        if manager != "apt-get":
            for knob, used in (("suites", self.suites), ("components", self.components),
                               ("architectures", self.architectures), ("types", tuple(self.types) != ("deb",))):
                if used:
                    raise Unsupported(f"{knob} only applies to apt repositories; this host uses {manager}")
        if manager == "apk":
            for knob, used in (("options", self.options), ("signed_by", self.signed_by),
                               ("trusted", self.trusted is not None)):
                if used:
                    raise Unsupported(f"{knob} isn't supported for apk repositories")
        if manager == "pacman":
            if self.key:
                raise Unsupported("pacman keys are added with pacman-key; not supported yet")
            if self.signed_by:
                raise Unsupported("pacman has no per-repository key file; use options (SigLevel)")
            if self.trusted is False:
                raise Unsupported("pacman: set signature checking through options (SigLevel)")
        if manager == "zypper" and len(self.uris) != 1:
            raise Unsupported("zypper takes exactly one URI per repository")

    def current(self, results):
        m = results["manager"]
        if not m.ok or not m.output.strip():
            raise Unsupported("no supported package manager (apt, pacman, dnf, zypper, apk)")
        manager = m.output.strip()
        self._check(manager)
        parts = self.parts(manager)
        states = [p.current({r.name: results[f"{manager}.{j}.{r.name}"] for r in p.reads()}) for j, p in enumerate(parts)]
        return {"manager": manager, "parts": states}

    def _threaded(self, current):
        """Parts editing one shared file see the earlier parts' edits, so they don't overwrite each other."""
        pairs = []
        latest: dict[str, str] = {}
        for part, state in zip(self.parts(str(current["manager"])), current["parts"]):
            path = getattr(part, "path", None)
            edits = hasattr(part, "wanted")
            if edits and path in latest:
                state = {**state, "content": latest[path]}
            if edits:
                latest[path] = part.wanted(state["content"])
            pairs.append((part, state))
        return pairs

    def compare(self, current):
        changes = []
        for part, state in self._threaded(current):
            where = getattr(part, "path", part.label)
            changes += [FieldChange(f"{where}:{c.field}", c.before, c.after) for c in part.compare(state)]
        return changes

    def fix(self, changes, current):
        cmds: list[str] = []
        key_changed = False
        for part, state in self._threaded(current):
            own = part.compare(state)
            if own:
                cmds += part.fix(own, state)
                key_changed = key_changed or getattr(part, "path", "") == self._rpm_key_path()
        if current["manager"] == "zypper" and key_changed:
            cmds.append(f"rpm --import {self._rpm_key_path()}")
        return cmds

    def diff_text(self, current):
        texts = [part.diff_text(state) for part, state in self._threaded(current) if part.compare(state)]
        return "\n".join(t for t in texts if t) or None


def _per_manager(cases: dict[str, str]) -> str:
    body = " ".join(f"{m}) {cmd};;" for m, cmd in cases.items())
    return f"case \"$({DETECT})\" in {body} esac"


PENDING = _per_manager({
    "apt-get": ("apt-get -o DPkg::Lock::Timeout=120 update -q >/dev/null 2>&1 || echo '@@RC refresh-failed'; "
                "apt list --upgradable 2>/dev/null; echo @@HELD@@; apt-mark showhold 2>/dev/null"),
    "pacman": "command -v checkupdates >/dev/null || exit 127; checkupdates 2>/dev/null; echo \"@@RC $?\"",
    "dnf": "dnf check-update -q --refresh 2>/dev/null; echo \"@@RC $?\"",
    "zypper": "zypper --non-interactive --quiet refresh >/dev/null 2>&1; zypper --non-interactive --quiet list-updates 2>/dev/null; true",
    "apk": "apk update -q >/dev/null 2>&1; apk version -l '<' 2>/dev/null; true",
})
SECURITY = _per_manager({
    "dnf": "dnf updateinfo list --security -q 2>/dev/null; true",
    "zypper": "zypper --non-interactive --quiet list-patches --category security 2>/dev/null; true",
})
_NEVRA = re.compile(r"^(.+)-[^-]+-[^-]+$")
_APK_NAME = re.compile(r"^(.+?)-\d[^-]*-r\d+$")


def _manager(results) -> str:
    m = results["manager"]
    if not m.ok or not m.output.strip():
        raise Unsupported("no supported package manager (apt, pacman, dnf, zypper, apk)")
    return m.output.strip()


_RC = re.compile(r"^@@RC (\S+)$", re.M)
CHECK_OK = {"pacman": ("0", "2"), "dnf": ("0", "100")}


def _check_rc(manager: str, text: str) -> None:
    """Fail loudly when the update check itself failed, instead of reading 'nothing pending'."""
    for rc in _RC.findall(text):
        if rc == "refresh-failed":
            raise ReadError("couldn't refresh the package lists (apt-get update failed); is the network or mirror up?")
        if manager in CHECK_OK and rc not in CHECK_OK[manager]:
            raise ReadError(f"couldn't check for updates ({manager} exit {rc}); is the network or mirror up?")


def _pending(manager: str, text: str) -> tuple[list[str], list[str]]:
    names, security = [], []
    text, _, held_text = text.partition("@@HELD@@")
    held = {line.strip() for line in held_text.splitlines() if line.strip()}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("@@") or "[ignored]" in line:
            continue
        if manager == "apt-get":
            if "/" not in line or line.startswith("Listing"):
                continue
            name, rest = line.split("/", 1)
            names.append(name)
            if "-security" in rest.split()[0]:
                security.append(name)
        elif manager == "pacman":
            names.append(line.split()[0])
        elif manager == "dnf":
            first = line.split()[0]
            if "." in first and len(line.split()) >= 3 and not line.startswith(("Last metadata", "Obsoleting")):
                names.append(first.rsplit(".", 1)[0])
        elif manager == "zypper":
            cols = [c.strip() for c in line.split("|")]
            if len(cols) >= 3 and cols[0] == "v":
                names.append(cols[2])
        elif manager == "apk":
            m = _APK_NAME.match(line.split()[0])
            if m:
                names.append(m.group(1))
    return [n for n in names if n not in held], [n for n in security if n not in held]


def _dnf_security(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            m = _NEVRA.match(parts[-1].rsplit(".", 1)[0])
            if m:
                out.append(m.group(1))
    return out


@dataclass(frozen=True, kw_only=True)
class Updates(Resource):
    family: ClassVar[str] = "Packages"
    policy: str = "manual"
    exclude: tuple[str, ...] = ()
    apply_updates: bool = False
    dpkg_options: tuple[str, ...] = DPKG_DEFAULT
    extra_args: tuple[str, ...] = ()
    rest: bool = False  # the non-security remainder under a security policy, reported only

    def __post_init__(self):
        if self.policy not in ("manual", "auto", "security"):
            raise ValueError(f"updates policy must be manual, auto or security, not {self.policy!r}")

    @property
    def identity(self) -> str:
        return "updates:rest" if self.rest else "updates"

    @property
    def label(self) -> str:
        return "updates (non-security)" if self.rest else "updates"

    def report_only(self) -> bool:
        return self.policy == "manual" and not self.apply_updates

    def desired(self):
        return {"policy": self.policy, "exclude": self.exclude}

    def reads(self):
        return (Read("manager", DETECT), Read("pending", PENDING, root=True), Read("security", SECURITY, root=True))

    def current(self, results):
        manager = _manager(results)
        if self.policy == "security" and manager in ("pacman", "apk"):
            raise Unsupported(f"{manager} has no separate security updates; use updates: auto or manual")
        if manager == "pacman" and results["pending"].missing:
            raise Unsupported("checking for updates on Arch needs checkupdates (install pacman-contrib)")
        if self.policy == "security" and manager == "zypper" and self.exclude:
            raise Unsupported("zypper's security patches can't exclude packages; drop updates_exclude or use auto")
        _check_rc(manager, results["pending"].output)
        names, security = _pending(manager, results["pending"].output)
        if manager in ("dnf",):
            security = _dnf_security(results["security"].output)
        elif manager == "zypper":
            security = ["(patches)"] if any("|" in line and "security" in line for line in results["security"].output.splitlines()) else []
        keep = lambda xs: tuple(sorted({x for x in xs if x not in self.exclude}))  # noqa: E731
        return {"manager": manager, "pending": keep(names), "security": keep(security)}

    def _target(self, current) -> tuple[str, ...]:
        if self.rest:
            return tuple(n for n in current["pending"] if n not in current["security"])
        return current["security"] if self.policy == "security" else current["pending"]

    def compare(self, current):
        target = self._target(current)
        return [FieldChange("updates", f"{len(target)} pending", "up to date")] if target else []

    def diff_text(self, current):
        names = list(current["pending"])
        return "\n".join(names[:40] + ([f"… {len(names) - 40} more"] if len(names) > 40 else [])) or None

    def fix(self, changes, current):
        return [c + "".join(f" {_q(a)}" for a in self.extra_args) for c in self._commands(current)]

    def _commands(self, current):
        manager = current["manager"]
        names = " ".join(_q(n) for n in self._target(current))
        apt = f"DEBIAN_FRONTEND=noninteractive {APT}" + "".join(f" -o Dpkg::Options::={o}" for o in self.dpkg_options)
        security = self.policy == "security"
        if manager == "apt-get":
            if security or self.exclude:
                return [f"{apt} install --only-upgrade -y -q -- {names}"]
            return [f"{apt} full-upgrade -y -q"]
        if manager == "pacman":
            return ["pacman -Syu --noconfirm" + (f" --ignore {','.join(self.exclude)}" if self.exclude else "")]
        if manager == "dnf":
            return ["dnf upgrade -y -q" + (" --security" if security else "") + "".join(f" --exclude={_q(x)}" for x in self.exclude)]
        if manager == "zypper":
            if security:
                return ["zypper --non-interactive patch --category security"]
            return [f"zypper --non-interactive update -- {names}" if self.exclude else "zypper --non-interactive update"]
        return [f"apk upgrade -q {names}" if self.exclude else "apk upgrade -q"]


REBOOT = ("[ -e /run/reboot-required ] && echo debian; "
          "if command -v needs-restarting >/dev/null 2>&1; then needs-restarting -r >/dev/null 2>&1 || echo dnf; fi; "
          "if [ -d /usr/lib/modules ] && [ -n \"$(ls /usr/lib/modules 2>/dev/null)\" ] && "
          "[ ! -d \"/usr/lib/modules/$(uname -r)\" ]; then echo kernel; fi; true")


@dataclass(frozen=True, kw_only=True)
class Reboot(Resource):
    family: ClassVar[str] = "System"
    root: bool = False
    policy: str = "ask"  # what apply does when a reboot is needed: never, ask, auto (cli.reboot)
    timeout: int = 600

    def __post_init__(self):
        if self.policy not in ("never", "ask", "auto"):
            raise ValueError(f"reboot policy must be never, ask or auto, not {self.policy!r}")

    @property
    def identity(self) -> str:
        return "reboot"

    @property
    def label(self) -> str:
        return "reboot"

    def report_only(self) -> bool:
        return True

    def desired(self):
        return {"policy": self.policy}

    def reads(self):
        return (Read("reboot", REBOOT),)

    def current(self, results):
        why = sorted({w for w in results["reboot"].output.split() if w})
        return {"needed": bool(why), "why": ", ".join(why)}

    def compare(self, current):
        return [FieldChange("reboot", f"needed ({current['why']})", "not needed")] if current["needed"] else []

    def fix(self, changes, current):
        return []


EXPLICIT = _per_manager({
    "pacman": "pacman -Qqe",
    "apt-get": "apt-mark showmanual",
    "dnf": "dnf repoquery --userinstalled -q --qf '%{name}\\n'",
    "apk": "cat /etc/apk/world",
    "zypper": "exit 3",
})
SYSTEM = _per_manager({
    "pacman": "echo base; echo base-devel",
    "apt-get": "dpkg-query -W -f='${Package} ${Priority}\\n'",
    "dnf": "true",
    "apk": "echo alpine-base",
    "zypper": "true",
})
_WORLD = re.compile(r"[<>=~].*$")


@dataclass(frozen=True, kw_only=True)
class Unaccounted(Resource):
    """Packages installed on purpose that no role, system set or allowed list accounts for. Reported, never removed."""

    family: ClassVar[str] = "Packages"
    tracked: tuple[str, ...] = ()
    allowed: tuple[str, ...] = ()
    root: bool = False

    @property
    def identity(self) -> str:
        return "unaccounted"

    @property
    def label(self) -> str:
        return "unaccounted packages"

    def report_only(self) -> bool:
        return True

    def desired(self):
        return {"tracked": self.tracked, "allowed": self.allowed}

    def reads(self):
        return (Read("manager", DETECT), Read("explicit", EXPLICIT), Read("system", SYSTEM))

    def current(self, results):
        manager = _manager(results)
        if manager == "zypper":
            raise Unsupported("zypper doesn't record which packages were installed on purpose")
        explicit = {_WORLD.sub("", line.strip()) for line in results["explicit"].output.splitlines() if line.strip()}
        if manager == "apt-get":
            system = {p.split()[0] for p in results["system"].output.splitlines()
                      if len(p.split()) > 1 and p.split()[1] in ("required", "important", "standard")}
        else:
            system = {line.strip() for line in results["system"].output.splitlines() if line.strip()}
        left = explicit - system - set(self.tracked) - set(self.allowed)
        return {"unaccounted": tuple(sorted(left))}

    def compare(self, current):
        n = len(current["unaccounted"])
        return [FieldChange("unaccounted", f"{n} packages", "none")] if n else []

    def diff_text(self, current):
        names = list(current["unaccounted"])
        return "\n".join(names[:60] + ([f"… {len(names) - 60} more"] if len(names) > 60 else [])) or None

    def fix(self, changes, current):
        return []
