"""Mermaid maps generated from the files: cabling (from links) and networks (from the lab file and host addresses)."""

from __future__ import annotations

import ipaddress

from bastet.core.cabling import _owner
from bastet.core.inventory import Inventory, _bare_ip
from bastet.core.links import link_target
from bastet.core.networks import lab_networks, network_of
from bastet.core.render import _address, _label


def _edges(inv: Inventory) -> list[tuple[str, str, str]]:
    out = []
    for doc in [*inv.of_kind("host"), *inv.of_kind("hardware")]:
        links = doc.data.get("links")
        for link in links if isinstance(links, list) else []:
            target = link_target(link.get("to")) if isinstance(link, dict) else None
            if not target:
                continue
            label = f"{link.get('port')} ↔ {link.get('to_port')}" + (f" · {link['speed']}" if link.get("speed") else "")
            out.append((_owner(inv, doc), target, label))
    return out


def cabling_map(inv: Inventory, around: str | None = None) -> str:
    edges = _edges(inv)
    if around:
        me = around.lower()
        near = {me} | {b.lower() for a, b, _ in edges if a.lower() == me} | {a.lower() for a, b, _ in edges if b.lower() == me}
        edges = [e for e in edges if e[0].lower() in near and e[1].lower() in near]
    if not edges:
        return ""
    names = sorted({n for a, b, _ in edges for n in (a, b)}, key=str.lower)
    ids = {n.lower(): f"n{i}" for i, n in enumerate(names)}
    lines = ["```mermaid", "flowchart LR"]
    for n in names:
        doc = inv.get(n)
        detail = str(doc.data.get("type") or "") if doc else ""
        lines.append(f'  {ids[n.lower()]}["{_label(n)}<br/><small>{_label(detail)}</small>"]')
    for a, b, label in edges:
        lines.append(f'  {ids[a.lower()]} ---|"{_label(label)}"| {ids[b.lower()]}')
    lines.append("```")
    return "\n".join(lines) + "\n"


def networks_map(inv: Inventory) -> str:
    nets = lab_networks(inv)
    if not nets:
        return ""
    groups: dict[str, list] = {n: [] for n in nets}
    elsewhere = []
    for h in inv.of_kind("host"):
        bare = _bare_ip(h.data.get("ip")) if h.data.get("ip") else None
        if not bare:
            continue
        net = network_of(nets, bare)
        (groups[net.name] if net else elsewhere).append(h)
    lines, n = ["```mermaid", "flowchart TB"], 0
    for i, (name, members) in enumerate([*groups.items(), ("Elsewhere", elsewhere)]):
        if name == "Elsewhere" and not members:
            continue
        net = nets.get(name) if name in groups else None
        title = name if net is None else " · ".join(x for x in (name, str(net.cidr), f"VLAN {net.vlan}" if net.vlan else "") if x)
        lines.append(f'  subgraph net{i}["{_label(title)}"]')
        lines.append("    direction LR")
        for h in sorted(members, key=lambda d: (ipaddress.ip_address(_bare_ip(d.data["ip"])).version, ipaddress.ip_address(_bare_ip(d.data["ip"])))):
            lines.append(f'    h{n}["{_label(h.name)}<br/><small>{_label(_address(h) or "")}</small>"]')
            n += 1
        lines.append("  end")
    lines.append("```")
    return "\n".join(lines) + "\n"
