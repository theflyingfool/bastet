"""Pure parsers for hardware probe output."""

import json
import re

PLACEHOLDERS = {
    "", "to be filled by o.e.m.", "default string", "system serial number", "0123456789", "not specified",
    "none", "n/a", "0", "00000000", "not applicable", "chassis serial number", "base board serial number",
    "unknown", "not available", "serial number", "o.e.m.",
}


def clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in PLACEHOLDERS else text


def _int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_dmidecode(text: str) -> list[dict]:
    records: list[dict] = []
    current: dict | None = None
    want_title = False
    for line in text.splitlines():
        m = re.match(r"^Handle 0x[0-9A-Fa-f]+, DMI type (\d+),", line)
        if m:
            current = {"type": int(m.group(1)), "title": "", "fields": {}}
            records.append(current)
            want_title = True
            continue
        if current is None:
            continue
        if want_title and line.strip() and not line.startswith("\t"):
            current["title"] = line.strip()
            want_title = False
            continue
        fm = re.match(r"^\t([^\t:][^:]*):\s?(.*)$", line)
        if fm:
            current["fields"][fm.group(1).strip()] = fm.group(2).strip()
    return records


def _of_type(records: list[dict], dmi_type: int) -> list[dict]:
    return [r["fields"] for r in records if r["type"] == dmi_type]


def memory_size(text: str) -> str | None:
    m = re.match(r"^\s*(\d+)\s*(MB|GB|TB)\s*$", str(text))
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if unit == "MB" and n >= 1024 and n % 1024 == 0:
        return f"{n // 1024} GB"
    return f"{n} {unit}"


def machine_from_dmi(records: list[dict]) -> dict:
    first = lambda t: (_of_type(records, t) or [{}])[0]  # noqa: E731
    system, board, bios, chassis = first(1), first(2), first(0), first(3)
    out: dict[str, object] = {
        "make": clean(system.get("Manufacturer")),
        "model": clean(system.get("Product Name")),
        "serial": clean(system.get("Serial Number")) or clean(chassis.get("Serial Number")) or clean(board.get("Serial Number")),
    }
    if clean(board.get("Product Name")):
        out["board"] = " ".join(x for x in (clean(board.get("Manufacturer")), clean(board.get("Product Name"))) if x)
    if clean(bios.get("Version")):
        text = " ".join(x for x in (clean(bios.get("Vendor")), clean(bios.get("Version"))) if x)
        if clean(bios.get("Release Date")):
            text += f" ({bios['Release Date']})"
        out["bios"] = text
    cpus = []
    for c in _of_type(records, 4):
        if "Populated" not in c.get("Status", ""):
            continue
        entry = {"socket": clean(c.get("Socket Designation")), "model": clean(c.get("Version")),
                 "cores": _int(c.get("Core Count")), "threads": _int(c.get("Thread Count"))}
        cpus.append({k: v for k, v in entry.items() if v not in (None, "")})
    if cpus:
        out["cpus"] = cpus
    dimms = _of_type(records, 17)
    memory = []
    for d in dimms:
        size = memory_size(d.get("Size", ""))
        if not size:
            continue
        entry = {"slot": clean(d.get("Locator")), "size": size, "type": clean(d.get("Type")),
                 "speed": clean(d.get("Configured Memory Speed")) or clean(d.get("Speed")),
                 "part": clean(d.get("Part Number")), "serial": clean(d.get("Serial Number"))}
        memory.append({k: v for k, v in entry.items() if v})
    if memory:
        out["memory"] = memory
    if dimms:
        out["memory_slots"] = f"{len(memory)} of {len(dimms)} used"
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def slots_in_use(records: list[dict]) -> dict[str, str]:
    out = {}
    for s in _of_type(records, 9):
        address = s.get("Bus Address", "")
        if "In Use" in s.get("Current Usage", "") and re.match(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.", address):
            out[address.rsplit(".", 1)[0]] = s.get("Designation", "").strip()
    return out


def parse_lspci(text: str) -> list[dict]:
    devices: list[dict] = []
    current: dict = {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if current:
                devices.append(current)
                current = {}
            continue
        key, _, value = line.partition(":")
        current[key.strip()] = value.strip()
    for d in devices:
        m = re.search(r"\[([0-9a-f]{4})\]\s*$", d.get("Class", ""))
        d["class_code"] = m.group(1) if m else ""
    return devices


def strip_ids(name: str | None) -> str:
    return re.sub(r"\s*\[[0-9a-f]{4}\]\s*$", "", name or "").strip()


def parse_net_sysfs(text: str) -> dict[str, dict]:
    out = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        speed = _int(parts[1]) if len(parts) > 1 else None
        target = parts[2].rsplit("/", 1)[-1] if len(parts) > 2 and parts[2] else ""
        out[parts[0]] = {
            "speed": speed if speed and speed > 0 else None,
            "pci": target if re.match(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$", target) else None,
        }
    return out


def speed_label(mbps: int | None) -> str | None:
    if not mbps:
        return None
    return f"{mbps / 1000:g}G" if mbps >= 1000 else f"{mbps}M"


def parse_ipmi_lan(text: str) -> dict | None:
    fields = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    address = fields.get("IP Address")
    if not address or address == "0.0.0.0":
        return None
    out = {"type": "ipmi", "address": address}
    if clean(fields.get("MAC Address")) and fields["MAC Address"] != "00:00:00:00:00:00":
        out["mac"] = fields["MAC Address"]
    source = fields.get("IP Address Source", "")
    if source:
        out["source"] = "dhcp" if "dhcp" in source.lower() else "static"
    return out


def parse_zpool(text: str) -> list[dict]:
    pools: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m = re.match(r"^\s*pool:\s*(\S+)", line)
        if m:
            current = {"name": m.group(1), "state": None, "devices": []}
            pools.append(current)
            continue
        if current is None:
            continue
        m = re.match(r"^\s*state:\s*(\S+)", line)
        if m:
            current["state"] = m.group(1)
            continue
        m = re.match(r"^\s+(/dev/\S+)", line)
        if m:
            current["devices"].append(m.group(1))
    return pools


def parse_disk_ids(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.search(r"\s(\S+) -> \S*?([^/\s]+)$", line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def base_device(name: str) -> str:
    m = re.match(r"^(nvme\d+n\d+)p\d+$", name)
    if m:
        return m.group(1)
    m = re.match(r"^((?:sd|vd|hd|xvd)[a-z]+)\d+$", name)
    return m.group(1) if m else name


def parse_smart(text: str) -> dict[str, dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    out = {}
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict) or not entry.get("serial_number"):
            continue
        path = (entry.get("device") or {}).get("name")
        status = entry.get("smart_status")
        out[path] = {
            "model": clean(entry.get("model_name")),
            "serial": clean(entry.get("serial_number")),
            "firmware": clean(entry.get("firmware_version")),
            "health": ("passed" if status.get("passed") else "failing") if isinstance(status, dict) else None,
            "rotation": entry.get("rotation_rate"),
            "bytes": (entry.get("user_capacity") or {}).get("bytes") or entry.get("nvme_total_capacity"),
        }
    return out


def parse_pve_guests(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    keys = ("vmid", "name", "type", "node", "status")
    return [{k: g.get(k) for k in keys} for g in data if isinstance(g, dict) and g.get("vmid") is not None]
