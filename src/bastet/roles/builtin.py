"""The first roles: systemd, packages, users and files, each turning its merged values into engine batches."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.core.osinfo import os_id
from bastet.engine.command import Command
from bastet.engine.files import Block, Directory, File, Line, Symlink
from bastet.engine.model import Trigger
from bastet.engine.packages import Package, Reboot, Repository, Unaccounted, Updates
from bastet.engine.run import Batch
from bastet.engine.systemd import Hostname, Locale, TimeSettings, Unit, drop_in, reload, restart
from bastet.engine.templates import render_template
from bastet.engine.users import AuthorizedKey, Group, User, sudoer
from bastet.roles.resolve import Applied

ORDER = ("packages", "users", "files", "systemd")
DEBIAN_LIKE = ("debian", "ubuntu", "proxmox", "raspbian", "mint")


@dataclass
class HostInfo:
    name: str
    type: str
    data: dict
    root: Path
    lab: dict = field(default_factory=dict)
    apply_updates: bool = False
    physical: bool = False

    @property
    def os_id(self) -> str | None:
        return os_id(self.data)

    @property
    def debian_like(self) -> bool:
        return any(w in str(self.data.get("os", "")).lower() for w in DEBIAN_LIKE)

    @property
    def container(self) -> bool:
        return self.type == "lxc"


def _kw(values: dict) -> dict:
    """Role values as resource keywords: lists become tuples (resources are frozen)."""
    return {k: tuple(v) if isinstance(v, list) else v for k, v in values.items()}


def _systemd(v: dict, host: HostInfo) -> list[Batch]:
    res = []
    service, ntp = v["ntp_service"], v["ntp"]
    servers, fallback = tuple(v.get("ntp_servers") or ()), tuple(v.get("fallback_ntp_servers") or ())
    if service == "keep" and (servers or fallback):
        raise BastetError("systemd.ntp_servers needs ntp_service: timesyncd or chrony")
    if service == "chrony" and fallback:
        raise BastetError("systemd.fallback_ntp_servers only applies to timesyncd")
    if (servers or fallback) and ntp is not True:
        raise BastetError("systemd.ntp_servers needs ntp: true (otherwise the servers would never be used)")
    if not host.container and service != "keep" and ntp is not None:
        if service == "timesyncd":
            unit, other = "systemd-timesyncd.service", "chronyd.service"
            if ntp and host.debian_like:
                res.append(Package(name="systemd-timesyncd"))
            if ntp and (servers or fallback):
                body = "[Time]\n" + (f"NTP={' '.join(servers)}\n" if servers else "") + \
                    (f"FallbackNTP={' '.join(fallback)}\n" if fallback else "")
                res.append(File(path="/etc/systemd/timesyncd.conf.d/bastet.conf", content=body, mode="0644",
                                on_change=(restart(unit),)))
        else:
            unit, other = "chronyd.service", "systemd-timesyncd.service"
            if ntp:
                res.append(Package(name="chrony"))
            if ntp and servers:
                lines = "".join(f"server {s} iburst\n" for s in servers)
                if host.debian_like:
                    res.append(File(path="/etc/chrony/sources.d/bastet.sources", content=lines, mode="0644",
                                    on_change=(Trigger("reload chrony sources", "chronyc reload sources"),)))
                else:
                    res.append(Block(path="/etc/chrony.conf", block=lines.rstrip("\n"), marker="bastet servers",
                                     on_change=(restart(unit),)))
        if ntp:
            res.append(Unit(name=other, enabled=False, state="down"))
        res.append(Unit(name=unit, enabled=bool(ntp), state="up" if ntp else "down"))
    time = TimeSettings(timezone=v.get("timezone"), ntp=ntp if service == "keep" and not host.container else None,
                        rtc_local=None if host.container else v.get("rtc_local"))
    if time.timezone is not None or time.ntp is not None or time.rtc_local is not None:
        res.append(time)
    if v.get("manage_hostname") and not host.container:
        res.append(Hostname(name=str(host.data.get("hostname") or host.name)))
    if v.get("locale") or v.get("keymap"):
        res.append(Locale(lang=v.get("locale"), keymap=v.get("keymap")))
    for unit_name, want in (v.get("services") or {}).items():
        res.append(Unit(name=unit_name, enabled=want.get("enabled"), state=want.get("state")))
    for d in v.get("dropins") or []:
        missing = [k for k in ("unit", "name", "content") if k not in d]
        if missing:
            raise BastetError(f"systemd.dropins: each drop-in needs {', '.join(missing)}")
        res.append(drop_in(d["unit"], d["name"], d["content"], restart_unit=d.get("restart", True)))
    return [Batch("systemd", res)]


ROLE_KNOBS = ("refresh", "install_recommends", "full_upgrade", "default_release", "allow_change_held", "dpkg_options",
              "extra_args")


def _packages(v: dict, host: HostInfo) -> list[Batch]:
    base = {k: v[k] for k in ROLE_KNOBS if v.get(k) is not None}
    installs = v.get("install") or []
    if v.get("full_upgrade") and not installs:
        raise BastetError("packages.full_upgrade only applies while installing packages; add `install:` "
                          "(keeping a whole system upgraded on its own isn't a role option yet)")
    names = {p["name"] for p in installs}
    repos = []
    for r in v.get("repositories") or []:
        r = dict(r)
        r["options"] = tuple((k, val) for k, val in (r.get("options") or {}).items())
        repos.append(Repository(**_kw(r)))
    removes = []
    for p in v.get("remove") or []:
        if p["name"] in names:
            raise BastetError(f"packages: {p['name']} is in both install and remove")
        keep = {k: base[k] for k in ("extra_args", "dpkg_options", "allow_change_held") if k in base}  # per-entry knobs override
        removes.append(Package(**_kw({**keep, "state": "absent", **p})))
    policy = v.get("updates") or "manual"
    common = {"exclude": tuple(v.get("updates_exclude") or ()), "extra_args": tuple(v.get("extra_args") or ()),
              **({"dpkg_options": tuple(v["dpkg_options"])} if v.get("dpkg_options") else {})}
    if policy == "security" and host.apply_updates:
        extras = [Updates(policy="auto", **common)]
    elif policy == "security":
        extras = [Updates(policy="security", **common), Updates(policy="manual", rest=True, **common)]
    else:
        extras = [Updates(policy=policy, apply_updates=host.apply_updates, **common)]
    if not host.container:
        extras.append(Reboot(policy=v.get("reboot") or "ask", timeout=v.get("reboot_timeout") or 600))
    if v.get("report_unaccounted", True):
        tracked = tuple(p["name"] for p in installs) + tuple(str(t) for t in host.data.get("bastet_tools") or ())
        extras.append(Unaccounted(tracked=tracked, allowed=tuple(v.get("allowed") or ())))
    return [Batch("packages", [*repos, *removes, *[Package(**_kw({**base, **p})) for p in installs], *extras])]


BASTET_USER = "bastet"
NO_LOGIN = ("/usr/sbin/nologin", "/sbin/nologin", "/bin/false", "/usr/bin/false")


def _guard_bastet(v: dict) -> None:
    """Refuse role values that would lock Bastet out of the host it manages (spec 12)."""
    def stop(what: str):
        raise BastetError(f"users: {what} would lock Bastet out of this host; the bastet account is managed by Bastet itself")
    me = (v.get("users") or {}).get(BASTET_USER) or {}
    if me.get("expires") not in (None, "never"):
        stop("an expiry date on the bastet user")
    if me.get("locked"):
        stop("locking the bastet user")
    if me.get("shell") in NO_LOGIN:
        stop("a no-login shell for the bastet user")
    if any(k.get("state") == "absent" for k in me.get("keys") or []):
        stop("removing a key from the bastet user")
    if me.get("sudo") or BASTET_USER in (v.get("sudoers") or {}):
        stop("a sudoers rule for bastet (/etc/sudoers.d/bastet)")


def _users(v: dict, host: HostInfo) -> list[Batch]:
    _guard_bastet(v)
    groups = [Group(name=name, **_kw(g)) for name, g in (v.get("groups") or {}).items()]
    users, keys, sudo = [], [], []
    for name, u in (v.get("users") or {}).items():
        u = dict(u)
        keys += [AuthorizedKey(user=name, **_kw(k)) for k in u.pop("keys", None) or []]
        rule = u.pop("sudo", None)
        if rule:
            sudo.append(sudoer(name, user=name, **_kw(rule)))
        users.append(User(name=name, **_kw(u)))
    sudo += [sudoer(name, **_kw(s)) for name, s in (v.get("sudoers") or {}).items()]
    return [Batch("users", [*groups, *users, *keys, *sudo])]


def _triggers(d: dict) -> dict:
    """Pop restart/reload unit lists from a role entry and turn them into on-change triggers."""
    units = [restart(u) for u in d.pop("restart", None) or []] + [reload(u) for u in d.pop("reload", None) or []]
    return {"on_change": tuple(units)} if units else {}


def _absolute(path: str, where: str) -> str:
    if not path.startswith("/"):
        raise BastetError(f"{where}: {path!r} must be an absolute path")
    return path


def _files(v: dict, host: HostInfo) -> list[Batch]:
    res = [Directory(path=_absolute(p, "files.directories"), **d) for p, d in (v.get("directories") or {}).items()]
    for path, f in (v.get("files") or {}).items():
        _absolute(path, "files.files")
        f = dict(f)
        template = f.pop("template", None)
        if template is not None:
            if "content" in f:
                raise BastetError(f"files.files.{path}: give content or template, not both")
            f["content"] = render_template(host.root, template, {"host": host.data, "name": host.name, "lab": host.lab})
        if "content" not in f:
            raise BastetError(f"files.files.{path}: needs content or template")
        res.append(File(path=path, **_triggers(f), **f))
    res += [Symlink(path=_absolute(p, "files.links"), target=t) for p, t in (v.get("links") or {}).items()]
    res += [Block(**_triggers(dict(b)), **{k: x for k, x in b.items() if k not in ("restart", "reload")})
            for b in v.get("blocks") or []]
    res += [Line(**_triggers(dict(line)), **{k: x for k, x in line.items() if k not in ("restart", "reload")})
            for line in v.get("lines") or []]
    res += [Command(**c) for c in v.get("commands") or []]
    return [Batch("files", res)]


BUILDERS = {"systemd": _systemd, "packages": _packages, "users": _users, "files": _files}


def batches_for(applied: list[Applied], host: HostInfo) -> list[Batch]:
    batches: list[Batch] = []
    for a in sorted(applied, key=lambda a: ORDER.index(a.role.name) if a.role.name in ORDER else len(ORDER)):
        builder = BUILDERS.get(a.role.name)
        if builder is None:
            raise BastetError(f"role {a.role.name} has no implementation yet")
        try:
            batches += builder(a.values, host)
        except (TypeError, ValueError, KeyError) as exc:
            raise BastetError(f"{a.role.name}: {exc}") from None
    # Everything Bastet installs is accounted for, whichever role installs it.
    present = sorted({r.name for b in batches for r in b.resources if isinstance(r, Package) and r.state == "present"})
    for b in batches:
        b.resources = [replace(r, tracked=tuple(dict.fromkeys((*r.tracked, *present)))) if isinstance(r, Unaccounted) else r
                       for r in b.resources]
    return batches
