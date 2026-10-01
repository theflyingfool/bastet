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
    base_device, board_subsystem_id, clean, cpus_from_dmi, parse_ethtool, parse_firmware_info, parse_fru,
    parse_mc_info, parse_usb, psus_from_dmi, short_cpu, parse_guest_conf, parse_neigh, has_bmc, machine_from_dmi, pci_id, slot_designations, parse_disk_ids, parse_dmidecode, parse_ipmi_lan, parse_lspci,
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
    alt: str | None = None  # host-scoped fallback key, tried when the serial key finds no file


@dataclass
class HardwareView:
    items: list[Observed] = field(default_factory=list)
    pools: list[dict] = field(default_factory=list)
    guests: list[dict] = field(default_factory=list)
    complete: dict[str, bool] = field(default_factory=lambda: {
        "drives": False, "cards": False, "cpus": False, "memory": False, "psus": False, "usb": False})
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


def _usable(results: dict[str, ProbeResult], name: str) -> str | None:
    """Output of a probe that ran (not missing, not denied), even if it exited non-zero."""
    r = results.get(name)
    return r.output if r is not None and not r.missing and not r.denied and r.output.strip() else None


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
    eth = parse_ethtool(_text(results, "ethtool") or "")
    usb_devices = parse_usb(_text(results, "usb") or "")
    slots = slots_in_use(dmi)
    ports_by_bus: dict[str, list[dict]] = {}
    onboard: list[dict] = []
    for ifname, info in sorted(net.items()):
        if not info["pci"]:
            continue
        port = {"name": ifname}
        if macs.get(ifname):
            port["mac"] = macs[ifname]
        for key in ("max_speed", "firmware"):
            if eth.get(ifname, {}).get(key):
                port[key] = eth[ifname][key]
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
    gpus = [{"model": strip_ids(d.get("Device")), "make": strip_ids(d.get("Vendor")), "pci": d.get("Slot")}
            for d in pci if d["class_code"].startswith("03") and d.get("Slot", "").rsplit(".", 1)[0] not in cards]
    if gpus:
        data["gpus"] = gpus
    builtin_usb = [{"name": u.get("model") or u["id"], "id": u["id"]} for u in usb_devices if not u["removable"]]
    if builtin_usb:
        data["usb"] = builtin_usb
    ipmi_result = results.get("ipmi")
    if ipmi_result is not None and ipmi_result.missing and has_bmc(dmi, pci, _text(results, "ipmi_dev")):
        view.hints.append(f"has a BMC (IPMI); install ipmitool on {host} to record its out-of-band address")
    oob = parse_ipmi_lan(_text(results, "ipmi") or "")
    if oob:
        data["oob"] = oob
        data["oob_address"] = oob["address"]
    mc = parse_mc_info(_text(results, "ipmi_mc") or "")
    if mc.get("firmware"):
        data["bmc_firmware"] = mc["firmware"]
    data.update(parse_firmware_info(_text(results, "firmware") or ""))
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

    view.items.extend(_parts(host, link, dmi, machine, results, usb_devices))
    view.complete["cpus"] = view.complete["memory"] = bool(dmi)
    view.complete["psus"] = bool(_usable(results, "ipmi_fru")) or bool(psus_from_dmi(dmi))
    usb_result = results.get("usb")
    view.complete["usb"] = usb_result is not None and usb_result.ok

    view.guests = parse_pve_guests(_text(results, "pve_guests") or "")
    confs = parse_guest_conf(_text(results, "pve_guest_conf") or "")
    neighbours = parse_neigh(_text(results, "neigh") or "")
    for guest in view.guests:
        conf = confs.get(int(guest["vmid"])) if str(guest.get("vmid", "")).isdigit() else None
        guest["ip"], guest["ip_source"] = None, None
        guest["conf_ip"] = conf["ip"] if conf else None
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


def _part(category: str, link: str, fields: dict) -> dict:
    data: dict[str, object] = {"bastet": "hardware", "category": category}
    data.update({k: v for k, v in fields.items() if v not in (None, "")})
    data["status"], data["installed_in"] = "in-service", link
    return data


def _merge_psus(fru: list[dict], dmi: list[dict]) -> list[dict]:
    psus = [dict(p) for p in fru]
    for p in dmi:
        same = next((q for q in psus if (p.get("serial") and p.get("serial") == q.get("serial"))
                     or ((not p.get("serial") or not q.get("serial")) and p.get("model") and p.get("model") == q.get("model"))), None)
        if same is None:
            psus.append(dict(p))
        else:
            for k, v in p.items():
                same.setdefault(k, v)
    return psus


