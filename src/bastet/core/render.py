"""Generated Obsidian notes: per-page summaries (stat cards) and the lab dashboard.

Everything here is derived from the inventory files (plus git history for "recent changes" and the
warnings each host's last gather stored in its summary). Output is deterministic: no timestamps,
so regenerating an unchanged inventory changes nothing.
"""

from importlib import resources
from pathlib import Path

from bastet.core.changes import Change
from bastet.core.errors import BastetError
from bastet.core.frontmatter import Document, parse_document
from bastet.core.gitrepo import BASTET_NAME, GitRepo
from bastet.core.hardware import MACHINE_CATEGORIES
from bastet.core.hosttypes import HostType
from bastet.core.factsnote import (
    FACTS_DIR, SECURITY_MARKER, facts_path, hardware_facts_path, render_facts, render_hardware_facts, split_security,
)
from bastet.core.hostview import hardware_data, host_data, missing_warning
from bastet.core.hwparse import short_cpu
from bastet.core.inventory import Inventory, markdown_files
from bastet.core.links import link_target
from bastet.core.units import format_size, parse_size
from bastet.core.views import ensure_page_embed, ensure_views
from bastet.core.yamlstyle import dump_frontmatter

DASHBOARD_NAME = "bastet dashboard"
DASHBOARD_PATH = f"_bastet/{DASHBOARD_NAME}.md"
DASHBOARD_EMBED = f"![[{DASHBOARD_NAME}]]"
RECENT = 6
GUIDE_PATH = "_bastet/Bastet guide.md"
MAPS_DIR = "_bastet/maps"
GROUPS_DIR = "_bastet/groups"
SECRETS_PATH = "_bastet/Secrets.md"


def guide() -> str:
    text = (resources.files("bastet") / "data" / "guide" / "guide.md").read_text(encoding="utf-8")
    return _note({}, text)


def _flat(value: object) -> str:
    return " ".join(str(value).split())


def _oob_type(oob: object) -> str | None:
    return str(oob.get("type") or "").upper() or None if isinstance(oob, dict) else None


def _card(title: str, value: object, sub: object = None) -> list[str]:
    lines = [f"> > [!stat] {_flat(title)}", f"> > **{_flat(value)}**"]
    if sub not in (None, ""):
        lines.append(f"> > {_flat(sub)}")
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
    return [d for d in inv.of_kind("hardware")
            if (link_target(hardware_data(inv, d).get("installed_in")) or "").lower() == host.lower()]


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


def _port_names(ports: object) -> list[str]:
    return [str(p["name"]) for p in ports if isinstance(p, dict) and p.get("name")] if isinstance(ports, list) else []


def _roles(inv: Inventory, doc: Document, types: dict[str, HostType]) -> tuple[list[str] | None, str]:
    """The Roles card and the read-only resolved-roles table for a host summary."""
    from bastet.roles.contract import load_roles  # lazy: roles builds on core
    from bastet.roles.pages import resolved_table
    from bastet.roles.resolve import resolve

    try:
        applied = resolve(inv, doc, types, load_roles())
    except BastetError as exc:
        return _card("Roles", "⚠", exc.message), ""
    if not applied:
        return None, ""
    parts = [f"[[{a.role.name} role|{a.role.name}]] ({', '.join(sorted({s.label for s in a.sources}))})" for a in applied]
    return _card("Roles", len(applied), ", ".join(parts)), resolved_table(applied)


