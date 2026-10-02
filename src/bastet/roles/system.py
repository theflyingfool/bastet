"""Roles built on the building blocks: base, pacman and proxmox."""

from __future__ import annotations

from bastet.core.errors import BastetError
from bastet.core.osinfo import ARCH_LIKE
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
