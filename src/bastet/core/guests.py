"""Compare what a Proxmox node says about its guests with the guests' files.

The files are the source of truth: a difference is drift. It is reported, never adopted here.
Only observed facts that the file lacks (the VMID) are filled in -- into the guest's facts note,
since a guest's own gather never observes its own vmid (that's the node's doing).
"""

from bastet.core.changes import Change
from bastet.core.factsnote import facts_change
from bastet.core.frontmatter import Document
from bastet.core.hosttypes import HostType
from bastet.core.hostview import host_data
from bastet.core.inventory import Inventory
from bastet.core.links import link_target


def _bare(ip: str) -> str:
    return str(ip).split("/", 1)[0].strip()


def guest_drift(
    inv: Inventory, node: Document, guests: list[dict], types: dict[str, HostType], gathered: str
) -> tuple[dict[str, list[str]], dict[str, Change]]:
    """For guests of `node` that are in the inventory: drift messages per guest (empty list = in agreement),
    plus a facts-note Change per guest newly matched by vmid, keyed by guest name (lowercase)."""
    by_vmid: dict[str, Document] = {}
    for d in inv.of_kind("host"):
        vmid = host_data(inv, d, types).get("vmid")
        if vmid is not None:
            by_vmid[str(vmid)] = d
    drift: dict[str, list[str]] = {}
    changes: dict[str, Change] = {}
    for g in guests:
        doc = by_vmid.get(str(g.get("vmid"))) or inv.get(str(g.get("name", "")))
        if doc is None or doc.data.get("bastet") != "host":
            continue
        items: list[str] = []
        file_node = link_target(doc.data.get("runs_on"))
        if file_node and file_node.lower() != node.name.lower():
            items.append(f"runs on [[{node.name}]] according to Proxmox, file says [[{file_node}]]")
        conf_ip = g.get("conf_ip")
        file_ip = str(doc.data.get("ip") or "")
        if conf_ip and conf_ip != "dhcp":
            if _bare(conf_ip) != _bare(file_ip):
                items.append(f"ip: file says {file_ip or '(none)'}, Proxmox has {conf_ip}")
        elif conf_ip == "dhcp" and file_ip and file_ip.lower() != "dhcp":
            items.append(f"ip: file says {file_ip}, Proxmox uses DHCP")
        drift[doc.name] = items
        if host_data(inv, doc, types).get("vmid") is None:
            merged = {**inv.facts_for(doc.name), "vmid": g["vmid"]}
            change = facts_change(inv.root, doc.name, merged, gathered)
            if change is not None:
                changes[doc.name.lower()] = change
    return drift, changes
