"""Which roles reach a host, and with what values: precedence and merging."""

from __future__ import annotations

from dataclasses import dataclass, field

from bastet.core.errors import BastetError
from bastet.core.frontmatter import Document
from bastet.core.hosttypes import HostType
from bastet.core.hostview import host_data
from bastet.core.inventory import Inventory
from bastet.core.links import link_target
from bastet.core.osinfo import os_id
from bastet.engine.run import ConflictError
from bastet.roles.contract import RESERVED, Option, RoleDef, check_values, with_defaults


@dataclass
class Source:
    role: str
    label: str
    rank: tuple
    values: dict
    doc: Document | None = None


@dataclass
class Applied:
    role: RoleDef
    values: dict
    sources: list[Source] = field(default_factory=list)
    origins: dict[str, str] = field(default_factory=dict)
    secret: bool = False  # at least one option resolve_refs() replaced with a decrypted secret value


def _links(value) -> list[str]:
    items = value if isinstance(value, list) else ([value] if value else [])
    return [t for t in (link_target(i) for i in items) if t]


def _matches(inv: Inventory, group: Document, host: Document, types: dict[str, HostType]) -> bool:
    """A group's `match:` rule (os, type): hosts that fit every key belong to it without listing it."""
    if "match" not in group.data:
        return False
    rule = group.data.get("match")
    if not isinstance(rule, dict) or not rule:
        raise BastetError("match: expected a rule like {os: arch} or {type: proxmox}", file=group.path, key="match")
    unknown = set(rule) - {"os", "type"}
    if unknown:
        raise BastetError(f"match: unknown key {', '.join(sorted(map(str, unknown)))} (known: os, type)",
                          file=group.path, key="match")
    data = host_data(inv, host, types)
    have = {"os": os_id(data), "type": str(data.get("type") or "")}
    for key, wanted in rule.items():
        options = [str(w).lower() if key == "os" else str(w) for w in (wanted if isinstance(wanted, list) else [wanted])]
        if have[key] not in options:
            return False
    return True


def group_distances(inv: Inventory, host: Document, types: dict[str, HostType]) -> dict[str, int]:
    """Groups the host belongs to, directly (1) or through nesting (2, 3…); the nearest path counts."""
    dist: dict[str, int] = {}
    frontier = [(name, 1) for name in _links(host.data.get("groups"))]
    frontier += [(g.name, 1) for g in inv.of_kind("group") if _matches(inv, g, host, types)]
    while frontier:
        name, d = frontier.pop(0)
        doc = inv.get(name)
        if doc is None or doc.data.get("bastet") != "group":
            continue
        key = doc.name.lower()
        if key in dist and dist[key] <= d:
            continue
        dist[key] = d
        frontier += [(g, d + 1) for g in _links(doc.data.get("groups"))]
    return dist


def sources_for(inv: Inventory, host: Document, types: dict[str, HostType]) -> dict[str, list[Source]]:
    out: dict[str, list[Source]] = {}
    host_type = types.get(str(host.data.get("type")))
    if host_type is not None:
        for role, values in host_type.roles.items():
            out.setdefault(role, []).append(Source(role, f"type {host_type.name}", (1,), dict(values or {})))
    dist = group_distances(inv, host, types)
    for doc in inv.role_files:
        target = inv.get(link_target(doc.data.get("applies_to")) or "")
        if target is None:
            continue
        kind = target.data.get("bastet")
        if kind == "lab":
            rank, label = (0,), "lab"
        elif kind == "host" and target.name.lower() == host.name.lower():
            rank, label = (3,), f"host {host.name}"
        elif kind == "group" and target.name.lower() in dist:
            try:
                priority = int(target.data.get("priority") or 0)
            except (TypeError, ValueError):
                raise BastetError("priority must be a whole number", file=target.path, key="priority") from None
            rank = (2, -dist[target.name.lower()], priority)
            label = f"group {target.name}"
        else:
            continue
        role = str(doc.data.get("role"))
        values = {k: v for k, v in doc.data.items() if k not in RESERVED}
        out.setdefault(role, []).append(Source(role, label, rank, values, doc))
    return out


def _merge(opt: Option, a, b, path: str, clash):
    if a is None:
        return b
    if b is None:
        return a
    if opt.type == "list":
        return a + [x for x in b if x not in a]
    if opt.type == "map":
        out = dict(a)
        for k, v in b.items():
            out[k] = _merge(opt.items, a.get(k), v, f"{path}.{k}", clash)
        return out
    if opt.type == "object":
        out = dict(a)
        for k, v in b.items():
            out[k] = _merge(opt.fields[k], a.get(k), v, f"{path}.{k}", clash)
        return out
    if clash is not None and a != b:
        clash(path, opt, a, b)
    return b


def _merge_values(role: RoleDef, a: dict, b: dict, clash=None) -> dict:
    keys = list(a) + [k for k in b if k not in a]
    return {k: _merge(role.options[k], a.get(k), b.get(k), k, clash) for k in keys}


def resolve(inv: Inventory, host: Document, types: dict[str, HostType], roles: dict[str, RoleDef]) -> list[Applied]:
    applied: list[Applied] = []
    host_type = types.get(str(host.data.get("type")))
    if host_type is not None and not host_type.managed:
        return applied  # configured elsewhere (e.g. the UniFi controller); roles never reach it
    for name, sources in sources_for(inv, host, types).items():
        role = roles.get(name)
        if role is None:
            src = next((s for s in sources if s.doc is not None), sources[0])
            raise BastetError(f"unknown role {name!r} (roles: {', '.join(sorted(roles))})",
                              file=src.doc.path if src.doc else None, key="role")
        for s in sources:
            s.values = check_values(role, s.values, s.label, file=s.doc.path if s.doc else None)
        merged: dict = {}
        origins: dict[str, str] = {}
        for rank in sorted({s.rank for s in sources}):
            level = [s for s in sources if s.rank == rank]

            def clash(path, opt, a, b, level=level):
                shown = "(secret)" if opt.secret else f"{a!r} vs {b!r}"
                raise ConflictError(f"{name}: {' and '.join(s.label for s in level)} set {path} differently ({shown})")

            combined: dict = {}
            for s in level:
                combined = _merge_values(role, combined, s.values, clash)
            merged = _merge_values(role, merged, combined)
            for key in combined:
                origins[key] = ", ".join(s.label for s in level if key in s.values)
        applied.append(Applied(role, with_defaults(role, merged), sources, origins))
    return sorted(applied, key=lambda a: a.role.name)
