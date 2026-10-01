"""Generated reference pages: one per role, every option with type, default and description, and who uses it."""

from pathlib import Path

from bastet.core.errors import BastetError
from bastet.core.hosttypes import HostType
from bastet.core.inventory import Inventory
from bastet.roles.contract import Option, RoleDef, load_roles
from bastet.roles.resolve import resolve

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
    lines = [f"# {role.name} role", "", role.description, "", "## Options", "",
             "| Option | Type | Default | Description |", "|---|---|---|---|"]
    for name, opt in role.options.items():
        lines += _rows(name, opt)
    lines += ["", "## Used by", ""]
    lines += [f"- [[{host}]]: {', '.join(labels)}" for host, labels in used_by] or ["- (no hosts yet)"]
    return f"---\ngenerated: true\nrole: {role.name}\n---\n" + "\n".join(lines) + "\n"


def role_pages(inv: Inventory, types: dict[str, HostType]) -> dict[Path, str]:
    roles = load_roles()
    used: dict[str, list[tuple[str, list[str]]]] = {name: [] for name in roles}
    for host in sorted(inv.of_kind("host"), key=lambda d: d.name.lower()):
        try:
            applied = resolve(inv, host, types, roles)
        except BastetError:
            continue
        for a in applied:
            used[a.role.name].append((host.name, sorted({s.label for s in a.sources})))
    return {role_page_path(inv.root, name): role_page(role, used[name]) for name, role in roles.items()}