def host_summary(
    inv: Inventory, doc: Document, types: dict[str, HostType], warnings: list[str], drift: list[str] | None = None
) -> str:
    d = host_data(inv, doc, types)
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
        cards.append(_card("RAM", d["ram"], hardware_data(inv, machine).get("memory_slots") if machine else None))
    if d.get("storage"):
        drives = [h for h in _installed(inv, doc.name) if h.data.get("category") == "drive"]
        cards.append(_card("Storage", d["storage"], f"{len(drives)} drive{'s' if len(drives) != 1 else ''}" if drives else None))
    if _address(doc):
        cards.append(_card("Network", _address(doc), f"gateway {d['gateway']}" if d.get("gateway") else None))
    parent = link_target(d.get("runs_on"))
    kind = " · ".join(str(x) for x in (d.get("chassis"), d.get("virtualization")) if x)
    cards.append(_card("Type", d.get("type", "?"), f"on [[{parent}]]" if parent else kind))
    if machine:
        m = hardware_data(inv, machine)
        what = " ".join(str(x) for x in (m.get("make"), m.get("model")) if x)
        if m.get("make") and str(m.get("model", "")).lower().startswith(str(m["make"]).lower()):
            what = str(m["model"])
        cards.append(_card("Machine", what or machine.name, f"serial {m['serial']}" if m.get("serial") else f"[[{machine.name}]]"))
        if m.get("oob_address"):
            cards.append(_card("Out-of-band", m["oob_address"], _oob_type(m.get("oob"))))
    if host_type and host_type.physical:
        ports = _port_names(hardware_data(inv, machine).get("interfaces") if machine else None)
        for item in _installed(inv, doc.name):
            if item.data.get("category") not in MACHINE_CATEGORIES:
                ports += _port_names(hardware_data(inv, item).get("ports"))
        if ports:
            cards.append(_card("Ports", len(ports), ", ".join(ports)))
    bridges = d.get("bridges")
    if isinstance(bridges, list) and bridges:
        names = [str(b.get("name")) for b in bridges if isinstance(b, dict)]
        cards.append(_card("Bridges", len(names), ", ".join(names)))
    guests = _guests(inv, doc.name)
    if guests or (host_type and host_type.name == "proxmox"):
        cards.append(_card("Guests", len(guests), ", ".join(f"[[{g.name}]]" for g in guests) or None))
    card, roles_table = _roles(inv, doc, types)
    if card is not None:
        cards.append(card)
    body = _grid(cards)
    drift = list(drift or [])
    if drift:
        body += "\n> [!danger] Drift: Proxmox disagrees with this file\n" + "".join(f"> - {_cell(d)}\n" for d in drift)
    hw_warnings = [w for item in _installed(inv, doc.name) if (w := missing_warning(inv, item))]
    all_warnings = list(warnings) + hw_warnings
    if all_warnings:
        body += "\n> [!warning] Needs attention\n" + "".join(f"> - {_cell(w)}\n" for w in all_warnings)
    from bastet.core.cabling import port_rows  # lazy: cabling imports unifi

    rows = port_rows(inv, types, doc.name)
    if any(r.peer for r in rows):
        body += "\n## Ports\n\n| Port | Connected to | Speed | VLANs | Note |\n|---|---|---|---|---|\n"
        for r in rows:
            peer = f"[[{r.peer}]] {_cell(r.peer_port)}".strip() if r.peer else "—"
            arrow = " ↑" if r.direction == "up" else ""
            body += f"| {_cell(r.port)} | {peer}{arrow} | {_cell(r.speed)} | {_cell(r.vlans)} | {_cell(r.note)} |\n"
    if roles_table:
        body += "\n" + roles_table
    return body


def _memory_total(memory: object) -> str | None:
    if not isinstance(memory, list):
        return None
    total = sum(parse_size(m.get("size")) or 0 for m in memory if isinstance(m, dict))
    return format_size(total) if total else None


