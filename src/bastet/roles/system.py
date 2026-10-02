"""Roles built on the building blocks: base, pacman and proxmox."""

from __future__ import annotations

import re

from bastet.core.errors import BastetError
from bastet.core.osinfo import ARCH_LIKE
from bastet.engine.command import Command
from bastet.engine.files import Line
from bastet.engine.packages import Package, Repository, StraySources
from bastet.engine.run import Batch

MICROCODE = {("arch", "intel"): "intel-ucode", ("arch", "amd"): "amd-ucode",
             ("debian", "intel"): "intel-microcode", ("debian", "amd"): "amd64-microcode"}


def _family(host) -> str | None:
    if host.os_id in ARCH_LIKE:
        return "arch"
    if host.debian_like:
        return "debian"
    return None


def _vendor(cpu: object) -> str | None:
    text = str(cpu or "").lower()
    return "intel" if "intel" in text else "amd" if "amd" in text else None


def base(v: dict, host) -> list[Batch]:
    names = list(dict.fromkeys([*(v.get("tools") or []), *(v.get("extra_tools") or [])]))
    res = [Package(name=n) for n in names]
    if v.get("microcode") == "auto" and host.physical:
        if not host.data.get("cpu"):
            raise BastetError("base.microcode: auto needs the CPU vendor; run bastet gather on this host first")
        package = MICROCODE.get((_family(host), _vendor(host.data.get("cpu"))))
        if package is None:
            raise BastetError(f"base.microcode: no microcode package known for {host.data.get('os')} "
                              f"on {host.data.get('cpu')}; set microcode: never")
        res.append(Package(name=package))
    return [Batch("base", res)]


PACMAN_CONF = "/etc/pacman.conf"
COLOR = r"^#?\s*Color\s*$"
OPTIONS = r"^\[options\]\s*$"
IN_OPTIONS = rf"{COLOR}|{OPTIONS}"  # after Color when it's there, else right under [options]


def _setting(name: str, on: bool | None, value: str | None = None, after: str | None = None) -> Line | None:
    """One [options] setting: on writes it, off comments it out, None leaves pacman.conf alone."""
    if on is None:
        return None
    text = f"{name} = {value}" if value is not None else name
    match = rf"^#?\s*{name}(\s*=.*)?\s*$" if value is not None else rf"^#?\s*{name}\s*$"
    return Line(path=PACMAN_CONF, line=text if on else f"#{text}", match=match, after=after)


def pacman(v: dict, host) -> list[Batch]:
    if host.os_id not in ARCH_LIKE:
        raise BastetError(f"pacman role: {host.name} isn't Arch-based ({host.data.get('os') or 'OS unknown'}); "
                          "aim it at [[arch]]")
    parallel = v.get("parallel_downloads")
    if parallel is not None and parallel < 1:
        raise BastetError("pacman.parallel_downloads must be 1 or more")
    items = [
        _setting("Color", v.get("color"), after=OPTIONS),
        _setting("ILoveCandy", v.get("candy"), after=IN_OPTIONS),
        _setting("ParallelDownloads", None if parallel is None else True, None if parallel is None else str(parallel),
                 after=IN_OPTIONS),
        _setting("VerbosePkgLists", v.get("verbose_pkg_lists"), after=IN_OPTIONS),
    ]
    return [Batch("pacman", [i for i in items if i is not None])]


DEBIAN_KEY = "/usr/share/keyrings/debian-archive-keyring.gpg"
PVE_KEY = "/usr/share/keyrings/proxmox-archive-keyring.gpg"
PVE_JS = "/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js"
NAG = "res.data.status.toLowerCase() !== 'active'"
NAG_SED = NAG.replace(".", "\\.")  # sed basic regex: ( ) are literal; only the dots need escaping


def _suite(v: dict, host) -> str:
    if v.get("suite"):
        return str(v["suite"])
    m = re.search(r"\(([a-z]+)\)", str(host.data.get("os") or ""))
    if not m:
        raise BastetError(f"proxmox.suite: can't tell the Debian codename from '{host.data.get('os')}'; "
                          "set suite (e.g. trixie) or run bastet gather")
    return m.group(1)


def proxmox(v: dict, host) -> list[Batch]:
    s = _suite(v, host)
    comps = tuple(v.get("debian_components") or ())
    which = v.get("repository") or "no-subscription"
    res: list = [
        Repository(name="debian", uris=(v["debian_mirror"],), suites=(s, f"{s}-updates"), components=comps,
                   signed_by=DEBIAN_KEY),
        Repository(name="debian-security", uris=("http://security.debian.org/debian-security",),
                   suites=(f"{s}-security",), components=comps, signed_by=DEBIAN_KEY),
        Repository(name="proxmox", uris=("http://download.proxmox.com/debian/pve",), suites=(s,),
                   components=("pvetest" if which == "test" else "pve-no-subscription",), signed_by=PVE_KEY,
                   enabled=which != "enterprise"),
        Repository(name="pve-enterprise", uris=("https://enterprise.proxmox.com/debian/pve",), suites=(s,),
                   components=("pve-enterprise",), signed_by=PVE_KEY, enabled=which == "enterprise"),
        _ceph(v, s),
        StraySources(keep=("debian", "debian-security", "proxmox", "pve-enterprise", "ceph"),
                     remove=v.get("stray_sources") == "remove"),
    ]
    res += [Package(name=t) for t in v.get("tools") or []]
    if v.get("subscription_notice") == "remove":  # last: a failure here mustn't stop the tools
        res.append(Command(
            name="proxmox subscription notice",
            unless=f"grep -q BASTET-NOTICE-OFF {PVE_JS}",
            run=(f"grep -qF \"{NAG}\" {PVE_JS} || {{ echo 'pattern not found; Proxmox changed proxmoxlib.js, or another "
                 f"tool already patched it (apt reinstall proxmox-widget-toolkit, then apply again)' >&2; exit 1; }}; "
                 f"sed -i.bastet-bak \"s/{NAG_SED}/false \\/* BASTET-NOTICE-OFF *\\//g\" {PVE_JS} && "
                 "systemctl restart pveproxy.service"),
        ))
    return [Batch("proxmox", res)]


def _ceph(v: dict, suite: str) -> Repository:
    """ceph.sources: disabled unless asked for, so an enterprise Ceph entry can't break apt on a no-subscription node."""
    which, release = v.get("ceph") or "none", v.get("ceph_release") or "squid"
    if which == "no-subscription":
        return Repository(name="ceph", uris=(f"http://download.proxmox.com/debian/ceph-{release}",), suites=(suite,),
                          components=("no-subscription",), signed_by=PVE_KEY)
    return Repository(name="ceph", uris=(f"https://enterprise.proxmox.com/debian/ceph-{release}",), suites=(suite,),
                      components=("enterprise",), signed_by=PVE_KEY, enabled=which == "enterprise")
