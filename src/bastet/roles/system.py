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
OPTIONS = r"^\[options\]\s*$"
# role option -> (pacman.conf directive, kind): flag = bare word, value = "Name = v", list = "Name = a b c"
PACMAN_SETTINGS = {
    "root_dir": ("RootDir", "value"), "db_path": ("DBPath", "value"), "cache_dir": ("CacheDir", "list"),
    "hook_dir": ("HookDir", "list"), "gpg_dir": ("GPGDir", "value"), "log_file": ("LogFile", "value"),
    "hold_pkg": ("HoldPkg", "list"), "ignore_pkg": ("IgnorePkg", "list"), "ignore_group": ("IgnoreGroup", "list"),
    "no_upgrade": ("NoUpgrade", "list"), "no_extract": ("NoExtract", "list"), "architecture": ("Architecture", "value"),
    "xfer_command": ("XferCommand", "value"), "parallel_downloads": ("ParallelDownloads", "value"),
    "disable_download_timeout": ("DisableDownloadTimeout", "flag"), "download_user": ("DownloadUser", "value"),
    "disable_sandbox": ("DisableSandbox", "flag"), "clean_method": ("CleanMethod", "list"),
    "sig_level": ("SigLevel", "value"), "local_file_sig_level": ("LocalFileSigLevel", "value"),
    "remote_file_sig_level": ("RemoteFileSigLevel", "value"), "color": ("Color", "flag"),
    "candy": ("ILoveCandy", "flag"), "no_progress_bar": ("NoProgressBar", "flag"),
    "verbose_pkg_lists": ("VerbosePkgLists", "flag"), "check_space": ("CheckSpace", "flag"),
    "use_syslog": ("UseSyslog", "flag"),
}


def _directive(name: str, kind: str, value) -> Line:
    """One [options] line: written in place of the directive (commented or not), else right under [options]."""
    match = rf"^#?\s*{name}\s*(=.*)?$"
    if kind == "flag":
        line = name if value else f"#{name}"
    elif kind == "list":
        line = f"{name} = {' '.join(str(x) for x in value)}" if value else f"#{name} ="
    else:
        line = f"{name} = {value}"
    return Line(path=PACMAN_CONF, line=line, match=match, after=OPTIONS, unique=True)  # the setting means exactly this


def pacman(v: dict, host) -> list[Batch]:
    if host.os_id not in ARCH_LIKE:
        raise BastetError(f"pacman role: {host.name} isn't Arch-based ({host.data.get('os') or 'OS unknown'}); "
                          "aim it at [[arch]]")
    parallel = v.get("parallel_downloads")
    if parallel is not None and parallel < 1:
        raise BastetError("pacman.parallel_downloads must be 1 or more")
    for knob, (_, kind) in PACMAN_SETTINGS.items():
        if kind == "value" and isinstance(v.get(knob), str) and ("\n" in v[knob] or not v[knob].strip()):
            raise BastetError(f"pacman.{knob}: needs a single non-empty line")
    lines = [_directive(name, kind, v[knob]) for knob, (name, kind) in PACMAN_SETTINGS.items() if v.get(knob) is not None]
    return [Batch("pacman", lines)]

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