def hardware_summary(inv: Inventory, doc: Document) -> str:
    d = hardware_data(inv, doc)
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
        onboard = _port_names(d.get("interfaces"))
        if onboard:
            cards.append(_card("Network", len(onboard), ", ".join(onboard)))
        if d.get("oob_address"):
            cards.append(_card("Out-of-band", d["oob_address"], _oob_type(d.get("oob"))))
        if d.get("boot") or d.get("tpm") or d.get("secure_boot"):
            sub = " · ".join(str(x) for x in (d.get("tpm"), f"Secure Boot {d['secure_boot']}" if d.get("secure_boot") else "") if x)
            cards.append(_card("Firmware", str(d.get("boot") or "—").upper(), sub))
    elif category == "cpu":
        counts = " · ".join(x for x in (f"{d['cores']} cores" if d.get("cores") else "",
                                         f"{d['threads']} threads" if d.get("threads") else "") if x)
        cards.append(_card("CPU", short_cpu(d.get("model") or doc.name), counts))
        if d.get("socket"):
            cards.append(_card("Socket", d["socket"], f"serial {d['serial']}" if d.get("serial") else None))
    elif category == "memory":
        cards.append(_card("Memory", d.get("size") or "—", " · ".join(str(x) for x in (d.get("type"), d.get("speed")) if x)))
        cards.append(_card("Slot", d.get("slot") or "—", " ".join(str(x) for x in (d.get("make"), d.get("model")) if x)))
    elif category == "psu":
        cards.append(_card("PSU", d.get("model") or doc.name, d.get("make")))
        if d.get("max_power"):
            cards.append(_card("Power", d["max_power"], f"serial {d['serial']}" if d.get("serial") else None))
    elif category == "usb":
        cards.append(_card("USB", d.get("model") or doc.name, d.get("make")))
        cards.append(_card("ID", d.get("usb_id") or "—", f"serial {d['serial']}" if d.get("serial") else None))
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
    body = _grid(cards)
    warning = missing_warning(inv, doc)
    if warning:
        body += f"\n> [!warning] {_cell(warning)}\n"
    return body


def _label(text: str) -> str:
    return _flat(text).replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


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
    ids = {h.name.lower(): f"h{n}" for n, h in enumerate(hosts)}
    lines = ["```mermaid", "flowchart TB"]  # top-down: side-by-side locations got too wide
    for n, loc in enumerate(sorted(groups, key=lambda x: (x == "Unplaced", x.lower()))):
        lines.append(f'  subgraph loc{n}["📍 {_label(loc)}"]')
        for h in groups[loc]:
            detail = " · ".join(str(x) for x in (h.data.get("type"), _address(h)) if x)
            lines.append(f'    {ids[h.name.lower()]}["{_label(h.name)}<br/><small>{_label(detail)}</small>"]')
        lines.append("  end")
    for h in hosts:
        parent = link_target(h.data.get("runs_on"))
        if parent and parent.lower() in by_name:
            lines.append(f"  {ids[parent.lower()]} --> {ids[h.name.lower()]}")
    lines.append("```")
    return "\n".join(lines) + "\n"


def _cell(value: object) -> str:
    return _flat(value).replace("|", "\\|")


