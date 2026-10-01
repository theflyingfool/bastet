"""Turn hardware probe output into proposed hardware files, and plan changes against the inventory."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from bastet.core.changes import Change
from bastet.core.collect import ProbeResult
from bastet.core.facts import SKIP_DISKS, Extracted
from bastet.core.frontmatter import Document, new_document, set_keys
from bastet.core.gatherplan import Note, merge_facts
from bastet.core.gitrepo import GitRepo
from bastet.core.hwparse import (
    base_device, board_subsystem_id, clean, parse_guest_conf, parse_neigh, has_ipmi, machine_from_dmi, pci_id, slot_designations, parse_disk_ids, parse_dmidecode, parse_ipmi_lan, parse_lspci,
    parse_net_sysfs, parse_pve_guests, parse_smart, parse_zpool, slots_in_use, strip_ids,
)
from bastet.core.inventory import Inventory, markdown_files
from bastet.core.links import link_target, make_link
from bastet.core.units import format_size
from bastet.core.views import ensure_page_embed, summary_embed

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
    notes: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)


@dataclass
class RunState:
    """Shared across the hosts of one gather run, so two hosts never create the same file."""
    claimed: dict[str, str] = field(default_factory=dict)
    names: set[str] = field(default_factory=set)


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
        bus = info["pci"].rsplit(".", 1)[0]
        ports_by_bus.setdefault(bus, []).append(port)

    designations = slot_designations(dmi)
    pci = parse_lspci(_text(results, "lspci") or "")
    # Boards often report useless slot data; then an add-in card shows itself by a PCI subsystem vendor
    # different from the one the board maker stamps on its onboard devices (found by name, else not used).
    board_makers = [machine.get("make"), clean(ex.hints.get("vendor"))]
    board_makers += [r["fields"].get("Manufacturer") for r in dmi if r["type"] == 2]
    # Slot data is useful when it points at real devices; boards that list root ports/bridges (class 06xx)
    # as slot addresses tell us nothing.
    slot_data_useful = any(d.get("PhySlot") for d in pci) or any(
        d.get("Slot", "").rsplit(".", 1)[0] in slots and not d["class_code"].startswith("06") for d in pci)
    board_svid = None if slot_data_useful else board_subsystem_id(pci, board_makers)
    cards: dict[str, list[dict]] = {}
    for dev in pci:
        bus = dev.get("Slot", "").rsplit(".", 1)[0]
        svid = pci_id(dev.get("SVendor"))
        in_slot = bool(dev.get("PhySlot")) or bus in slots or bool(svid and board_svid and svid != board_svid)
        if dev["class_code"] in CARD_CLASSES and in_slot:
            cards.setdefault(bus, []).append(dev)
        elif dev["class_code"] in ("0200", "0280") and dev.get("Slot", "").endswith(".0"):
            onboard.extend(ports_by_bus.get(bus, []))
    view.complete["cards"] = bool(pci)

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
    ipmi_result = results.get("ipmi")
    if has_ipmi(dmi) and ipmi_result is not None and ipmi_result.missing:
        view.hints.append(f"has a BMC (IPMI); install ipmitool on {host} to record its out-of-band address")
    oob = parse_ipmi_lan(_text(results, "ipmi") or "")
    if oob:
        data["oob"] = oob
        data["oob_address"] = oob["address"]
    if serial:
        view.items.append(Observed(f"serial:{serial.lower()}", file_name(_make_model(make, model), serial), data))
    else:
        view.items.append(Observed(f"machine:{host.lower()}", file_name(host, _make_model(make, model) or "machine"), data))

    card_items = []
    for bus, devs in sorted(cards.items()):
        first = devs[0]
        sub = strip_ids(first.get("SDevice"))
        card_model = sub if sub and sub != "Device" else strip_ids(first.get("Device"))
        phys = (first.get("PhySlot") or "").strip()
        slot_name = designations.get(phys) or slots.get(bus) or (f"slot {phys}" if phys else "")
        card = {"bastet": "hardware", "category": CARD_CLASSES[first["class_code"]],
                "make": strip_ids(first.get("Vendor")), "model": card_model, "pci": bus}
        if slot_name:
            card["slot"] = slot_name
        if phys:
            card["phys_slot"] = phys
        if first.get("Driver"):
            card["driver"] = first["Driver"]
        if ports_by_bus.get(bus):
            card["ports"] = ports_by_bus[bus]
        card["status"] = "in-service"
        card["installed_in"] = link
        key = f"slot:{host.lower()}:{phys}" if phys else f"pci:{host.lower()}:{bus}"
        card_items.append(Observed(key, file_name(host, card_model), card))
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
    confs = parse_guest_conf(_text(results, "pve_guest_conf") or "")
    neighbours = parse_neigh(_text(results, "neigh") or "")
    for guest in view.guests:
        conf = confs.get(int(guest["vmid"])) if str(guest.get("vmid", "")).isdigit() else None
        guest["ip"], guest["ip_source"] = None, None
        if conf and conf["ip"] and conf["ip"] != "dhcp":
            guest["ip"], guest["ip_source"] = conf["ip"], "config"
        elif conf:
            seen = next((neighbours[m] for m in conf["macs"] if m in neighbours), None)
            if seen:
                guest["ip"], guest["ip_source"] = seen, "neighbour"
    seen: dict[str, Observed] = {}
    unique = []
    for item in view.items:
        if item.key in seen:
            view.notes.append(f"{item.data.get('serial') or item.key} appears twice ({seen[item.key].name}); "
                              "multipath or a duplicated serial, one file kept")
            continue
        seen[item.key] = item
        unique.append(item)
    view.items = unique
    return view


HARDWARE_YOURS = {"category", "status", "location", "purchased", "vendor", "price", "warranty_until", "notes"}
HARDWARE_SPECIAL = {"bastet", "installed_in"}


def _index(inv: Inventory) -> dict[str, Document]:
    index: dict[str, Document] = {}
    for doc in inv.of_kind("hardware"):
        target = (link_target(doc.data.get("installed_in")) or "").lower()
        if doc.data.get("serial"):
            index[f"serial:{str(doc.data['serial']).lower()}"] = doc
        if doc.data.get("phys_slot") and target:
            index[f"slot:{target}:{doc.data['phys_slot']}"] = doc
        if doc.data.get("pci") and target:
            index.setdefault(f"pci:{target}:{doc.data['pci']}", doc)
        if target and doc.data.get("category") in MACHINE_CATEGORIES:
            index.setdefault(f"machine-any:{target}", doc)
            if not doc.data.get("serial"):
                index.setdefault(f"machine:{target}", doc)
    return index


def plan_hardware(
    inv: Inventory,
    host_doc: Document,
    view: HardwareView,
    repo: GitRepo,
    *,
    take: set[str],
    run: RunState | None = None,
) -> tuple[list[Change], list[Note]]:
    host = host_doc.name
    run = run if run is not None else RunState()
    index = _index(inv)
    if not run.names:
        run.names.update(p.stem.lower() for p in markdown_files(inv.root))
    changes: list[Change] = []
    notes: list[Note] = [Note(host, "warn", n) for n in view.notes] + [Note(host, "info", h) for h in view.hints]
    seen: set[Path] = set()

    for obs in view.items:
        if obs.key in run.claimed and run.claimed[obs.key] != host:
            notes.append(Note(host, "warn", f"{obs.name} was also seen in {run.claimed[obs.key]} in this run; not recorded twice"))
            continue
        run.claimed[obs.key] = host
        doc = index.get(obs.key)
        if doc is None and obs.data.get("category") in MACHINE_CATEGORIES:
            fallback = "machine-any" if obs.key.startswith("machine:") else "machine"
            doc = index.get(f"{fallback}:{host.lower()}")
        if doc is None:
            name, n = obs.name, 2
            while name.lower() in run.names:
                name, n = f"{obs.name} {n}", n + 1
            run.names.add(name.lower())
            body = f"# {name}\n\n{summary_embed(name)}\n"
            data = {**obs.data, "cssclasses": ["bastet-host"]}
            changes.append(Change(inv.root / "hardware" / f"{name}.md", None, new_document(data, body)))
            continue
        seen.add(doc.path)
        observed = {k: v for k, v in obs.data.items() if k not in HARDWARE_YOURS | HARDWARE_SPECIAL | {"cssclasses"}}
        updates, fact_notes = merge_facts(doc, observed, repo, take=take, nature_of=lambda k: "fact", warn=lambda k: True)
        notes.extend(fact_notes)
        current = link_target(doc.data.get("installed_in"))
        if (current or "").lower() != host.lower():
            updates["installed_in"] = make_link(host)
            where = f"moved from [[{current}]] to [[{host}]]" if current else f"is now installed in [[{host}]]"
            notes.append(Note(host, "info", f"{doc.name} {where}"))
        status = doc.data.get("status")
        if status not in (None, "in-service"):
            notes.append(Note(host, "warn", f"{doc.name} has status '{status}' but is installed in {host}; update it if that's wrong"))
        if not doc.data.get("cssclasses"):
            updates["cssclasses"] = ["bastet-host"]
        text = doc.path.read_text(encoding="utf-8")
        new_text = set_keys(text, updates, doc.path) if updates else text
        new_text = ensure_page_embed(new_text, summary_embed(doc.name))
        if new_text != text:
            changes.append(Change(doc.path, text, new_text))

    for doc in inv.of_kind("hardware"):
        if doc.path in seen or (link_target(doc.data.get("installed_in")) or "").lower() != host.lower():
            continue
        category = doc.data.get("category")
        checked = (category == "drive" and view.complete["drives"]) or (category in ("gpu", "hba", "nic") and view.complete["cards"])
        if checked:
            notes.append(Note(host, "warn", f"{doc.name} is recorded in {host} but wasn't seen (pulled, failed or moved?); its file is unchanged"))
    return changes, notes
