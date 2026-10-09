"""The one view onto a host's data: its facts note overlaid with its own declared keys.

Readers (OS detection, roles, cabling, summaries, the dashboard, `show`, connect, host-key pinning)
go through `host_data` instead of reading `doc.data` directly, so a stale fact left on an old host
note can never beat a fresh one from the facts note.
"""

from bastet.core.cabling import merge_links
from bastet.core.factsnote import OBSERVED_BY_OTHERS
from bastet.core.frontmatter import Document
from bastet.core.hardware import HARDWARE_YOURS
from bastet.core.hosttypes import HostType
from bastet.core.inventory import Inventory

# Structural host-note keys: never fact-nature, whatever the host type says (most aren't declared
# under a type's `fields:` at all, so this is mostly a safety net).
IDENTITY_KEYS = ("type", "groups", "runs_on", "location", "connection", "gather", "address", "ip", "state", "hostname")
# A key recorded only on an old host note, from before the facts note existed (or, for the
# OBSERVED_BY_OTHERS keys, from before something else ever observed it): still honoured as a fallback
# for matching, never silently re-trusted as Bastet's own. `links` has its own per-port merge below,
# so including it here is a no-op, not a second mechanism.
FALLBACK_KEYS = ("ssh_host_key", *OBSERVED_BY_OTHERS)


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
    for key in FALLBACK_KEYS:
        if key not in data and doc.data.get(key) is not None:
            data[key] = doc.data[key]
    observed_links = inv.facts_for(doc.name).get("links")
    if isinstance(observed_links, list):
        merged, _ = merge_links(doc.data.get("links"), observed_links)
        if merged is not None:
            data["links"] = merged
    return data


def stale_fact_keys(doc: Document, types: dict[str, HostType]) -> list[str]:
    fields = _fields(doc, types)
    return [key for key in doc.data if key not in IDENTITY_KEYS and fields.get(key) == "fact"]


# Structural keys on a hardware note that are never a stale gathered key, whatever they hold:
# `bastet`/`category` are yours by definition, the rest are Obsidian/organisational, not facts.
HARDWARE_STRUCTURAL_KEYS = ("bastet", "category", "cssclasses", "tags", "aliases", "links")
HARDWARE_RETIRED_STATUSES = ("failed", "retired", "sold", "spare")


def hardware_data(inv: Inventory, doc: Document) -> dict:
    """A hardware item's facts note overlaid with its own declared (yours) fields.

    A gathered key still hand-typed on the item's own note (a spare's serial, a never-regathered
    item's model and size, or anything from before the facts-note split) is kept as a fallback for
    whatever the facts note doesn't hold -- it's only truly stale, and reported as such, once Bastet's
    own note has its own value for that key (`stale_hardware_keys`/`_check_stale_hardware`).
    """
    data = dict(inv.facts_for(doc.name))
    for key in (*HARDWARE_YOURS, "category"):
        if key in doc.data:
            data[key] = doc.data[key]
    if "links" in doc.data:  # hand-declared, kept even before anything's ever been observed
        data["links"] = doc.data["links"]
    observed_links = inv.facts_for(doc.name).get("links")
    if isinstance(observed_links, list):
        merged, _ = merge_links(doc.data.get("links"), observed_links)
        if merged is not None:
            data["links"] = merged
    for key, value in doc.data.items():
        if key not in HARDWARE_YOURS and key not in HARDWARE_STRUCTURAL_KEYS and key not in data:
            data[key] = value
    return data


def stale_hardware_keys(doc: Document) -> list[str]:
    return [key for key in doc.data if key not in HARDWARE_YOURS and key not in HARDWARE_STRUCTURAL_KEYS]


def missing_warning(inv: Inventory, doc: Document) -> str | None:
    """The persistent "hasn't been seen" warning for a hardware item, or None.

    Computed fresh from `missing_since` (stored in the item's facts note) and `status` (yours) every
    time, so it survives a plain refresh and clears the moment you set the status yourself.
    """
    since = hardware_data(inv, doc).get("missing_since")
    status = doc.data.get("status") or None
    if since and status not in HARDWARE_RETIRED_STATUSES:
        return f"{doc.name} hasn't been seen since {since} (pulled, failed or moved?)"
    return None