def dashboard(
    inv: Inventory,
    types: dict[str, HostType],
    warnings: dict[str, list[str]],
    recent: list[str],
    drift: dict[str, list[str]] | None = None,
    secrets_summary: list[str] | None = None,
) -> str:
    hosts = inv.of_kind("host")
    hardware = inv.of_kind("hardware")
    physical = [h for h in hosts if types.get(str(h.data.get("type"))) and types[str(h.data.get("type"))].physical]
    drives = [h for h in hardware if h.data.get("category") == "drive"]
    spares = [h for h in hardware if h.data.get("status") == "spare"]
    flagged = {name: ws for name, ws in warnings.items() if ws}
    drifted = {name: ds for name, ds in (drift or {}).items() if ds}
    missing = {h.name: w for h in hardware if (w := missing_warning(inv, h))}
    total = sum(len(ws) for ws in flagged.values()) + sum(len(ds) for ds in drifted.values()) + len(missing)

    out = ["How this vault works: [[Bastet guide]]\n\n", _grid([
        _card("Hosts", len(hosts), f"{len(physical)} physical · {len(hosts) - len(physical)} virtual"),
        _card("Hardware", len(hardware), f"{len(drives)} drive{'s' if len(drives) != 1 else ''}"),
        _card("Spares", len(spares), ", ".join(f"[[{s.name}]]" for s in spares[:3]) or None),
        _card("Warnings", total, ", ".join(f"[[{n}]]" for n in sorted(set(flagged) | set(drifted) | set(missing))) or "none"),
    ])]
    if flagged or drifted or missing:
        out.append("\n## Needs attention\n\n| | Host | What |\n|---|---|---|\n")
        for name in sorted(drifted):
            for d in drifted[name]:
                out.append(f"| #drift | [[{name}]] | drift: {_cell(d)} |\n")
        for name in sorted(flagged):
            for w in flagged[name]:
                out.append(f"| #warn | [[{name}]] | {_cell(w)} |\n")
        for name in sorted(missing):
            out.append(f"| #warn | [[{name}]] | {_cell(missing[name])} |\n")
    out.append(_hosts_table(inv, types, hosts))
    out.append(_hardware_tables(inv, hardware))
    from bastet.core.maps import cabling_map, networks_map  # lazy: maps builds on render

    shown = [f"![[{MAPS_DIR}/{t}]]" for t, f in (
        ("Cabling", lambda: cabling_map(inv, types)), ("Networks", lambda: networks_map(inv)),
    ) if f()]
    out.append("\n## Maps\n\n" + "".join(f"{m}\n\n" for m in shown)
               + f"Also: [[{MAPS_DIR}/Where|what runs where]] (locations, nodes and guests)\n"
               + "\nRoles: [[_bastet/Roles|every role Bastet ships]]\n")

    lab = inv.lab
    domains = (lab.data.get("domains") or {}) if lab else {}
    if isinstance(domains, dict) and domains:
        out.append("\n## Domains\n\n| Scope | Domain |\n|---|---|\n")
        for scope, domain in domains.items():
            out.append(f"| {_cell(scope)} | {_cell(domain)} |\n")

    if recent:
        out.append("\n## Recent changes\n\n" + "".join(f"- {r}\n" for r in recent))
    if inv.secrets:
        from bastet.core.secrets import health  # lazy: core.secrets builds on core

        out.append("\n## Secrets\n\n" + "".join(f"{_cell(line)}\n" for line in (secrets_summary or []))
                   + f"\nEvery secret: [[{SECRETS_PATH[len('_bastet/'):-3]}|Secrets]]\n")
        if (inv.root / health.AUDIT_PATH).exists():
            out.append(f"\n![[{health.AUDIT_PATH[len('_bastet/'):-3]}]]\n")
    return _note({}, "".join(out))


def _hosts_table(inv: Inventory, types: dict[str, HostType], hosts: list[Document]) -> str:
    if not hosts:
        return ""
    rows = ["\n## Hosts\n\n| Host | Type | OS | Address | Where |\n|---|---|---|---|---|\n"]
    for h in hosts:
        parent, loc = link_target(h.data.get("runs_on")), link_target(h.data.get("location"))
        where = f"on [[{parent}]]" if parent else f"[[{loc}]]" if loc else "—"
        os_name = host_data(inv, h, types).get("os")
        rows.append(f"| [[{h.name}]] | {_cell(h.data.get('type') or '?')} | {_cell(os_name or '')} | "
                    f"{_cell(_address(h) or '')} | {where} |\n")
    return "".join(rows)


DEVICE_CATEGORIES = MACHINE_CATEGORIES | {"gateway", "switch", "ap", "network"}  # whole physical boxes


def _make_model(hd: dict) -> str:
    make, model = hd.get("make"), hd.get("model")
    if make and model and str(model).lower().startswith(str(make).lower()):
        return str(model)
    return " ".join(str(v) for v in (make, model) if v)


