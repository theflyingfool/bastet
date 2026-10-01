import json
import re
from dataclasses import dataclass, field

from bastet.core.collect import PROBES, ProbeResult
from bastet.core.units import format_size, ram_label

CHASSIS_FROM_SMBIOS = {
    3: "desktop", 4: "desktop", 5: "desktop", 6: "desktop", 7: "desktop", 13: "desktop", 15: "desktop", 16: "desktop",
    8: "laptop", 9: "laptop", 10: "laptop", 14: "laptop", 30: "tablet", 31: "convertible", 32: "convertible",
    17: "server", 23: "server", 28: "server", 29: "server",
}
CONTAINER_VIRTS = {"lxc", "lxc-libvirt", "systemd-nspawn", "docker", "podman", "openvz", "wsl", "proot", "rkt"}
VPS_VENDORS = ("linode", "akamai", "digitalocean", "hetzner", "vultr", "ovh", "amazon ec2", "google", "scaleway")
VIRTUAL_IFACE = re.compile(r"^(lo|veth|tap|fwbr|fwpr|fwln|docker|br-|virbr|cni|flannel|vnet)")
SKIP_DISKS = ("zram", "loop", "ram", "sr", "zd", "nbd", "rbd", "md")


@dataclass
class Extracted:
    facts: dict[str, object] = field(default_factory=dict)
    hints: dict[str, object] = field(default_factory=dict)
    missing_required: list[str] = field(default_factory=list)


def _text(results: dict[str, ProbeResult], name: str) -> str | None:
    r = results.get(name)
    if r is None or not r.ok or not r.output.strip():
        return None
    return r.output.strip()


def _json(results: dict[str, ProbeResult], name: str):
    text = _text(results, name)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _os_release(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _lscpu_fields(entries: list) -> dict[str, str]:
    fields: dict[str, str] = {}
    for entry in entries or []:
        if isinstance(entry, dict):
            fields.setdefault(str(entry.get("field", "")).rstrip(":"), str(entry.get("data", "")))
            fields.update({k: v for k, v in _lscpu_fields(entry.get("children", [])).items() if k not in fields})
    return fields


def _int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def extract(results: dict[str, ProbeResult]) -> Extracted:
    ex = Extracted()
    f = ex.facts
    ex.missing_required = [p.name for p in PROBES if p.required and _text(results, p.name) is None]

    if (text := _text(results, "hostname")) is not None:
        f["hostname"] = text.split()[0].split(".")[0]
    if (text := _text(results, "os_release")) is not None:
        osr = _os_release(text)
        if osr.get("PRETTY_NAME") or osr.get("NAME"):
            f["os"] = osr.get("PRETTY_NAME") or osr.get("NAME")
    if (text := _text(results, "uname")) is not None:
        parts = text.split()
        if len(parts) >= 3:
            f["kernel"], f["arch"] = parts[1], parts[2]

    hn = _json(results, "hostnamectl")
    hn = hn if isinstance(hn, dict) else {}
    chassis = hn.get("Chassis") or None
    if chassis is None and (code := _int(_text(results, "chassis_type"))) is not None:
        chassis = CHASSIS_FROM_SMBIOS.get(code)
    virt_result = results.get("virt")
    virt = virt_result.output.strip() if virt_result is not None and virt_result.output.strip() else None
    if virt in (None, "none") and (container := _text(results, "container")) is not None:
        virt = container.split()[0]
    if virt and virt != "none":
        f["virtualization"] = virt
        if chassis is None or chassis not in ("vm", "container"):
            chassis = "container" if virt in CONTAINER_VIRTS else "vm"
    if chassis:
        f["chassis"] = chassis
    ex.hints["vendor"] = hn.get("HardwareVendor") or _text(results, "sys_vendor")
    ex.hints["product"] = hn.get("HardwareModel") or _text(results, "product_name")
    ex.hints["proxmox"] = _text(results, "pveversion") is not None

    cpu = _json(results, "lscpu")
    if isinstance(cpu, dict):
        fields = _lscpu_fields(cpu.get("lscpu", []))
        if fields.get("Model name"):
            f["cpu"] = fields["Model name"]
        cores, sockets = _int(fields.get("Core(s) per socket")), _int(fields.get("Socket(s)"))
        if cores and sockets:
            f["cpu_cores"] = cores * sockets
        if (threads := _int(fields.get("CPU(s)"))) is not None:
            f["cpu_threads"] = threads

    if (text := _text(results, "meminfo")) is not None:
        m = re.search(r"^MemTotal:\s+(\d+)\s*kB", text, re.M)
        if m:
            f["ram"] = ram_label(int(m.group(1)))

    disks = _json(results, "lsblk")
    if isinstance(disks, dict):
        total = sum(
            int(d.get("size") or 0)
            for d in disks.get("blockdevices", [])
            if isinstance(d, dict) and d.get("type") == "disk" and not str(d.get("name", "")).startswith(SKIP_DISKS)
        )
        if total:
            f["storage"] = format_size(total, binary=chassis in ("vm", "container"))

    addrs = _json(results, "ip_addr")
    if isinstance(addrs, list):
        interfaces = []
        for iface in addrs:
            if not isinstance(iface, dict):
                continue
            name = str(iface.get("ifname", ""))
            if not name or VIRTUAL_IFACE.match(name):
                continue
            entry: dict[str, object] = {"name": name}
            if iface.get("link_type") == "ether" and (iface.get("permaddr") or iface.get("address")):
                entry["mac"] = iface.get("permaddr") or iface["address"]
            found = [
                f"{a['local']}/{a['prefixlen']}"
                for a in iface.get("addr_info", [])
                if isinstance(a, dict)
                and a.get("scope") not in ("link", "host")
                and a.get("local")
                and not a.get("temporary")
                and not a.get("deprecated")
            ]
            if found:
                entry["addresses"] = found
            if len(entry) > 1:
                interfaces.append(entry)
        if interfaces:
            f["interfaces"] = interfaces

    if chassis == "container":
        for key in ("storage", "cpu_cores", "cpu_threads"):
            f.pop(key, None)

    routes = _json(results, "ip_route")
    if isinstance(routes, list):
        for route in routes:
            if isinstance(route, dict) and route.get("dst") == "default" and route.get("gateway"):
                f["gateway"] = route["gateway"]
                break
    return ex


def propose_type(ex: Extracted) -> str | None:
    if ex.hints.get("proxmox"):
        return "proxmox-node"
    chassis = ex.facts.get("chassis")
    if chassis == "container":
        return "lxc"
    if chassis == "vm":
        text = f"{ex.hints.get('vendor') or ''} {ex.hints.get('product') or ''}".lower()
        return "vps" if any(v in text for v in VPS_VENDORS) else "vm"
    if chassis in ("laptop", "convertible", "tablet"):
        return "laptop"
    if chassis in ("server", "desktop"):
        return "server"
    return None
