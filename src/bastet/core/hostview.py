"""The one view onto a host's data: its facts note overlaid with its own declared keys.

Readers (OS detection, roles, cabling, summaries, the dashboard, `show`, connect, host-key pinning)
go through `host_data` instead of reading `doc.data` directly, so a stale fact left on an old host
note can never beat a fresh one from the facts note.
"""

from bastet.core.frontmatter import Document
from bastet.core.hosttypes import HostType
from bastet.core.inventory import Inventory

# Structural host-note keys: never fact-nature, whatever the host type says (most aren't declared
# under a type's `fields:` at all, so this is mostly a safety net).
IDENTITY_KEYS = ("type", "groups", "runs_on", "location", "connection", "gather", "address", "ip", "state", "hostname")


def _fields(doc: Document, types: dict[str, HostType]) -> dict[str, str]:
    host_type = types.get(str(doc.data.get("type"))) or types.get("unknown")
    return host_type.fields if host_type is not None else {}


def host_data(inv: Inventory, doc: Document, types: dict[str, HostType]) -> dict:
    fields = _fields(doc, types)
    data = dict(inv.facts_for(doc.name))
    for key, value in doc.data.items():
        if key not in IDENTITY_KEYS and fields.get(key) == "fact":
            continue
        data[key] = value
    if "ssh_host_key" not in data and doc.data.get("ssh_host_key"):
        data["ssh_host_key"] = doc.data["ssh_host_key"]
    return data


def stale_fact_keys(doc: Document, types: dict[str, HostType]) -> list[str]:
    fields = _fields(doc, types)
    return [key for key in doc.data if key not in IDENTITY_KEYS and fields.get(key) == "fact"]
