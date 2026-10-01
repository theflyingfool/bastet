"""Cabling from what UniFi devices see: LLDP between them, and port MAC tables against hosts' interface MACs."""

from __future__ import annotations

from dataclasses import dataclass

from bastet.core.inventory import Inventory
from bastet.core.links import link_target, make_link
from bastet.core.unifi import Device

TIER = {"unifi-gateway": 3, "unifi-switch": 2, "unifi-ap": 1}


@dataclass
class LinkProposal:
    host: str
    link: dict


def _host_macs(inv: Inventory) -> dict[str, tuple[str, str]]:
    """MAC -> (host, interface) for hosts that are cabled: not guests, not UniFi devices."""
    out: dict[str, tuple[str, str]] = {}
    hosts = {d.name.lower(): d for d in inv.of_kind("host")}
    cabled = {k: d for k, d in hosts.items() if not d.data.get("runs_on") and not str(d.data.get("type", "")).startswith("unifi-")}
    for doc in cabled.values():
        for i in doc.data.get("interfaces") or []:
            if isinstance(i, dict) and i.get("mac") and i.get("name"):
                out[str(i["mac"]).lower()] = (doc.name, str(i["name"]))
    for hw in inv.of_kind("hardware"):
        host = cabled.get((link_target(hw.data.get("installed_in")) or "").lower())
        if host is None:
            continue
        for key in ("interfaces", "ports"):
            for i in hw.data.get(key) or []:
                if isinstance(i, dict) and i.get("mac") and i.get("name"):
                    out.setdefault(str(i["mac"]).lower(), (host.name, str(i["name"])))
    return out


def propose_links(inv: Inventory, devices: dict[str, tuple[str, Device]]) -> list[LinkProposal]:
    by_mac = {m: name for name, (_, d) in devices.items() for m in d.interface_macs | {d.mac}}
    trunk: dict[str, set[str]] = {name: set() for name in devices}
    proposals: list[LinkProposal] = []
    seen: set[frozenset] = set()
    for name, (type_name, d) in devices.items():
        for n in d.neighbours:
            other = by_mac.get(n.chassis)
            if not n.wired or other is None or other == name:
                continue
            trunk[name].add(n.local)
            back = next((m.local for m in devices[other][1].neighbours if m.wired and by_mac.get(m.chassis) == name), None)
            if back is not None:
                trunk[other].add(back)
            pair = frozenset((name, other))
            if pair in seen or back is None:
                continue
            seen.add(pair)
            if TIER.get(type_name, 0) <= TIER.get(devices[other][0], 0):
                proposals.append(LinkProposal(name, {"port": n.local, "to": make_link(other), "to_port": back}))
            else:
                proposals.append(LinkProposal(other, {"port": back, "to": make_link(name), "to_port": n.local}))
    host_macs = _host_macs(inv)
    for name, (_, d) in devices.items():
        for p in d.ports:
            if p.uplink or p.id in trunk[name]:
                continue
            for mac in p.macs:
                if mac in host_macs:
                    host, iface = host_macs[mac]
                    proposals.append(LinkProposal(host, {"port": iface, "to": make_link(name), "to_port": p.id}))
    return proposals


def merge_links(existing: list, proposals: list[dict]) -> list | None:
    """Add proposed links for ports without one; never change a link that's there. None when nothing is new."""
    existing = [e for e in existing or [] if isinstance(e, dict)]
    taken = {str(e.get("port")) for e in existing}
    new = []
    for link in proposals:
        if str(link["port"]) not in taken and link not in new:
            new.append(link)
            taken.add(str(link["port"]))
    return existing + new if new else None
