"""Compare what a Proxmox node says about its guests with the guests' files.

The files are the source of truth: a difference is drift. It is reported, never adopted here.
The VMID is the one exception: it's observed by the node, never by the guest's own gather, so it's
kept current here -- filled in when missing, and overwritten when the node now reports a different one
(a guest recreated under a new vmid).
"""

from collections.abc import Callable

from bastet.core.frontmatter import Document
from bastet.core.hosttypes import HostType
from bastet.core.hostview import host_data
from bastet.core.inventory import Inventory
from bastet.core.links import link_target


def _bare(ip: str) -> str:
    return str(ip).split("/", 1)[0].strip()


def guest_drift(
    inv: Inventory,
    node: Document,
    guests: list[dict],
    types: dict[str, HostType],
    *,
    facts_for: Callable[[str], dict] | None = None,
) -> tuple[dict[str, list[str]], dict[str, object]]:
    """For guests of `node` that are in the inventory: drift messages per guest (empty list = in
    agreement), plus the vmid the node reports for any guest whose facts note doesn't already hold it,
    keyed by the guest's own name.

    A guest is matched by name first, falling back to its last-known vmid only for the rename case (the
    file's name hasn't caught up yet). `facts_for` is what the guest's facts note holds -- it defaults to
    `inv.facts_for`, but a caller merging several sources into one facts note in a single run (gather.py)
    passes its own accumulator, so a vmid already picked up earlier in the same run still counts.
    """
    facts_for = facts_for or inv.facts_for
    by_vmid: dict[str, Document] = {}
    for d in inv.of_kind("host"):
        vmid = host_data(inv, d, types).get("vmid")
        if vmid is not None:
            by_vmid[str(vmid)] = d
    # Guests that have their own name in this list must not be stolen by another guest's stale vmid
    # fallback -- e.g. git1 recreated under a new vmid, its old one now reported for a different guest.
    named_here = {str(g.get("name", "")).lower() for g in guests}
    drift: dict[str, list[str]] = {}
    vmid_updates: dict[str, object] = {}
    for g in guests:
        doc = inv.get(str(g.get("name", "")))
        if doc is None:
            candidate = by_vmid.get(str(g.get("vmid")))
            if candidate is not None and candidate.name.lower() not in named_here:
                doc = candidate
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
        new_vmid = g.get("vmid")
        if new_vmid is not None and str(facts_for(doc.name).get("vmid")) != str(new_vmid):
            vmid_updates[doc.name] = new_vmid
    return drift, vmid_updates
