"""Compare what a Proxmox node says about its guests with the guests' files.

The files are the source of truth: a difference is drift. It is reported, never adopted here.
Only observed facts that the file lacks (the VMID) are filled in.
"""

from bastet.core.changes import Change
from bastet.core.frontmatter import Document, set_keys
from bastet.core.inventory import Inventory
from bastet.core.links import link_target


def _bare(ip: str) -> str:
    return str(ip).split("/", 1)[0].strip()


def guest_drift(inv: Inventory, node: Document, guests: list[dict]) -> tuple[dict[str, list[str]], list[Change]]:
    """For guests of `node` that are in the inventory: drift messages per guest (empty list = in agreement),
    plus changes that add a missing `vmid`."""
    by_vmid = {str(d.data.get("vmid")): d for d in inv.of_kind("host") if d.data.get("vmid") is not None}
    drift: dict[str, list[str]] = {}
    changes: list[Change] = []
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
        if doc.data.get("vmid") is None:
            text = doc.path.read_text(encoding="utf-8")
            changes.append(Change(doc.path, text, set_keys(text, {"vmid": g["vmid"]}, doc.path)))
    return drift, changes
