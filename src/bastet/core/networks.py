"""The lab file's `networks:`: parsed, and checked against hosts' addresses and links' VLANs."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from bastet.core.errors import BastetError
from bastet.core.frontmatter import Document
from bastet.core.hosttypes import HostType
from bastet.core.inventory import Inventory, Problem, _bare_ip


LAN_RANGES = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7"))


def is_lan(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """RFC 1918 / ULA: an address that belongs in one of the lab's networks (unlike public or test addresses)."""
    return any(address.version == n.version and address in n for n in LAN_RANGES)


@dataclass
class Network:
    name: str
    cidr: ipaddress.IPv4Network | ipaddress.IPv6Network
    vlan: int | None
    purpose: list[str]
    data: dict


def _parse(name: str, spec: object) -> tuple[Network | None, str | None]:
    if not isinstance(spec, dict):
        return None, f"network '{name}' isn't a mapping"
    try:
        cidr = ipaddress.ip_network(str(spec.get("cidr")), strict=False)
    except ValueError:
        return None, f"network '{name}': cidr '{spec.get('cidr')}' isn't a network like 10.0.20.0/24"
    vlan = spec.get("vlan")
    if vlan is not None and (not isinstance(vlan, int) or isinstance(vlan, bool) or not 1 <= vlan <= 4094):
        return None, f"network '{name}': vlan {vlan} isn't 1–4094"
    purpose = spec.get("purpose") or []
    return Network(name, cidr, vlan, [str(p) for p in (purpose if isinstance(purpose, list) else [purpose])], spec), None


def lab_networks(inv: Inventory) -> dict[str, Network]:
    raw = (inv.lab.data.get("networks") if inv.lab else None) or {}
    if not isinstance(raw, dict):
        return {}
    return {str(n): net for n, spec in raw.items() if (net := _parse(str(n), spec)[0]) is not None}


def network_of(nets: dict[str, Network], address: str) -> Network | None:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    return next((n for n in nets.values() if ip.version == n.cidr.version and ip in n.cidr), None)


def _problem(inv: Inventory, severity: str, message: str, doc: Document, key: str | None) -> None:
    line = doc.key_lines.get(key) if key else None
    inv.problems.append(Problem(severity, BastetError(message, file=doc.path, line=line, key=key)))


def link_vlans(link: dict) -> list[object]:
    out = [link.get(k) for k in ("vlan", "native_vlan") if link.get(k) is not None]
    vlans = link.get("vlans")
    return out + (vlans if isinstance(vlans, list) else [vlans] if vlans is not None else [])


def _vlan_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def check_networks(inv: Inventory, types: dict[str, HostType]) -> None:
    lab = inv.lab
    raw = lab.data.get("networks") if lab else None
    if raw is None:
        return
    if not isinstance(raw, dict):
        _problem(inv, "error", "networks should be a mapping of name → {cidr, vlan, …}", lab, "networks")
        return
    nets: dict[str, Network] = {}
    for name, spec in raw.items():
        net, err = _parse(str(name), spec)
        if err:
            _problem(inv, "error", err, lab, "networks")
        if net:
            nets[net.name] = net
    seen_vlan: dict[int, str] = {}
    items = list(nets.values())
    for i, net in enumerate(items):
        if net.vlan is not None:
            if net.vlan in seen_vlan:
                _problem(inv, "error", f"VLAN {net.vlan} is used by both {seen_vlan[net.vlan]} and {net.name}", lab, "networks")
            seen_vlan.setdefault(net.vlan, net.name)
        for other in items[:i]:
            if net.cidr.version == other.cidr.version and net.cidr.overlaps(other.cidr):
                _problem(inv, "error", f"{net.name} ({net.cidr}) overlaps {other.name} ({other.cidr})", lab, "networks")
    if not nets:
        return
    for doc in inv.of_kind("host"):
        wanted = doc.data.get("network")
        if wanted is not None and str(wanted) not in nets:
            _problem(inv, "error", f"network '{wanted}' isn't in the lab file (have: {', '.join(sorted(nets))})", doc, "network")
        bare = _bare_ip(doc.data.get("ip")) if doc.data.get("ip") else None
        if not bare:
            continue
        address = ipaddress.ip_address(bare)
        if wanted is not None and str(wanted) in nets:
            net = nets[str(wanted)]
            if address.version != net.cidr.version or address not in net.cidr:
                _problem(inv, "error", f"{bare} is outside {net.name} ({net.cidr})", doc, "ip")
        elif is_lan(address) and network_of(nets, bare) is None:
            _problem(inv, "warning", f"{bare} is in none of the lab's networks", doc, "ip")
    vlans = set(seen_vlan)
    if not vlans:  # an untagged-only lab: nothing to check link VLANs against
        return
    from bastet.core.hostview import host_data  # lazy: hostview builds on inventory

    for doc in [*inv.of_kind("host"), *inv.of_kind("hardware")]:
        links = (host_data(inv, doc, types) if doc.data.get("bastet") == "host" else doc.data).get("links")
        for link in links if isinstance(links, list) else []:
            if not isinstance(link, dict):
                continue
            for v in link_vlans(link):
                number = _vlan_number(v)
                if number is None:
                    _problem(inv, "error", f"link {link.get('port')}: VLAN {v!r} isn't a number", doc, "links")
                elif number not in vlans:
                    _problem(inv, "error", f"link {link.get('port')}: VLAN {number} isn't any lab network's vlan", doc, "links")


def compare_networks(nets: dict[str, Network], seen: list[dict]) -> list[tuple[str, str]]:
    """What the gateway has against what the lab file plans: (severity, message) pairs for gather's notes."""
    out: list[tuple[str, str]] = []
    seen_cidrs = set()
    for s in seen:
        cidr = ipaddress.ip_network(s["cidr"])
        seen_cidrs.add(cidr)
        if not any(n.cidr == cidr for n in nets.values()):
            out.append(("warn", f"{cidr} ({s['interface']}) is on the gateway but not in the lab file's networks"))
    for n in nets.values():
        if n.cidr.version == 4 and n.cidr not in seen_cidrs:
            out.append(("info", f"{n.name} ({n.cidr}) isn't on the gateway yet"))
    return out
