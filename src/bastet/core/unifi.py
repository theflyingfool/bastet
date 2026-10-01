"""UniFi devices: what `mca-dump` (run over SSH on the device) tells Bastet, minus anything secret."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from bastet.core.errors import BastetError
from bastet.core.hardware import Observed, file_name
from bastet.core.hwparse import clean
from bastet.core.links import make_link

SENSITIVE = ("key", "pass", "secret", "token", "psk", "cert", "community", "auth", "credential", "shared", "hash")
_SECRET_TEXT = re.compile(r"(key|pass|secret|psk|token)\w*\s*[=:]", re.I)


def _sensitive(key: object) -> bool:
    k = str(key).lower()
    return k.startswith("x_") or any(s in k for s in SENSITIVE)
CATEGORY = {"unifi-gateway": "gateway", "unifi-switch": "switch", "unifi-ap": "ap"}


def redact(obj):
    """Drop anything that looks secret: sensitive keys, name/value pairs naming one, and key=value text."""
    if isinstance(obj, dict):
        named = any(_sensitive(obj.get(k)) for k in ("name", "key") if isinstance(obj.get(k), str))
        return {k: "(redacted)" if _sensitive(k) or (named and k == "value") else redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str) and _SECRET_TEXT.search(obj):
        return "(redacted)"
    return obj


@dataclass
class Port:
    id: str
    name: str
    media: str
    macs: list[str]
    uplink: bool


@dataclass
class Neighbour:
    local: str
    chassis: str
    wired: bool


@dataclass
class Device:
    mac: str
    model: str
    firmware: str
    serial: str | None
    hostname: str
    ports: list[Port] = field(default_factory=list)
    neighbours: list[Neighbour] = field(default_factory=list)
    interface_macs: set[str] = field(default_factory=set)


def parse_mca(text: str) -> Device:
    try:
        j = json.loads(text)
    except json.JSONDecodeError:
        raise BastetError("mca-dump didn't return JSON; is this a UniFi device?") from None
    ports, by_name = [], {}
    for p in j.get("port_table") or []:
        pid = str(p["port_idx"]) if p.get("port_idx") is not None else str(p.get("name") or "")
        macs = sorted({str(m.get("mac", "")).lower() for m in p.get("mac_table") or [] if m.get("mac")})
        port = Port(pid, str(p.get("name") or ""), str(p.get("media") or ""), macs, bool(p.get("is_uplink")))
        ports.append(port)
        by_name.setdefault(port.name, pid)
    ids = {p.id for p in ports}
    neighbours = []
    for n in j.get("lldp_table") or []:
        idx = n.get("local_port_idx")
        name = str(n.get("local_port_name") or "")
        local = str(idx) if idx is not None and str(idx) in ids else by_name.get(name, name or str(idx))
        neighbours.append(Neighbour(local, str(n.get("chassis_id", "")).lower(), bool(n.get("is_wired", True))))
    mac = str(j.get("mac", "")).lower()
    interface_macs = {str(i["mac"]).lower() for i in j.get("if_table") or [] if i.get("mac")} | {mac}
    return Device(mac=mac, model=str(j.get("model_display") or j.get("model") or ""), firmware=str(j.get("version") or ""),
                  serial=clean(j.get("serial")), hostname=str(j.get("hostname") or ""),
                  ports=sorted(ports, key=lambda p: (len(p.id), p.id)), neighbours=neighbours,
                  interface_macs=interface_macs - {""})


def device_facts(d: Device) -> dict:
    facts: dict = {"mac": d.mac, "firmware": d.firmware}
    if d.ports:
        facts["ports"] = [{"port": p.id, "name": p.name, "media": p.media} for p in d.ports]
    return {k: v for k, v in facts.items() if v}


def machine_item(host: str, type_name: str, d: Device) -> Observed:
    data = {"bastet": "hardware", "category": CATEGORY.get(type_name, "network"), "make": "Ubiquiti", "model": d.model}
    if d.serial:
        data["serial"] = d.serial
    data["status"], data["installed_in"] = "in-service", make_link(host)
    if d.serial:
        return Observed(f"serial:{d.serial.lower()}", file_name("Ubiquiti", d.model, d.serial), data)
    return Observed(f"machine:{host.lower()}", file_name(host, "Ubiquiti", d.model), data)
