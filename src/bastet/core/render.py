"""Generated Obsidian notes: per-page summaries (stat cards) and the lab dashboard.

Everything here is derived from the inventory files (plus git history for "recent changes" and the
warnings each host's last gather stored in its summary). Output is deterministic: no timestamps,
so regenerating an unchanged inventory changes nothing.
"""

import re
from importlib import resources
from pathlib import Path

from bastet.core.changes import Change
from bastet.core.errors import BastetError
from bastet.core.frontmatter import Document, parse_document
from bastet.core.gitrepo import BASTET_NAME, GitRepo
from bastet.core.hardware import MACHINE_CATEGORIES
from bastet.core.hosttypes import HostType
from bastet.core.inventory import Inventory
from bastet.core.links import link_target, make_link
from bastet.core.units import format_size, parse_size
from bastet.core.views import ensure_page_embed, ensure_views, summary_embed, summary_name
from bastet.core.yamlstyle import dump_frontmatter

SUMMARY_DIR = "_bastet/summary"
DASHBOARD_NAME = "bastet dashboard"
DASHBOARD_PATH = f"_bastet/{DASHBOARD_NAME}.md"
DASHBOARD_EMBED = f"![[{DASHBOARD_NAME}]]"
RECENT = 6
GUIDE_PATH = "_bastet/Bastet guide.md"


def guide() -> str:
    text = (resources.files("bastet") / "data" / "guide" / "guide.md").read_text(encoding="utf-8")
    return _note({}, text)


def summary_path(root: Path, page: str) -> Path:
    return root / SUMMARY_DIR / f"{summary_name(page)}.md"


