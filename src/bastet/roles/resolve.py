"""Which roles reach a host, and with what values: precedence and merging."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.core.frontmatter import Document
from bastet.core.hosttypes import HostType
from bastet.core.hostview import host_data
from bastet.core.inventory import Inventory
from bastet.core.links import link_target
from bastet.core.osdefaults import defaults_for
from bastet.core.osinfo import os_id
from bastet.engine.run import ConflictError
from bastet.roles.contract import RESERVED, Option, RoleDef, check_overrides, check_relations, check_values, with_defaults
from bastet.roles.expr import host_facts, truthy


@dataclass
class Source:
    role: str
    label: str
    rank: tuple
    values: dict
    doc: Document | None = None
    file: Path | None = None  # for a source that is a shipped file rather than a note (an OS default)
    overrides: object = None  # the note's raw `overrides:`, checked and applied by resolve()
    overridden: frozenset[str] = frozenset()  # the options whose value here came from a matching override entry


@dataclass
class Applied:
    role: RoleDef
    values: dict
    sources: list[Source] = field(default_factory=list)
    origins: dict[str, str] = field(default_factory=dict)
    secret: bool = False  # at least one option resolve_refs() replaced with a decrypted secret value
    secret_options: frozenset[str] = frozenset()  # their names, so a Markdown role marks only what uses them


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
            values = dict(values or {})
            out.setdefault(role, []).append(Source(role, f"type {host_type.name}", (1,), values, overrides=values.pop("overrides", None)))
    os_defaults = defaults_for(os_id(host_data(inv, host, types)))
    if os_defaults is not None:  # below the lab: the lab, the type default, groups and hosts all override it
        for role, values in os_defaults.roles.items():
            values = dict(values or {})
            out.setdefault(role, []).append(Source(role, f"OS default ({os_defaults.name})", (-1,), values,
                                              file=os_defaults.path, overrides=values.pop("overrides", None)))
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
        out.setdefault(role, []).append(Source(role, label, rank, values, doc, overrides=doc.data.get("overrides")))
    return out


_MISSING = object()  # a key a note doesn't mention; a null (None) is a value that opts out and merges by rank


def _merge(opt: Option, a, b, path: str, clash):
    if a is _MISSING:
        return b
    if b is _MISSING:
        return a
    if a is None or b is None:
        if clash is not None and a != b:
            clash(path, opt, a, b)
        return b
    if opt.type == "list":
        return a + [x for x in b if x not in a]
    if opt.type == "map":
        out = dict(a)
        for k, v in b.items():
            out[k] = _merge(opt.items, a.get(k, _MISSING), v, f"{path}.{k}", clash)
        return out
    if opt.type == "object":
        out = dict(a)
        for k, v in b.items():
            out[k] = _merge(opt.fields[k], a.get(k, _MISSING), v, f"{path}.{k}", clash)
        return out
    if clash is not None and a != b:
        clash(path, opt, a, b)
    return b


def _merge_values(role: RoleDef, a: dict, b: dict, clash=None) -> dict:
    keys = list(a) + [k for k in b if k not in a]
    return {k: _merge(role.options[k], a.get(k, _MISSING), b.get(k, _MISSING), k, clash) for k in keys}


def _cleared(opt: Option, value):
    """Drop the nulls left after merging (inside maps and objects too): those options are unset."""
    if opt.type == "map" and isinstance(value, dict):
        return {k: _cleared(opt.items, v) for k, v in value.items() if v is not None}
    if opt.type == "object" and isinstance(value, dict):
        return {k: _cleared(opt.fields[k], v) for k, v in value.items() if v is not None}
    return value


def _apply_overrides(source: Source, entries: list[tuple[str, dict]], ctx, file: Path | None) -> None:
    """Let each matching entry (listing order) replace the note's own value of its options, at the note's rank."""
    changed: set[str] = set()
    for i, (when, values) in enumerate(entries):
        try:
            matches = truthy(when, ctx())
        except BastetError as exc:
            raise BastetError(f"{source.label} note: overrides[{i}]: {exc.message}", file=file, key="overrides") from None
        if matches:
            source.values.update(values)
            changed |= set(values)
    source.overridden = frozenset(changed)


def resolve(inv: Inventory, host: Document, types: dict[str, HostType], roles: dict[str, RoleDef]) -> list[Applied]:
    applied: list[Applied] = []
    host_type = types.get(str(host.data.get("type")))
    if host_type is not None and not host_type.managed:
        return applied  # configured elsewhere (e.g. the UniFi controller); roles never reach it
    facts: dict = {}

    def facts_ctx() -> dict:  # built on the first `overrides:` entry that needs it
        if not facts:
            host_type = types.get(str(host.data.get("type")))
            facts["host"] = host_facts(host.name, str(host.data.get("type", "")), host_data(inv, host, types),
                                       bool(host_type and host_type.physical))
            facts["lab"] = dict(inv.lab.data) if inv.lab else {}
        return facts

    for name, sources in sources_for(inv, host, types).items():
        role = roles.get(name)
        if role is None:
            src = next((s for s in sources if s.doc is not None), sources[0])
            raise BastetError(f"unknown role {name!r} (roles: {', '.join(sorted(roles))})",
                              file=src.doc.path if src.doc else src.file, key="role")
        for s in sources:
            file = s.doc.path if s.doc else s.file
            s.values = check_values(role, s.values, s.label, file=file)
            _apply_overrides(s, check_overrides(role, s.overrides, s.label, file=file), facts_ctx, file)
        merged: dict = {}
        origins: dict[str, str] = {}
        for rank in sorted({s.rank for s in sources}):
            level = [s for s in sources if s.rank == rank]

            def clash(path, opt, a, b, level=level):
                shown = "(secret)" if opt.secret else f"{a!r} vs {b!r}"
                raise ConflictError(f"{name}: {' and '.join(s.label for s in level)} set {path} differently ({shown})")  # noqa: B023 (only called within this loop pass)

            combined: dict = {}
            for s in level:
                combined = _merge_values(role, combined, s.values, clash)
            merged = _merge_values(role, merged, combined)
            for key in combined:
                origins[key] = ", ".join(s.label + (" (override)" if key in s.overridden else "")
                                         for s in level if key in s.values)
        merged = {k: _cleared(role.options[k], v) for k, v in merged.items() if v is not None}
        origins = {k: v for k, v in origins.items() if k in merged}
        files = [s.doc.path if s.doc else s.file for s in sources if s.values]
        check_relations(role, merged, file=files[-1] if files else None)  # the notes' own values, before defaults
        applied.append(Applied(role, with_defaults(role, merged), sources, origins))
    return sorted(applied, key=lambda a: a.role.name)
