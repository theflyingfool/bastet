"""Roles built on the building blocks: base, pacman and proxmox."""

from __future__ import annotations

from bastet.core.errors import BastetError
from bastet.core.osinfo import ARCH_LIKE
from bastet.engine.files import Line
from bastet.engine.packages import Package
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
        _setting("Color", v.get("color")),
        _setting("ILoveCandy", v.get("candy"), after=COLOR),  # Color sits in [options] in every stock pacman.conf
        _setting("ParallelDownloads", None if parallel is None else True, None if parallel is None else str(parallel)),
        _setting("VerbosePkgLists", v.get("verbose_pkg_lists"), after=COLOR),
    ]
    return [Batch("pacman", [i for i in items if i is not None])]
