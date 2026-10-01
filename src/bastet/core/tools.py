"""Which gather tools a host is missing (and would actually use), and how to install them."""

import json
import shlex

from bastet.core.collect import ProbeResult
from bastet.core.hosttypes import HostType
from bastet.core.hwparse import has_bmc, parse_dmidecode, parse_lspci

# Generic tool package -> name per package manager.
PACKAGES = {
    "iproute2": {"apt-get": "iproute2", "pacman": "iproute2", "dnf": "iproute", "zypper": "iproute2", "apk": "iproute2"},
    "util-linux": {"apt-get": "util-linux", "pacman": "util-linux", "dnf": "util-linux", "zypper": "util-linux", "apk": "util-linux"},
    "dmidecode": {"apt-get": "dmidecode", "pacman": "dmidecode", "dnf": "dmidecode", "zypper": "dmidecode", "apk": "dmidecode"},
    "pciutils": {"apt-get": "pciutils", "pacman": "pciutils", "dnf": "pciutils", "zypper": "pciutils", "apk": "pciutils"},
    "smartmontools": {"apt-get": "smartmontools", "pacman": "smartmontools", "dnf": "smartmontools", "zypper": "smartmontools", "apk": "smartmontools"},
    "ipmitool": {"apt-get": "ipmitool", "pacman": "ipmitool", "dnf": "ipmitool", "zypper": "ipmitool", "apk": "ipmitool"},
}
INSTALL = {
    "apt-get": "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends {pkgs}",
    "pacman": "pacman -S --noconfirm --needed {pkgs}",
    "dnf": "dnf install -y {pkgs}",
    "zypper": "zypper --non-interactive install {pkgs}",
    "apk": "apk add {pkgs}",
}
DRIVE_TRANSPORTS = {"sata", "sas", "nvme", "ata", "scsi"}


def _missing(results: dict[str, ProbeResult], name: str) -> bool:
    r = results.get(name)
    return r is not None and r.missing


def _has_drives(results: dict[str, ProbeResult]) -> bool:
    r = results.get("lsblk")
    if r is None or not r.ok:
        return False
    try:
        devices = json.loads(r.output).get("blockdevices", [])
    except (json.JSONDecodeError, AttributeError):
        return False
    return any(isinstance(d, dict) and d.get("type") == "disk" and d.get("tran") in DRIVE_TRANSPORTS for d in devices)


def needed_tools(results: dict[str, ProbeResult], host_type: HostType) -> list[str]:
    """Packages worth installing: the tool was looked for and not found (exit 127), and it's useful here.

    Root-only probes that were denied (exit 126) say nothing about whether the tool exists, so they're ignored.
    """
    need = []
    if _missing(results, "ip_addr"):
        need.append("iproute2")
    if _missing(results, "lscpu") or _missing(results, "lsblk"):
        need.append("util-linux")
    if host_type.physical:
        if _missing(results, "dmidecode"):
            need.append("dmidecode")
        if _missing(results, "lspci"):
            need.append("pciutils")
        if _missing(results, "smart") and _has_drives(results):
            need.append("smartmontools")
        dmi, pci, dev = results.get("dmidecode"), results.get("lspci"), results.get("ipmi_dev")
        records = parse_dmidecode(dmi.output) if dmi is not None and dmi.ok else []
        devices = parse_lspci(pci.output) if pci is not None and pci.ok else []
        if _missing(results, "ipmi") and has_bmc(records, devices, dev.output if dev is not None and dev.ok else None):
            need.append("ipmitool")
    return need


def install_script(manager: str | None, tools: list[str]) -> str | None:
    """Shell script installing `tools` as root (directly, or with passwordless sudo); None for an unknown manager."""
    if manager not in INSTALL:
        return None
    pkgs = " ".join(PACKAGES[t][manager] for t in tools)
    command = INSTALL[manager].format(pkgs=pkgs)
    return (
        "# BASTET-INSTALL\n"
        f'if [ "$(id -u)" = 0 ]; then sh -c {shlex.quote(command)}; else sudo -n sh -c {shlex.quote(command)}; fi\n'
    )
