"""Cabling from what UniFi devices see: LLDP between them, and port MAC tables against hosts' interface MACs.

Links are only proposed when the evidence is unambiguous; anything doubtful becomes a note instead,
because a link, once written, is never changed by Bastet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bastet.core.inventory import Inventory
from bastet.core.links import link_target, make_link
from bastet.core.unifi import Device

TIER = {"unifi-gateway": 3, "unifi-switch": 2, "unifi-ap": 1}
# Interfaces that share a NIC's MAC but aren't a cable end: bridges, bonds, VLANs, wireless, containers.
NOT_A_CABLE_END = re.compile(r"^(vmbr|bond|br|team|docker|virbr|veth|tap|fwbr|fwpr|fwln|wl|ww)|\.\d+$")


@dataclass
class LinkProposal:
    host: str
    link: dict


def _norm(mac: object) -> str:
    return re.sub(r"[^0-9a-f]", "", str(mac).lower())


def _host_macs(inv: Inventory) -> dict[str, tuple[str, str]]:
    """MAC -> (host, interface) for cabled hosts (not guests, not UniFi devices), physical interfaces only."""
    out: dict[str, tuple[str, str]] = {}
    hosts = {d.name.lower(): d for d in inv.of_kind("host")}
    cabled = {k: d for k, d in hosts.items()
              if not d.data.get("runs_on") and not str(d.data.get("type", "")).startswith("unifi-")}

    def add(mac, host, iface):
        if mac and iface and not NOT_A_CABLE_END.search(str(iface)):
            out.setdefault(_norm(mac), (host, str(iface)))

    for doc in cabled.values():
        for i in doc.data.get("interfaces") or []:
            if isinstance(i, dict):
                add(i.get("mac"), doc.name, i.get("name"))
    for hw in inv.of_kind("hardware"):
        host = cabled.get((link_target(hw.data.get("installed_in")) or "").lower())
        if host is None:
            continue
        for key in ("interfaces", "ports"):
            for i in hw.data.get(key) or []:
                if isinstance(i, dict):
                    add(i.get("mac"), host.name, i.get("name"))
    return out


def _unifi_macs(inv: Inventory, devices: dict[str, tuple[str, Device]]) -> dict[str, str]:
    """MAC -> UniFi host name: this run's devices plus every UniFi host note's recorded `mac`."""
    out = {}
    for doc in inv.of_kind("host"):
        if str(doc.data.get("type", "")).startswith("unifi-") and doc.data.get("mac"):
            out[_norm(doc.data["mac"])] = doc.name
    for name, (_, d) in devices.items():
        for m in d.interface_macs | {d.mac}:
            out[_norm(m)] = name
    return out


def propose_links(inv: Inventory, devices: dict[str, tuple[str, Device]]) -> tuple[list[LinkProposal], list[tuple[str, str]]]:
    """Proposals, plus notes (host, message) for evidence too ambiguous to write."""
    by_mac = _unifi_macs(inv, devices)
    trunk: dict[str, set[str]] = {name: set() for name in devices}
    proposals: list[LinkProposal] = []
    notes: list[tuple[str, str]] = []
    seen: set[frozenset] = set()
    for name, (type_name, d) in devices.items():
        for n in d.neighbours:
            if n.wired:
                trunk[name].add(n.local)  # anything speaking LLDP on a wired port is infrastructure, not a host
            other = by_mac.get(_norm(n.chassis))
            if not n.wired or other is None or other == name or other not in devices:
                continue
            back = next((m.local for m in devices[other][1].neighbours if m.wired and by_mac.get(_norm(m.chassis)) == name), None)
            pair = frozenset((name, other))
            if pair in seen or back is None:
                continue
            seen.add(pair)
            if TIER.get(type_name, 0) <= TIER.get(devices[other][0], 0):
                proposals.append(LinkProposal(name, {"port": n.local, "to": make_link(other), "to_port": back}))
            else:
                proposals.append(LinkProposal(other, {"port": back, "to": make_link(name), "to_port": n.local}))
    host_macs = _host_macs(inv)
    found: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for name, (_, d) in devices.items():
        for p in d.ports:
            if p.uplink or p.id in trunk[name] or any(_norm(m) in by_mac for m in p.macs):
                continue
            known = sorted({host_macs[_norm(m)] for m in p.macs if _norm(m) in host_macs})
            if len(known) > 1:
                notes.append((name, f"port {p.id} sees {len(known)} hosts ({', '.join(h for h, _ in known)}); "
                                    "behind an unmanaged switch? not linked"))
                continue
            if known:
                found.setdefault(known[0], []).append((name, p.id))
    for (host, iface), places in found.items():
        if len(places) > 1:
            where = ", ".join(f"[[{n}]] port {pid}" for n, pid in places)
            notes.append((host, f"{iface} seen on several ports ({where}); not linked"))
            continue
        name, pid = places[0]
        proposals.append(LinkProposal(host, {"port": iface, "to": make_link(name), "to_port": pid}))
    return proposals, notes


def merge_links(existing: object, proposals: list[dict]) -> tuple[list | None, list[str]]:
    """Append proposed links for ports without one, keeping every existing entry exactly as written.

    Returns (new list, or None when nothing is new or `links` isn't a list; conflict messages).
    """
    if existing is None:
        existing = []
    if not isinstance(existing, list):
        return None, ["links isn't a list; left alone"]
    by_port = {str(e.get("port")): e for e in existing if isinstance(e, dict)}
    new: list[dict] = []
    conflicts: list[str] = []
    for link in proposals:
        have = by_port.get(str(link["port"]))
        if have is None:
            new.append(link)
            by_port[str(link["port"])] = link
        elif (have.get("to"), str(have.get("to_port"))) != (link["to"], str(link["to_port"])):
            conflicts.append(f"{link['port']}: seen on {link['to']} port {link['to_port']}, "
                             f"the file says {have.get('to')} port {have.get('to_port')}")
    return (list(existing) + new if new else None), conflicts