def _hardware_row(inv: Inventory, h: Document, *, badge: bool) -> str:
    hd = hardware_data(inv, h)
    status = str(hd.get("status") or "in-service")
    mark = {"spare": "#spare", "failed": "#down", "in-service": "#ok"}.get(status, "#info")
    where = link_target(hd.get("installed_in")) or link_target(hd.get("location"))
    notes = " · ".join(str(x) for x in (
        _make_model(hd) if hd.get("category") in DEVICE_CATEGORIES else "",
        f"OOB {hd['oob_address']}" if hd.get("oob_address") else "",
        f"warranty to {hd['warranty_until']}" if hd.get("warranty_until") else "",
        hd.get("size") or "",
    ) if x)
    cells = [mark] if badge else []
    cells += [f"[[{h.name}]]", _cell(hd.get("category") or ""), f"[[{where}]]" if where else "—", _cell(notes)]
    return "| " + " | ".join(cells) + " |\n"


def _hardware_tables(inv: Inventory, hardware: list[Document]) -> str:
    """Every machine, plus other hardware worth seeing (failed, retired, out-of-band, warranty); spares separately."""
    spares = [h for h in hardware if h.data.get("status") == "spare"]
    listed = [h for h in hardware if h.data.get("status") != "spare" and (
        h.data.get("category") in DEVICE_CATEGORIES or h.data.get("status") not in (None, "in-service")
        or hardware_data(inv, h).get("oob_address") or h.data.get("warranty_until"))]
    out = ""
    if listed:
        out += "\n## Hardware\n\n| | Item | Category | Where | Notes |\n|---|---|---|---|---|\n"
        out += "".join(_hardware_row(inv, h, badge=True) for h in listed)
    if spares:
        out += "\n## Spares\n\n| Item | Category | Where | Notes |\n|---|---|---|---|\n"
        out += "".join(_hardware_row(inv, h, badge=False) for h in spares)
    return out


def _recent(repo: GitRepo) -> list[str]:
    entries = []
    for date, author, subject in repo.log_entries(limit=50):
        if author != BASTET_NAME or subject.startswith("refresh"):
            continue
        entries.append(f"`{date}` {subject}")
        if len(entries) == RECENT:
            break
    return entries


def secrets_master_list(inv: Inventory, types: dict[str, HostType]) -> str:
    """`_bastet/Secrets.md`: every secret, where it lives, who uses it, source and dates. Never values."""
    from bastet.core.secrets import health  # lazy: core.secrets builds on core
    from bastet.core.secrets.notes import SecretPath

    uses = health.collect_uses(inv, types)
    rows = ["| Secret | Lives under | Used by | Source | Created | Rotated | Rotates | Expires |\n",
            "|---|---|---|---|---|---|---|---|\n"]
    for doc in sorted(inv.secrets, key=lambda d: str(d.path)):
        try:
            rel = doc.path.relative_to(inv.root / "_secrets").with_suffix("")
            sp = SecretPath.parse(rel.as_posix())
        except (ValueError, BastetError):
            continue
        link = f"[[_secrets/{rel.as_posix()}|{sp.text}]]"
        used_by = ", ".join(f"[[{h}]]" for h in sorted(uses.get(sp.text, [])))
        rotates = "yes" if doc.data.get("rotates", True) else "no"
        rows.append(f"| {link} | {_cell(doc.data.get('applies_to'))} | {_cell(used_by)} | "
                    f"{_cell(doc.data.get('source'))} | {_cell(doc.data.get('created'))} | "
                    f"{_cell(doc.data.get('rotated'))} | {rotates} | {_cell(doc.data.get('expires'))} |\n")
    return "".join(rows)