def short_cpu(model: str) -> str:
    text = re.sub(r"\((R|TM|tm|r)\)", "", str(model))
    text = re.sub(r"\s+CPU\s+@.*$", "", text)
    text = re.sub(r"\s+(Processor|CPU)$", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _card(title: str, value: object, sub: object = None) -> list[str]:
    lines = [f"> > [!stat] {title}", f"> > **{value}**"]
    if sub not in (None, ""):
        lines.append(f"> > {sub}")
    return lines


def _grid(cards: list[list[str]]) -> str:
    lines = ["> [!grid]"]
    for i, card in enumerate(cards):
        if i:
            lines.append(">")
        lines += card
    return "\n".join(lines) + "\n"


def _note(frontmatter: dict, body: str) -> str:
    return "---\n" + dump_frontmatter({"generated": True, **frontmatter}) + "---\n" + body


def _installed(inv: Inventory, host: str) -> list[Document]:
    return [d for d in inv.of_kind("hardware") if (link_target(d.data.get("installed_in")) or "").lower() == host.lower()]


def _machine(inv: Inventory, host: str) -> Document | None:
    machines = [d for d in _installed(inv, host) if d.data.get("category") in MACHINE_CATEGORIES]
    return machines[0] if machines else None


def _guests(inv: Inventory, host: str) -> list[Document]:
    return [d for d in inv.of_kind("host") if (link_target(d.data.get("runs_on")) or "").lower() == host.lower()]


def _address(doc: Document) -> str | None:
    ip = str(doc.data.get("ip") or "")
    if ip and ip.lower() != "dhcp":
        return ip
    return doc.data.get("address") or (ip or None)


def host_summary(inv: Inventory, doc: Document, types: dict[str, HostType], warnings: list[str]) -> str:
    d = doc.data
    host_type = types.get(str(d.get("type")))
    cards: list[list[str]] = []
    if d.get("os"):
        cards.append(_card("OS", d["os"], d.get("kernel")))
    if d.get("cpu"):
        counts = " · ".join(x for x in (
            f"{d['cpu_cores']} cores" if d.get("cpu_cores") else "",
            f"{d['cpu_threads']} threads" if d.get("cpu_threads") else "",
        ) if x)
        cards.append(_card("CPU", short_cpu(d["cpu"]), counts))
    machine = _machine(inv, doc.name)
    if d.get("ram"):
        cards.append(_card("RAM", d["ram"], machine.data.get("memory_slots") if machine else None))
    if d.get("storage"):
        drives = [h for h in _installed(inv, doc.name) if h.data.get("category") == "drive"]
        cards.append(_card("Storage", d["storage"], f"{len(drives)} drive{'s' if len(drives) != 1 else ''}" if drives else None))
    if _address(doc):
        cards.append(_card("Network", _address(doc), f"gateway {d['gateway']}" if d.get("gateway") else None))
    parent = link_target(d.get("runs_on"))
    kind = " · ".join(str(x) for x in (d.get("chassis"), d.get("virtualization")) if x)
    cards.append(_card("Type", d.get("type", "?"), f"on [[{parent}]]" if parent else kind))
    if machine:
        m = machine.data
        what = " ".join(str(x) for x in (m.get("make"), m.get("model")) if x)
        if m.get("make") and str(m.get("model", "")).lower().startswith(str(m["make"]).lower()):
            what = str(m["model"])
        cards.append(_card("Machine", what or machine.name, f"serial {m['serial']}" if m.get("serial") else f"[[{machine.name}]]"))
        if m.get("oob_address"):
            cards.append(_card("Out-of-band", m["oob_address"], (m.get("oob") or {}).get("type", "").upper() or None))
    guests = _guests(inv, doc.name)
    if guests or (host_type and host_type.name == "proxmox-node"):
        cards.append(_card("Guests", len(guests), ", ".join(f"[[{g.name}]]" for g in guests) or None))
    body = _grid(cards)
    if warnings:
        body += "\n> [!warning] Needs attention\n" + "".join(f"> - {w}\n" for w in warnings)
    return _note({"summary_of": make_link(doc.name), "warnings": list(warnings)}, body)


def _memory_total(memory: object) -> str | None:
    if not isinstance(memory, list):
        return None
    total = sum(parse_size(m.get("size")) or 0 for m in memory if isinstance(m, dict))
    return format_size(total) if total else None


def hardware_summary(inv: Inventory, doc: Document) -> str:
    d = doc.data
    category = d.get("category")
    where = link_target(d.get("installed_in")) or link_target(d.get("location"))
    place = _card("Where", f"[[{where}]]" if where else "—", d.get("status"))
    cards: list[list[str]] = []
    if category in MACHINE_CATEGORIES:
        cards.append(_card("Model", " ".join(str(x) for x in (d.get("make"), d.get("model")) if x) or doc.name,
                           f"serial {d['serial']}" if d.get("serial") else None))
        if d.get("board") or d.get("bios"):
            cards.append(_card("Board", d.get("board") or "—", d.get("bios")))
        if d.get("memory_slots") or d.get("memory"):
            cards.append(_card("Memory", _memory_total(d.get("memory")) or "—", d.get("memory_slots")))
        cpus = d.get("cpus") if isinstance(d.get("cpus"), list) else []
        if cpus and isinstance(cpus[0], dict) and cpus[0].get("model"):
            c = cpus[0]
            counts = " · ".join(x for x in (f"{c['cores']} cores" if c.get("cores") else "",
                                             f"{c['threads']} threads" if c.get("threads") else "") if x)
            cards.append(_card("CPU" if len(cpus) == 1 else f"CPU ×{len(cpus)}", short_cpu(c["model"]), counts))
        if d.get("oob_address"):
            cards.append(_card("Out-of-band", d["oob_address"], (d.get("oob") or {}).get("type", "").upper() or None))
    elif category == "drive":
        cards.append(_card("Drive", d.get("model") or doc.name, f"serial {d['serial']}" if d.get("serial") else None))
        cards.append(_card("Size", d.get("size") or "—", " · ".join(str(x) for x in (d.get("media"), d.get("interface")) if x)))
        if d.get("health") or d.get("firmware"):
            cards.append(_card("Health", d.get("health") or "—", f"firmware {d['firmware']}" if d.get("firmware") else None))
        if d.get("pool"):
            cards.append(_card("Pool", d["pool"]))
    else:
        cards.append(_card(str(category or "Item").upper() if category in ("gpu", "hba", "nic") else "Item",
                           d.get("model") or doc.name, d.get("make")))
        if d.get("slot") or d.get("pci"):
            cards.append(_card("Slot", d.get("slot") or "—", d.get("pci")))
        if d.get("driver"):
            cards.append(_card("Driver", d["driver"]))
        ports = d.get("ports")
        if isinstance(ports, list) and ports:
            cards.append(_card("Ports", len(ports), ", ".join(str(p.get("name")) for p in ports if isinstance(p, dict))))
    cards.append(place)
    return _note({"summary_of": make_link(doc.name)}, _grid(cards))


def _mermaid_id(prefix: str, name: str) -> str:
    return f"{prefix}{re.sub(r'[^A-Za-z0-9_]', '_', name)}"


def _label(text: str) -> str:
    return text.replace('"', "#quot;")


def _where(inv: Inventory) -> str:
    hosts = inv.of_kind("host")
    by_name = {h.name.lower(): h for h in hosts}

    def location(h: Document, seen: set[str]) -> str | None:
        loc = link_target(h.data.get("location"))
        if loc:
            return loc
        machine = _machine(inv, h.name)
        if machine and link_target(machine.data.get("location")):
            return link_target(machine.data.get("location"))
        parent = link_target(h.data.get("runs_on"))
        if parent and parent.lower() in by_name and parent.lower() not in seen:
            return location(by_name[parent.lower()], seen | {h.name.lower()})
        return None

    groups: dict[str, list[Document]] = {}
    for h in hosts:
        groups.setdefault(location(h, set()) or "Unplaced", []).append(h)
    lines = ["```mermaid", "flowchart LR"]
    for loc in sorted(groups, key=lambda x: (x == "Unplaced", x.lower())):
        lines.append(f'  subgraph {_mermaid_id("loc_", loc)}["📍 {_label(loc)}"]')
        for h in groups[loc]:
            detail = " · ".join(str(x) for x in (h.data.get("type"), _address(h)) if x)
            lines.append(f'    {_mermaid_id("", h.name)}["{_label(h.name)}<br/><small>{_label(detail)}</small>"]')
        lines.append("  end")
    for h in hosts:
        parent = link_target(h.data.get("runs_on"))
        if parent and parent.lower() in by_name:
            lines.append(f"  {_mermaid_id('', by_name[parent.lower()].name)} --> {_mermaid_id('', h.name)}")
    lines.append("```")
    return "\n".join(lines) + "\n"


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|")


def dashboard(inv: Inventory, types: dict[str, HostType], warnings: dict[str, list[str]], recent: list[str]) -> str:
    hosts = inv.of_kind("host")
    hardware = inv.of_kind("hardware")
    physical = [h for h in hosts if types.get(str(h.data.get("type"))) and types[str(h.data.get("type"))].physical]
    drives = [h for h in hardware if h.data.get("category") == "drive"]
    spares = [h for h in hardware if h.data.get("status") == "spare"]
    flagged = {name: ws for name, ws in warnings.items() if ws}
    total = sum(len(ws) for ws in flagged.values())

    out = ["How this vault works: [[Bastet guide]]\n\n", _grid([
        _card("Hosts", len(hosts), f"{len(physical)} physical · {len(hosts) - len(physical)} virtual"),
        _card("Hardware", len(hardware), f"{len(drives)} drive{'s' if len(drives) != 1 else ''}"),
        _card("Spares", len(spares), ", ".join(f"[[{s.name}]]" for s in spares[:3]) or None),
        _card("Warnings", total, ", ".join(f"[[{n}]]" for n in sorted(flagged)) or "none"),
    ])]
    if flagged:
        out.append("\n## Needs attention\n\n| | Host | What |\n|---|---|---|\n")
        for name in sorted(flagged):
            for w in flagged[name]:
                out.append(f"| #warn | [[{name}]] | {_cell(w)} |\n")
    out.append("\n## What's where\n\n" + _where(inv))

    lab = inv.lab
    domains = (lab.data.get("domains") or {}) if lab else {}
    if isinstance(domains, dict) and domains:
        out.append("\n## Domains\n\n| Scope | Domain |\n|---|---|\n")
        for scope, domain in domains.items():
            out.append(f"| {_cell(scope)} | {_cell(domain)} |\n")

    notable = [h for h in hardware if h.data.get("status") not in (None, "in-service")
               or h.data.get("oob_address") or h.data.get("warranty_until")]
    if notable:
        out.append("\n## Hardware\n\n| | Item | Where | Notes |\n|---|---|---|---|\n")
        for h in notable:
            status = str(h.data.get("status") or "in-service")
            badge = {"spare": "#spare", "failed": "#down", "in-service": "#ok"}.get(status, "#info")
            where = link_target(h.data.get("installed_in")) or link_target(h.data.get("location"))
            notes = " · ".join(str(x) for x in (
                f"OOB {h.data['oob_address']}" if h.data.get("oob_address") else "",
                f"warranty to {h.data['warranty_until']}" if h.data.get("warranty_until") else "",
                h.data.get("size") or "",
            ) if x)
            out.append(f"| {badge} | [[{h.name}]] | {f'[[{where}]]' if where else '—'} | {_cell(notes)} |\n")
    if recent:
        out.append("\n## Recent changes\n\n" + "".join(f"- {r}\n" for r in recent))
    return _note({}, "".join(out))


def _recent(repo: GitRepo) -> list[str]:
    entries = []
    for date, author, subject in repo.log_entries(limit=50):
        if author != BASTET_NAME or subject.startswith("refresh"):
            continue
        entries.append(f"`{date}` {subject}")
        if len(entries) == RECENT:
            break
    return entries


def _stored_warnings(root: Path, host: str) -> list[str]:
    path = summary_path(root, host)
    if not path.exists():
        return []
    try:
        doc = parse_document(path.read_text(encoding="utf-8"), path)
    except BastetError:
        return []
    value = doc.data.get("warnings") if doc else None
    return [str(w) for w in value] if isinstance(value, list) else []


def generated_changes(
    inv: Inventory, types: dict[str, HostType], repo: GitRepo, *, warnings: dict[str, list[str]] | None = None
) -> list[Change]:
    """Every Bastet-owned generated file that differs from what the inventory says it should be."""
    root = inv.root
    warnings = warnings or {}
    changes = list(ensure_views(root))
    by_host: dict[str, list[str]] = {}

    def want(path: Path, text: str) -> None:
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if before != text:
            changes.append(Change(path, before, text))

    for doc in inv.of_kind("host"):
        current = warnings[doc.name] if doc.name in warnings else _stored_warnings(root, doc.name)
        by_host[doc.name] = current
        want(summary_path(root, doc.name), host_summary(inv, doc, types, current))
    for doc in inv.of_kind("hardware"):
        want(summary_path(root, doc.name), hardware_summary(inv, doc))
    want(root / DASHBOARD_PATH, dashboard(inv, types, by_host, _recent(repo)))
    want(root / GUIDE_PATH, guide())
    return changes


def lab_embed_changes(inv: Inventory) -> list[Change]:
    """The dashboard embed under the lab file's title (a one-time edit to the user's file; shown as a diff)."""
    lab = inv.lab
    if lab is None:
        return []
    text = lab.path.read_text(encoding="utf-8")
    new = ensure_page_embed(text, DASHBOARD_EMBED)
    return [Change(lab.path, text, new)] if new != text else []
