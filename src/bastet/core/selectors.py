"""Host selectors: the names, patterns and groups `run`, `show` and friends accept on the command line."""

from __future__ import annotations

import fnmatch

from bastet.core.errors import BastetError, did_you_mean
from bastet.core.frontmatter import Document
from bastet.core.hosttypes import HostType
from bastet.core.inventory import Inventory
from bastet.roles.resolve import group_distances

GLOB_CHARS = "*?["


def is_selector(token: str) -> bool:
    """True for anything that isn't a plain, exact name: `@group`, `@type`, `@lab`, or a glob."""
    return token.startswith("@") or any(c in token for c in GLOB_CHARS)


def _present_hosts(inv: Inventory) -> list[Document]:
    return [d for d in inv.of_kind("host") if d.data.get("state", "present") != "destroyed"]


def _group_doc(inv: Inventory, name: str) -> Document | None:
    for g in inv.of_kind("group"):
        if g.name.lower() == name.lower():
            return g
    return None


def _at_selector(inv: Inventory, types: dict[str, HostType], name: str) -> list[Document]:
    if name.lower() == "lab":
        return _present_hosts(inv)
    if name in types:
        return [d for d in _present_hosts(inv) if str(d.data.get("type")) == name]
    group = _group_doc(inv, name)
    if group is not None:
        return [d for d in _present_hosts(inv) if group.name.lower() in group_distances(inv, d, types)]

    # Try to suggest a close match
    candidates = list(types.keys()) + [g.name for g in inv.of_kind("group")]
    suggestion = did_you_mean(name, candidates)
    if suggestion:
        msg = f"no group or type named '{name}'; {suggestion}"
    else:
        known_groups = ", ".join(sorted(g.name for g in inv.of_kind("group"))) or "none"
        known_types = ", ".join(sorted(types)) or "none"
        msg = f"no group or type named '{name}' (groups: {known_groups}; types: {known_types})"
    raise BastetError(msg)


def _glob_selector(inv: Inventory, pattern: str) -> list[Document]:
    matched = [d for d in _present_hosts(inv) if fnmatch.fnmatchcase(d.name, pattern)]
    if not matched:
        raise BastetError(f"'{pattern}' matches no host")
    return matched


def _exact_selector(inv: Inventory, name: str) -> list[Document]:
    doc = inv.get(name)
    if doc is None or doc.data.get("bastet") != "host":
        # Try to suggest a close match
        host_names = [d.name for d in inv.of_kind("host")]
        suggestion = did_you_mean(name, host_names)
        if suggestion:
            msg = f"no host named '{name}'; {suggestion}"
        else:
            msg = f"no host named '{name}' in the inventory"
        raise BastetError(msg)
    return [doc]


def _resolve_one(inv: Inventory, types: dict[str, HostType], token: str) -> list[Document]:
    if token.startswith("@"):
        return _at_selector(inv, types, token[1:])
    if any(c in token for c in GLOB_CHARS):
        return _glob_selector(inv, token)
    return _exact_selector(inv, token)


def _inventory_order(inv: Inventory, docs: set) -> list[Document]:
    return [d for d in inv.of_kind("host") if d.name.lower() in docs]


def select_hosts(
    inv: Inventory, types: dict[str, HostType], selectors: list[str], exclude: list[str]
) -> list[Document]:
    """Resolve host selectors (see module docstring forms) into a deduplicated, inventory-ordered list.

    No selectors means every host that isn't `state: destroyed`; a destroyed host is only ever reached
    by naming it exactly.
    """
    if not selectors:
        chosen_names = {d.name.lower() for d in _present_hosts(inv)}
    else:
        chosen_names: set = set()
        for token in selectors:
            chosen_names.update(d.name.lower() for d in _resolve_one(inv, types, token))
    if exclude:
        excluded_names: set = set()
        for token in exclude:
            excluded_names.update(d.name.lower() for d in _resolve_one(inv, types, token))
        chosen_names -= excluded_names
    return _inventory_order(inv, chosen_names)