def _migrated_warnings_drift_security(root: Path, name: str) -> tuple[list[str], list[str], str]:
    """One-time upgrade support: recover what the retired `_bastet/summary/` and `_bastet/reports/`
    notes held for `name`, so the first refresh after upgrading doesn't blank a host's warnings,
    drift or security section before they've ever made it into the facts note. A no-op once those
    notes are gone (`_retired_notes_to_delete` removes them the same refresh that reads them here)."""
    warnings: list[str] = []
    drift: list[str] = []
    security = ""
    old_summary = root / "_bastet" / "summary" / f"{name} summary.md"
    if old_summary.exists():
        try:
            doc = parse_document(old_summary.read_text(encoding="utf-8"), old_summary)
        except (BastetError, OSError, UnicodeDecodeError):
            doc = None
        if doc is not None:
            warnings = [str(w) for w in (doc.data.get("warnings") or [])]
            drift = [str(w) for w in (doc.data.get("drift") or [])]
    old_reports = root / "_bastet" / "reports" / f"{name} reports.md"
    if old_reports.exists():
        try:
            text = old_reports.read_text(encoding="utf-8")
            doc = parse_document(text, old_reports)
        except (BastetError, OSError, UnicodeDecodeError):
            doc = None
        if doc is not None and doc.body.strip():
            security = SECURITY_MARKER + doc.body
    return warnings, drift, security


def _retired_notes_to_delete(root: Path) -> list[Change]:
    """The old per-page summary notes (`generated: true`) and security reports (`security_of`), now
    that everything they held lives in the facts note. Only Bastet's own notes are ever removed here:
    a user's note with the same name never carries either marker."""
    changes = []
    summary_dir = root / "_bastet" / "summary"
    for path in sorted(summary_dir.glob("*.md")) if summary_dir.is_dir() else []:
        try:
            text = path.read_text(encoding="utf-8")
            doc = parse_document(text, path)
        except (BastetError, OSError, UnicodeDecodeError):
            continue
        if doc is not None and doc.data.get("generated"):
            changes.append(Change(path, text, None))
    reports_dir = root / "_bastet" / "reports"
    for path in sorted(reports_dir.glob("*.md")) if reports_dir.is_dir() else []:
        try:
            text = path.read_text(encoding="utf-8")
            doc = parse_document(text, path)
        except (BastetError, OSError, UnicodeDecodeError):
            continue
        if doc is not None and "security_of" in doc.data:
            changes.append(Change(path, text, None))
    return changes


