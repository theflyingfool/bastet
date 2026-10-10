"""Generated reference pages: one per role, every option with type, default and description, and who uses it."""

import re
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.core.hosttypes import HostType
from bastet.core.inventory import Inventory
from bastet.roles.contract import Option, RoleDef, load_roles
from bastet.roles.resolve import Applied, resolve

PAGES_DIR = "_bastet/roles"


def role_page_path(root: Path, name: str) -> Path:
    return root / PAGES_DIR / f"{name} role.md"


def _type_text(opt: Option) -> str:
    if opt.type in ("list", "map") and opt.items is not None:
        return f"{opt.type} of {opt.items.type}"
    return opt.type


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _rows(name: str, opt: Option) -> list[str]:
    extra = f" (one of {', '.join(map(str, opt.choices))})" if opt.choices else ""
    rows = [f"| {name} | {_type_text(opt)} | {_cell(opt.default)} | {_cell(opt.description)}{extra} |"]
    inner = opt.items if opt.type in ("list", "map") else opt
    suffix = "[]" if opt.type == "list" else (".<name>" if opt.type == "map" else "")
    if inner is not None and inner.type == "object":
        for field_name, field_opt in inner.fields.items():
            rows += _rows(f"{name}{suffix}.{field_name}", field_opt)
    return rows


def role_page(role: RoleDef, used_by: list[tuple[str, list[str]]]) -> str:
    lines = [f"# {role.name} role", "", role.description, "", "Docs: [[Using roles]] · [[Writing roles]]", "",
             "Values go in a role file's properties (the frontmatter at the top), never in its page text.", "",
             "## Examples", ""]
    for ex in role.examples:
        lines += [f"### {ex['title']}", "", "```yaml", ex["yaml"].rstrip("\n"), "```", ""]
    lines += ["## Options", "",
             "| Option | Type | Default | Description |", "|---|---|---|---|"]
    for name, opt in role.options.items():
        lines += _rows(name, opt)
    lines += ["", "## Used by", ""]
    lines += [f"- [[{host}]]: {', '.join(labels)}" for host, labels in used_by] or ["- (no hosts yet)"]
    return f"---\ngenerated: true\nrole: {role.name}\n---\n" + "\n".join(lines) + "\n"


ROLES_INDEX_PATH = "_bastet/Roles.md"


def _summary(role: RoleDef) -> str:
    """The first sentence of a role's description."""
    return role.description.split(". ")[0].rstrip(".")


def roles_index(roles: dict[str, RoleDef], used: dict[str, list[str]]) -> str:
    """The vault note listing every role Bastet ships, what it does, and which hosts use it."""
    lines = ["Every role Bastet ships. Add one with `bastet add role`; each name opens its full reference "
             "(options and examples).", "", "| Role | What it does | Used by |", "|---|---|---|"]
    for name in sorted(roles):
        hosts = used.get(name) or []
        users = (f"{len(hosts)}: " + ", ".join(f"[[{h}]]" for h in hosts[:5])
                 + (f" +{len(hosts) - 5} more" if len(hosts) > 5 else "")) if hosts else "—"
        lines.append(f"| [[{name} role\\|{name}]] | {_cell(_summary(roles[name]))} | {users} |")
    return "---\ngenerated: true\n---\n" + "\n".join(lines) + "\n"