def _parts(host: str, link: str, dmi: list[dict], machine: dict, results: dict[str, ProbeResult],
           usb_devices: list[dict]) -> list[Observed]:
    """Removable parts that get their own files: CPUs, memory sticks, PSUs and removable USB devices."""
    h = host.lower()
    items: list[Observed] = []
    for c in cpus_from_dmi(dmi):
        short = short_cpu(c.get("model") or "CPU")
        data = _part("cpu", link, {k: c.get(k) for k in ("make", "model", "serial", "socket", "cores", "threads")})
        socket = str(c.get("socket") or "0")
        fallback = f"cpu:{h}:{socket.lower()}"
        if c.get("serial"):
            items.append(Observed(f"serial:{c['serial'].lower()}", file_name(short, c["serial"]), data, fallback))
        else:
            items.append(Observed(fallback, file_name(host, short, socket), data))
    for d in machine.get("memory", []):
        data = _part("memory", link, {"make": d.get("make"), "model": d.get("part"), "serial": d.get("serial"),
                                      "size": d.get("size"), "type": d.get("type"), "speed": d.get("speed"),
                                      "slot": d.get("slot")})
        slot = str(d.get("slot") or "0")
        fallback = f"dimm:{h}:{slot.lower()}"
        if d.get("serial"):
            label = d.get("part") or " ".join(x for x in (d.get("type"), d.get("size")) if x)
            items.append(Observed(f"serial:{d['serial'].lower()}", file_name(d.get("make"), label, d["serial"]), data, fallback))
        else:
            items.append(Observed(fallback, file_name(host, slot, d.get("size")), data))
    for p in _merge_psus(parse_fru(_usable(results, "ipmi_fru") or ""), psus_from_dmi(dmi)):
        data = _part("psu", link, {k: p.get(k) for k in ("make", "model", "serial", "max_power", "name")})
        label = str(p.get("name") or p.get("model") or "PSU")
        fallback = f"psu:{h}:{label.lower()}"
        if p.get("serial"):
            items.append(Observed(f"serial:{p['serial'].lower()}", file_name(p.get("model"), p["serial"]), data, fallback))
        else:
            items.append(Observed(fallback, file_name(host, label), data))
    for u in usb_devices:
        if not u["removable"]:
            continue
        data = _part("usb", link, {"make": u.get("make"), "model": u.get("model"), "serial": u.get("serial"),
                                   "usb_id": u["id"], "usb_port": None if u.get("serial") else u["busid"]})
        label = u.get("model") or f"USB {u['id']}"
        if u.get("serial"):
            items.append(Observed(f"usb:{u['id']}:{u['serial'].lower()}", file_name(label, u["serial"]), data))
        else:
            items.append(Observed(f"usb:{h}:{u['id']}:{u['busid']}", file_name(host, label), data))
    return items


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
        category, serial = doc.data.get("category"), doc.data.get("serial")
        if category == "usb" and doc.data.get("usb_id"):
            if serial:
                index.setdefault(f"usb:{doc.data['usb_id']}:{str(serial).lower()}", doc)
            elif target and doc.data.get("usb_port"):
                index.setdefault(f"usb:{target}:{doc.data['usb_id']}:{doc.data['usb_port']}", doc)
        elif target:
            fallback = {"cpu": ("cpu", doc.data.get("socket")), "memory": ("dimm", doc.data.get("slot")),
                        "psu": ("psu", doc.data.get("name") or doc.data.get("model"))}.get(str(category))
            if fallback and fallback[1]:
                index.setdefault(f"{fallback[0]}:{target}:{str(fallback[1]).lower()}", doc)
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
        if doc is None and obs.alt and index.get(obs.alt) is not None:
            candidate = index[obs.alt]
            if not candidate.data.get("serial") or str(candidate.data["serial"]).lower() == str(obs.data.get("serial")).lower():
                doc = candidate
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
        complete_key = {"drive": "drives", "gpu": "cards", "hba": "cards", "nic": "cards", "cpu": "cpus",
                        "memory": "memory", "psu": "psus", "usb": "usb"}.get(str(category))
        checked = bool(complete_key and view.complete.get(complete_key))
        if checked:
            notes.append(Note(host, "warn", f"{doc.name} is recorded in {host} but wasn't seen (pulled, failed or moved?); its file is unchanged"))
    return changes, notes
