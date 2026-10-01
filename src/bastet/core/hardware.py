"""Turn hardware probe output into proposed hardware files, and plan changes against the inventory."""

import json
import re
from dataclasses import dataclass, field

from bastet.core.collect import ProbeResult
from bastet.core.facts import SKIP_DISKS, Extracted
from bastet.core.hwparse import (
    base_device, clean, machine_from_dmi, parse_disk_ids, parse_dmidecode, parse_ipmi_lan, parse_lspci,
    parse_net_sysfs, parse_pve_guests, parse_smart, parse_zpool, slots_in_use, speed_label, strip_ids,
)
from bastet.core.links import make_link
from bastet.core.units import format_size

DRIVE_TRANSPORTS = {"sata", "sas", "nvme", "ata", "scsi"}
CARD_CLASSES = {"0300": "gpu", "0302": "gpu", "0380": "gpu", "0100": "hba", "0104": "hba", "0107": "hba", "0200": "nic"}
MACHINE_CATEGORY = {"laptop": "laptop", "convertible": "laptop", "tablet": "laptop", "server": "server", "desktop": "desktop"}
MACHINE_CATEGORIES = set(MACHINE_CATEGORY.values()) | {"machine"}
_UNSAFE = re.compile(r"[^A-Za-z0-9 ._-]+")


@dataclass
class Observed:
    key: str
    name: str
    data: dict


@dataclass
class HardwareView:
    items: list[Observed] = field(default_factory=list)
    pools: list[dict] = field(default_factory=list)
    guests: list[dict] = field(default_factory=list)
    complete: dict[str, bool] = field(default_factory=lambda: {"drives": False, "cards": False})
    skipped_root: bool = False


def file_name(*parts: str | None) -> str:
    text = " ".join(_UNSAFE.sub(" ", p) for p in parts if p)
    return re.sub(r"\s+", " ", text).strip()


def _text(results: dict[str, ProbeResult], name: str) -> str | None:
    r = results.get(name)
    return r.output if r is not None and r.ok and r.output.strip() else None


def _make_model(make: str | None, model: str | None) -> str | None:
    if make and model and not model.lower().startswith(make.lower()):
        return f"{make} {model}"
    return model or make