def roles_markdown(roles: dict[str, RoleDef]) -> str:
    """The repo document (docs/roles.md): every role with its options and examples, no inventory data."""
    lines = ["# Roles", "", "Every role Bastet ships. Put values in a role file's properties "
             "(`_roles/lab/<role>.md`, `_roles/groups/<group>/<role>.md` or `_roles/hosts/<host>/<role>.md`), "
             "or run `bastet add role`.", "", "| Role | What it does |", "|---|---|"]
    lines += [f"| [{n}](#{n}) | {_cell(_summary(roles[n]))} |" for n in sorted(roles)]
    for name in sorted(roles):
        role = roles[name]
        lines += ["", f"## {name}", "", role.description, ""]
        if role.examples:
            lines += ["### Examples", ""]
            for ex in role.examples:
                lines += [f"**{ex['title']}**", "", "```yaml", ex["yaml"].rstrip("\n"), "```", ""]
        lines += ["### Options", "", "| Option | Type | Default | Description |", "|---|---|---|---|"]
        for opt_name, opt in role.options.items():
            lines += _rows(opt_name, opt)
    return re.sub(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", r"`\1`", "\n".join(lines)) + "\n"  # no vault links on GitHub


def roles_used(inv: Inventory, types: dict[str, HostType], roles: dict[str, RoleDef]) -> dict[str, list[tuple[str, list[str]]]]:
    used: dict[str, list[tuple[str, list[str]]]] = {name: [] for name in roles}
    for host in sorted(inv.of_kind("host"), key=lambda d: d.name.lower()):
        try:
            applied = resolve(inv, host, types, roles)
        except BastetError:
            continue
        for a in applied:
            used[a.role.name].append((host.name, sorted({s.label for s in a.sources})))
    return used


def role_pages(inv: Inventory, types: dict[str, HostType]) -> dict[Path, str]:
    roles = load_roles()
    used = roles_used(inv, types, roles)
    pages = {role_page_path(inv.root, name): role_page(role, used[name]) for name, role in roles.items()}
    pages[inv.root / ROLES_INDEX_PATH] = roles_index(roles, {n: [h for h, _ in u] for n, u in used.items()})
    return pages


_OPTION_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(\s|$)")


def options_in_body(role: RoleDef, body: str) -> list[str]:
    """Option names written as `name:` lines in the page text (outside code blocks): values Bastet won't read."""
    found: list[str] = []
    fenced = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        m = _OPTION_LINE.match(line)
        if not fenced and m and m.group(1) in role.options and m.group(1) not in found:
            found.append(m.group(1))
    return found


def _fmt(opt: Option | None, value: object) -> str:
    """One option's merged value as short table text; secrets hidden at any depth."""
    if opt is not None and opt.secret:
        return "(secret)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        items = opt.items if opt is not None else None
        return ", ".join(_fmt(items, v) for v in value)
    if isinstance(value, dict):
        if opt is not None and opt.type == "object":
            short = opt.shorthand
            rest = {k: v for k, v in value.items() if k != short}
            parts = [f"{k} {_fmt(opt.fields.get(k), v)}" for k, v in rest.items()]
            if short and short in value:
                return str(value[short]) + (f" ({', '.join(parts)})" if parts else "")
            return "; ".join(f"{k}: {_fmt(opt.fields.get(k), v)}" for k, v in value.items())
        items = opt.items if opt is not None else None
        return "; ".join(f"{k}: {_fmt(items, v)}" for k, v in value.items())
    text = " ".join(str(value).split())
    return text if len(text) <= 80 else text[:77] + "…"


def _from(applied: Applied, key: str) -> str:
    setters = sorted((s for s in applied.sources if key in s.values), key=lambda s: s.rank)
    if not setters:
        return "default"
    if applied.role.options[key].type in ("list", "map", "object"):
        return ", ".join(dict.fromkeys(s.label for s in setters))
    top = setters[-1].rank
    return ", ".join(s.label for s in setters if s.rank == top)


def resolved_table(applied: list[Applied]) -> str:
    """The merged desired state for one host, as a read-only table (generated into the host summary)."""
    if not applied:
        return ""
    esc = lambda s: str(s).replace("|", "\\|")  # noqa: E731
    lines = ["> [!warning] Resolved roles: read-only",
             "> What Bastet applies to this host, merged from every level (type, lab, groups, host). "
             "Don't edit it here: change the role files, and the next Bastet command refreshes this table.",
             "", "| Role | Option | Value | From |", "|---|---|---|---|"]
    for a in applied:
        for key, opt in a.role.options.items():
            value = a.values.get(key)
            if value is None:
                continue
            lines.append(f"| {esc(f'[[{a.role.name} role|{a.role.name}]]')} | {key} | {esc(_fmt(opt, value))} | "
                         f"{esc(_from(a, key))} |")
    return "\n".join(lines) + "\n"
