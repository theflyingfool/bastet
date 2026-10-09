import ipaddress
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.core.factsnote import FACTS_DIR, META_KEYS, facts_path, hardware_facts_path
from bastet.core.frontmatter import Document, parse_document
from bastet.core.hosttypes import HostType
from bastet.core.links import link_target

KINDS = ("lab", "host", "hardware", "group", "location", "role", "secret", "facts")
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
    secrets: list[Document] = field(default_factory=list)
    facts: dict[str, Document] = field(default_factory=dict)

    def get(self, name: str) -> Document | None:
        return self.objects.get(name.lower())

    def facts_for(self, name: str) -> dict:
        """The host's gathered facts (from its facts note), or {} when it has none."""
        doc = self.facts.get(name.lower())
        if doc is None:
            return {}
        return {k: v for k, v in doc.data.items() if k not in META_KEYS}

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


FALLBACK_KEYS_WITH_NO_EARLY_REMOVE = ("ssh_host_key", "vmid")


def _check_stale_facts(inv: Inventory, doc: Document, types: dict[str, HostType]) -> None:
    from bastet.core.hostview import stale_fact_keys  # hostview builds on inventory
    from bastet.core.units import same_value

    stale = stale_fact_keys(doc, types)
    if not stale:
        return
    facts = inv.facts_for(doc.name)
    # ssh_host_key and vmid are also honoured as a fallback (hostview.FALLBACK_KEYS) until the facts
    # note has its own value: telling the user to remove one before that would silently undo the pin.
    removable = [
        key for key in stale
        if key not in FALLBACK_KEYS_WITH_NO_EARLY_REMOVE or (key in facts and same_value(key, facts[key], doc.data.get(key)))
    ]
    pending = [key for key in stale if key not in removable]
    note_path = f"{FACTS_DIR}/{doc.name} facts.md"
    parts = []
    if removable:
        parts.append(f"{', '.join(removable)} are gathered facts; they now live in {note_path} (remove them from this note)")
    if pending:
        parts.append(
            f"{', '.join(pending)} are gathered facts; they now live in {note_path} once gather runs "
            f"(kept here until then, so the next gather copies them in instead of losing them)"
        )
    message = " ".join(parts)
    line = doc.key_lines.get(stale[0])
    inv.problems.append(Problem("warning", BastetError(message, file=doc.path, line=line)))


def _check_host(inv: Inventory, doc: Document, types: dict[str, HostType], ips: dict[str, Document]) -> None:
    _check_stale_facts(inv, doc, types)
    type_name = doc.data.get("type")
    if type_name is None:
        _add(inv, "error", "missing 'type'", doc, "bastet")
    elif type_name not in types:
        known = ", ".join(sorted(types))
        if type_name == "proxmox-node":
            _add(inv, "error", f"unknown type '{type_name}' (renamed to proxmox)", doc, "type")
        else:
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


def _check_stale_hardware(inv: Inventory, doc: Document) -> None:
    """A gathered-looking key on a hardware note is only reported once Bastet's own facts note holds
    a value for it -- until then it's a legitimate hand-typed value (a spare's serial, a never-
    regathered item's model and size), kept quietly as a fallback (`hostview.hardware_data`)."""
    from bastet.core.hostview import stale_hardware_keys  # hostview builds on inventory

    stale = stale_hardware_keys(doc)
    if not stale:
        return
    facts = inv.facts_for(doc.name)
    removable = [key for key in stale if key in facts]
    if not removable:
        return
    note_path = hardware_facts_path(inv.root, doc.name).relative_to(inv.root).as_posix()
    message = f"{', '.join(removable)} are gathered facts; they now live in {note_path} (remove them from this note)"
    line = doc.key_lines.get(removable[0])
    inv.problems.append(Problem("warning", BastetError(message, file=doc.path, line=line)))


def _check_hardware(inv: Inventory, doc: Document) -> None:
    _check_stale_hardware(inv, doc)
    if not doc.data.get("category"):
        _add(inv, "error", "missing 'category'", doc, "bastet")
    status = doc.data.get("status") or None
    if status is not None and status not in HARDWARE_STATUSES:
        _add(inv, "error", f"status '{status}' is not one of: {', '.join(HARDWARE_STATUSES)}", doc, "status")


def _generated(root: Path, path: Path) -> bool:
    """Bastet's own notes (_bastet/); a user's note with the same name always wins over them."""
    try:
        return path.relative_to(root).parts[0] == "_bastet"
    except ValueError:
        return False


def load_inventory(root: Path, types: dict[str, HostType]) -> Inventory:
    inv = Inventory(root=root)
    facts_docs: list[Document] = []
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
        if kind == "secret":
            inv.secrets.append(doc)
            continue
        if kind == "facts":
            facts_docs.append(doc)
            continue
        existing = inv.objects.get(doc.name.lower())
        if existing is not None:
            if _generated(root, existing.path) and not _generated(root, doc.path):
                inv.objects[doc.name.lower()] = doc  # the user's note wins over one Bastet generated
                continue
            if _generated(root, doc.path) and not _generated(root, existing.path):
                continue
            _add(inv, "error", f"duplicate name '{doc.name}': also {existing.path}", doc)
            continue
        inv.objects[doc.name.lower()] = doc

    labs = inv.of_kind("lab")
    for extra in labs[1:]:
        _add(inv, "error", f"more than one lab file (also {labs[0].path})", extra)

    # Check that group names don't conflict with type names (type groups are automatic)
    for doc in inv.of_kind("group"):
        if doc.name in types:
            _add(inv, "error", f"'{doc.name}' is a host type; type groups are automatic, so rename this group", doc)

    # Index facts notes before checking hosts, so a host's stale-fact-key check below can see what its
    # facts note already holds. The canonical note for a host or hardware item is the one at
    # `facts_path`/`hardware_facts_path`; anything else claiming the same object (e.g. left behind by a
    # rename) is a warning, never indexed -- so which one wins never depends on load order.
    for doc in facts_docs:
        if "item" in doc.data:
            kind, link_key, canonical_path = "hardware", "item", hardware_facts_path
        else:
            kind, link_key, canonical_path = "host", "host", facts_path
        target = link_target(doc.data.get(link_key))
        owner = inv.get(target) if target else None
        if owner is None or owner.data.get("bastet") != kind:
            _add(inv, "warning", f"no {kind} named {target or doc.data.get(link_key)}", doc)
            continue
        canonical = canonical_path(inv.root, owner.name)
        if doc.path == canonical:
            inv.facts[owner.name.lower()] = doc
        else:
            _add(
                inv, "warning",
                f"{doc.name} claims {kind} [[{owner.name}]], but its facts note is "
                f"{canonical.relative_to(inv.root).as_posix()}; ignored",
                doc,
            )

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
    from bastet.core.networks import check_networks  # networks builds on inventory

    check_networks(inv, types)
    return inv