def generated_changes(
    inv: Inventory,
    types: dict[str, HostType],
    repo: GitRepo,
    *,
    warnings: dict[str, list[str]] | None = None,
    drift: dict[str, list[str]] | None = None,
    secrets_summary: list[str] | None = None,
) -> list[Change]:
    """Every Bastet-owned generated file that differs from what the inventory says it should be."""
    root = inv.root
    warnings = warnings or {}
    drift = drift or {}
    changes = list(ensure_views(root))
    by_host: dict[str, list[str]] = {}
    drift_by_host: dict[str, list[str]] = {}

    def want(path: Path, text: str) -> None:
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if before != text:
            changes.append(Change(path, before, text))

    for doc in inv.of_kind("host"):
        existing = inv.facts.get(doc.name.lower())
        migrated_warnings, migrated_drift, migrated_security = _migrated_warnings_drift_security(root, doc.name)
        stored_warnings = (existing.data.get("warnings") if existing is not None else None) or migrated_warnings
        stored_drift = (existing.data.get("drift") if existing is not None else None) or migrated_drift
        current = warnings[doc.name] if doc.name in warnings else list(stored_warnings)
        current_drift = drift[doc.name] if doc.name in drift else list(stored_drift)
        by_host[doc.name] = current
        drift_by_host[doc.name] = current_drift
        security = (split_security(existing.body)[1] if existing is not None else "") or migrated_security
        facts = inv.facts_for(doc.name)
        gathered = existing.data.get("gathered") if existing is not None else None
        body = host_summary(inv, doc, types, current, current_drift) + security
        want(facts_path(root, doc.name), render_facts(doc.name, facts, gathered, warnings=current, drift=current_drift, body=body))
    for doc in inv.of_kind("hardware"):
        existing = inv.facts.get(doc.name.lower())
        facts = inv.facts_for(doc.name)
        gathered = existing.data.get("gathered") if existing is not None else None
        want(hardware_facts_path(root, doc.name), render_hardware_facts(doc.name, facts, gathered, body=hardware_summary(inv, doc)))
    changes.extend(_retired_notes_to_delete(root))
    from bastet.core.osinfo import os_id

    for ident in sorted({i for d in inv.of_kind("host") if (i := os_id(host_data(inv, d, types)))}):
        existing = inv.get(ident)
        path = root / GROUPS_DIR / f"{ident}.md"
        if existing is not None and existing.path != path:
            if path.exists():  # the user's note took the name: drop the generated group
                changes.append(Change(path, path.read_text(encoding="utf-8"), None))
            continue
        body = (f"Every host whose OS is {ident}, from what gather recorded. Generated by Bastet.\n\n"
                f'Point a role file at it (`applies_to: "[[{ident}]]"`) to reach all of them.\n')
        want(path, _note({"bastet": "group", "match": {"os": ident}}, body))
    wanted_facts = {facts_path(root, d.name) for d in inv.of_kind("host")} | {
        hardware_facts_path(root, d.name) for d in inv.of_kind("hardware")
    }
    on_disk = {p.stem.lower() for p in markdown_files(root)}  # includes notes that failed to load
    facts_dir = root / FACTS_DIR
    for path in sorted(facts_dir.glob("* facts.md")) if facts_dir.is_dir() else []:
        if path in wanted_facts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
            doc = parse_document(text, path)
        except (BastetError, OSError, UnicodeDecodeError):
            continue
        target = link_target(doc.data.get("host") or doc.data.get("item")) if doc is not None else None
        if target and target.lower() not in on_disk:  # only Bastet's own facts notes of notes that are really gone
            changes.append(Change(path, text, None))
    if inv.secrets:
        want(root / SECRETS_PATH, _note({}, secrets_master_list(inv, types)))
    elif (root / SECRETS_PATH).exists():
        changes.append(Change(root / SECRETS_PATH, (root / SECRETS_PATH).read_text(encoding="utf-8"), None))
    want(root / DASHBOARD_PATH, dashboard(inv, types, by_host, _recent(repo), drift_by_host, secrets_summary))
    want(root / GUIDE_PATH, guide())
    from bastet.core.maps import cabling_map, networks_map, where_map  # lazy: maps builds on render

    for title, text, what in (("Cabling", cabling_map(inv, types), "cables, from `links:`"),
                              ("Networks", networks_map(inv), "networks, from the lab file and host addresses"),
                              ("Where", where_map(inv), "hosts' locations and what runs on what")):
        path = root / MAPS_DIR / f"{title}.md"
        if text:
            want(path, _note({}, f"Generated from your {what}; edit those, not this page.\n\n{text}"))
        elif path.exists():
            changes.append(Change(path, path.read_text(encoding="utf-8"), None))
    from bastet.roles.pages import role_pages  # lazy: roles builds on core

    for path, text in role_pages(inv, types).items():
        want(path, text)
    snippet = root / ".obsidian" / "snippets" / "bastet.css"
    if snippet.exists():  # only keep it current where the user installed it
        want(snippet, (resources.files("bastet") / "data" / "obsidian" / "bastet.css").read_text(encoding="utf-8"))
    return changes


def lab_embed_changes(inv: Inventory) -> list[Change]:
    """The dashboard embed under the lab file's title (a one-time edit to the user's file; shown as a diff)."""
    lab = inv.lab
    if lab is None:
        return []
    text = lab.path.read_text(encoding="utf-8")
    new = ensure_page_embed(text, DASHBOARD_EMBED)
    return [Change(lab.path, text, new)] if new != text else []
