import ipaddress
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.core.frontmatter import Document, parse_document
from bastet.core.hosttypes import HostType
from bastet.core.links import link_target

KINDS = ("lab", "host", "hardware", "group", "location", "role")
SKIP_DIRS = {".git", ".obsidian", ".trash", ".bastet"}
LINK_FIELDS = {
    "host": ("runs_on", "location", "groups"),
    "hardware": ("installed_in", "location"),
    "location": ("parent",),
}
HARDWARE_STATUSES = ("in-service", "spare", "failed", "retired", "sold")


@dataclass
class Problem:
    severity: str
    error: BastetError

    def __str__(self) -> str:
        return f"{self.severity}: {self.error}"


@dataclass
class Inventory:
    root: Path
    objects: dict[str, Document] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)
    role_files: list[Document] = field(default_factory=list)

    def get(self, name: str) -> Document | None:
        return self.objects.get(name.lower())

    def of_kind(self, kind: str) -> list[Document]:
        docs = [d for d in self.objects.values() if d.data.get("bastet") == kind]
        return sorted(docs, key=lambda d: d.name.lower())

    @property
    def lab(self) -> Document | None:
        labs = self.of_kind("lab")
        return labs[0] if labs else None

    @property
    def errors(self) -> list[Problem]:
        return [p for p in self.problems if p.severity == "error"]

    def linking_to(self, name: str) -> list[tuple[Document, str]]:
        wanted = name.lower()
        found = []
        for doc in self.objects.values():
            for key, value in doc.data.items():
                values = value if isinstance(value, list) else [value]
                if any((link_target(v) or "").lower() == wanted for v in values):
                    found.append((doc, key))
        return sorted(found, key=lambda item: (item[0].name.lower(), item[1]))


def markdown_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        yield path


def _add(inv: Inventory, severity: str, message: str, doc: Document, key: str | None = None) -> None:
    line = doc.key_lines.get(key) if key else None
    inv.problems.append(Problem(severity, BastetError(message, file=doc.path, line=line, key=key)))


def _bare_ip(value: object) -> str | None:
    """The address part of an ip value, or None for non-addresses such as `dhcp`."""
    text = str(value).split("/", 1)[0].strip()
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return None
    return text


def _check_host(inv: Inventory, doc: Document, types: dict[str, HostType], ips: dict[str, Document]) -> None:
    type_name = doc.data.get("type")
    if type_name is None:
        _add(inv, "error", "missing 'type'", doc, "bastet")
    elif type_name not in types:
        known = ", ".join(sorted(types))
        _add(inv, "error", f"unknown host type '{type_name}' (known: {known})", doc, "type")
    else:
        for name in types[type_name].minimal:
            if doc.data.get(name) in (None, ""):
                _add(inv, "error", f"host type '{type_name}' needs '{name}'", doc, "type")
    connection = doc.data.get("connection")
    if connection is not None and connection not in ("local", "ssh"):
        _add(inv, "error", f"connection '{connection}' is not 'local' or 'ssh'", doc, "connection")
    ip = doc.data.get("ip")
    if ip:
        bare = _bare_ip(ip)
        if bare is None:
            if str(ip).strip().lower() != "dhcp":
                _add(inv, "error", f"ip '{ip}' is not an address or 'dhcp'", doc, "ip")
        elif bare in ips:
            _add(inv, "error", f"address {bare} is also used by {ips[bare].path}", doc, "ip")
        else:
            ips[bare] = doc


def _check_hardware(inv: Inventory, doc: Document) -> None:
    if not doc.data.get("category"):
        _add(inv, "error", "missing 'category'", doc, "bastet")
    status = doc.data.get("status")
    if status is not None and status not in HARDWARE_STATUSES:
        _add(inv, "error", f"status '{status}' is not one of: {', '.join(HARDWARE_STATUSES)}", doc, "status")


def load_inventory(root: Path, types: dict[str, HostType]) -> Inventory:
    inv = Inventory(root=root)
    for path in markdown_files(root):
        try:
            doc = parse_document(path.read_text(encoding="utf-8"), path)
        except BastetError as exc:
            exc.message += " (ignored; if this is a Bastet file, fix it)"
            inv.problems.append(Problem("warning", BastetError(exc.message, file=exc.file, line=exc.line)))
            continue
        except (OSError, UnicodeDecodeError) as exc:
            inv.problems.append(Problem("warning", BastetError(f"cannot read: {exc.__class__.__name__}", file=path)))
            continue
        if doc is None or "bastet" not in doc.data:
            continue
        kind = doc.data["bastet"]
        if kind not in KINDS:
            _add(inv, "error", f"unknown kind '{kind}' (known: {', '.join(KINDS)})", doc, "bastet")
            continue
        if kind == "role":
            inv.role_files.append(doc)
            continue
        existing = inv.objects.get(doc.name.lower())
        if existing is not None:
            _add(inv, "error", f"duplicate name '{doc.name}': also {existing.path}", doc)
            continue
        inv.objects[doc.name.lower()] = doc

    labs = inv.of_kind("lab")
    for extra in labs[1:]:
        _add(inv, "error", f"more than one lab file (also {labs[0].path})", extra)

    ips: dict[str, Document] = {}
    for doc in sorted(inv.objects.values(), key=lambda d: str(d.path)):
        kind = doc.data["bastet"]
        if kind == "host":
            _check_host(inv, doc, types, ips)
        elif kind == "hardware":
            _check_hardware(inv, doc)
        for key in LINK_FIELDS.get(kind, ()):
            value = doc.data.get(key)
            if value is None:
                continue
            for item in value if isinstance(value, list) else [value]:
                target = link_target(item)
                if target is None:
                    _add(inv, "error", f'expected a link like "[[name]]", got {item!r}', doc, key)
                elif inv.get(target) is None:
                    _add(inv, "warning", f"links to [[{target}]], which isn't in the inventory", doc, key)
    for doc in inv.role_files:
        if not doc.data.get("role"):
            _add(inv, "error", "a role file needs `role:` (which role)", doc, "role")
        target = link_target(doc.data.get("applies_to"))
        if target is None:
            _add(inv, "warning", 'a role file needs `applies_to: "[[host, group or lab]]"`', doc, "applies_to")
        elif inv.get(target) is None or inv.get(target).data.get("bastet") not in ("host", "group", "lab"):
            _add(inv, "warning", f"applies_to [[{target}]], which isn't a host, group or the lab", doc, "applies_to")
    return inv