def observe_hardware(host: str, results: dict[str, ProbeResult], ex: Extracted) -> HardwareView:
    view = HardwareView()
    link = make_link(host)
    view.skipped_root = (_text(results, "privilege") or "").strip() == "none"

    dmi = parse_dmidecode(_text(results, "dmidecode") or "")
    machine = machine_from_dmi(dmi) if dmi else {}
    make = machine.get("make") or clean(ex.hints.get("vendor"))
    model = machine.get("model") or clean(ex.hints.get("product"))
    serial = machine.get("serial")

    macs = {i["name"]: i.get("mac") for i in ex.facts.get("interfaces", []) if isinstance(i, dict)}
    addr_text = _text(results, "ip_addr")
    if addr_text:
        try:
            for iface in json.loads(addr_text):
                if isinstance(iface, dict) and iface.get("ifname"):
                    macs.setdefault(iface["ifname"], iface.get("permaddr") or iface.get("address"))
        except json.JSONDecodeError:
            pass
    net = parse_net_sysfs(_text(results, "net_sysfs") or "")
    slots = slots_in_use(dmi)
    ports_by_bus: dict[str, list[dict]] = {}
    onboard: list[dict] = []
    for ifname, info in sorted(net.items()):
        if not info["pci"]:
            continue
        port = {"name": ifname}
        if macs.get(ifname):
            port["mac"] = macs[ifname]
        if speed_label(info["speed"]):
            port["speed"] = speed_label(info["speed"])
        bus = info["pci"].rsplit(".", 1)[0]
        ports_by_bus.setdefault(bus, []).append(port)

    pci = parse_lspci(_text(results, "lspci") or "")
    cards: dict[str, list[dict]] = {}
    for dev in pci:
        bus = dev.get("Slot", "").rsplit(".", 1)[0]
        if dev["class_code"] in CARD_CLASSES and bus in slots:
            cards.setdefault(bus, []).append(dev)
        elif dev["class_code"] == "0200":
            onboard.extend(ports_by_bus.get(bus, []))
    view.complete["cards"] = bool(dmi) and bool(pci)

    data: dict[str, object] = {"bastet": "hardware", "category": MACHINE_CATEGORY.get(str(ex.facts.get("chassis")), "machine")}
    for key, value in (("make", make), ("model", model), ("serial", serial)):
        if value:
            data[key] = value
    data["status"] = "in-service"
    data["installed_in"] = link
    for key in ("board", "bios", "cpus", "memory", "memory_slots"):
        if key in machine:
            data[key] = machine[key]
    if onboard:
        data["interfaces"] = onboard
    oob = parse_ipmi_lan(_text(results, "ipmi") or "")
    if oob:
        data["oob"] = oob
    if serial:
        view.items.append(Observed(f"serial:{serial.lower()}", file_name(_make_model(make, model), serial), data))
    else:
        view.items.append(Observed(f"machine:{host.lower()}", file_name(host, _make_model(make, model) or "machine"), data))

    card_items = []
    for bus, devs in sorted(cards.items()):
        first = devs[0]
        card_model = strip_ids(first.get("SDevice") or first.get("Device"))
        card = {"bastet": "hardware", "category": CARD_CLASSES[first["class_code"]],
                "make": strip_ids(first.get("Vendor")), "model": card_model, "pci": bus, "slot": slots[bus]}
        if first.get("Driver"):
            card["driver"] = first["Driver"]
        if ports_by_bus.get(bus):
            card["ports"] = ports_by_bus[bus]
        card["status"] = "in-service"
        card["installed_in"] = link
        card_items.append(Observed(f"pci:{host.lower()}:{bus}", file_name(host, card_model), card))
    names = [c.name for c in card_items]
    for c in card_items:
        if names.count(c.name) > 1:
            c.name = file_name(c.name, c.data["pci"])
    view.items.extend(card_items)

    smart = parse_smart(_text(results, "smart") or "")
    ids = parse_disk_ids(_text(results, "disk_ids") or "")
    pools = parse_zpool(_text(results, "zpool") or "")
    pool_of: dict[str, str] = {}
    for pool in pools:
        for dev in pool["devices"]:
            leaf = dev.rsplit("/", 1)[-1]
            pool_of[base_device(ids.get(leaf, leaf))] = pool["name"]
    view.pools = [{"name": p["name"], "state": p["state"]} for p in pools if p["state"]]

    blk_text = _text(results, "lsblk")
    try:
        disks = json.loads(blk_text).get("blockdevices", []) if blk_text else []
    except json.JSONDecodeError:
        disks = []
    view.complete["drives"] = blk_text is not None and bool(disks)
    for d in disks:
        if not isinstance(d, dict) or d.get("type") != "disk" or str(d.get("name", "")).startswith(SKIP_DISKS):
            continue
        tran = d.get("tran")
        s = smart.get(d.get("path"), {})
        drive_serial = clean(s.get("serial") or d.get("serial"))
        if not drive_serial or (tran and tran not in DRIVE_TRANSPORTS):
            continue
        drive_model = clean(s.get("model") or d.get("model")) or "Drive"
        drive: dict[str, object] = {"bastet": "hardware", "category": "drive", "model": drive_model, "serial": drive_serial}
        size = s.get("bytes") or d.get("size")
        if size:
            drive["size"] = format_size(int(size))
        if tran:
            drive["interface"] = tran
        rotational = s.get("rotation") not in (0, None) if "rotation" in s and s.get("rotation") is not None else d.get("rota") in (True, 1, "1")
        drive["media"] = "ssd" if tran == "nvme" or not rotational else "hdd"
        for key in ("firmware", "health"):
            if s.get(key):
                drive[key] = s[key]
        if pool_of.get(d.get("name", "")):
            drive["pool"] = pool_of[d["name"]]
        drive["status"] = "in-service"
        drive["installed_in"] = link
        view.items.append(Observed(f"serial:{drive_serial.lower()}", file_name(drive_model, drive_serial), drive))

    view.guests = parse_pve_guests(_text(results, "pve_guests") or "")
    return view
