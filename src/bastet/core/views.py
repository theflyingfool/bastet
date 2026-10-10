"""Bastet-owned Obsidian views (Bases) and the page sections that embed them."""

import re
from pathlib import Path

from bastet.core.changes import Change

HARDWARE_LIST_COLUMNS = ("hardware", "category", "status", "make", "model", "serial", "size")


def _yaml_list(items: tuple[str, ...], indent: str = "      ") -> str:
    return "".join(f"{indent}- {item}\n" for item in items)


def _view_text(view_type, name, columns, *, group_by=None, filters=None, sort=None) -> str:
    text = f"  - type: {view_type}\n    name: {name}\n"
    if filters:
        key, exprs = ("or", filters) if isinstance(filters, tuple) else ("and", filters)
        text += f"    filters:\n      {key}:\n" + "".join(f"        - {e}\n" for e in exprs)
    if group_by:
        text += f"    groupBy:\n      property: {group_by}\n      direction: ASC\n"
    text += "    order:\n" + _yaml_list(columns)
    if sort:
        text += f"    sort:\n      - property: {sort[0]}\n        direction: {sort[1]}\n"
    return text


def _base(
    filter_exprs: str | list[str],
    views: list,
    *,
    group_by: str | None = None,
    formulas: dict[str, str] | None = None,
) -> str:
    """A .base file: one or more `and`-ed filters, then views in order (the first is the one shown by default).

    A view is `(type, name, columns)` or a dict with those as `type`, `name`, `columns` plus optional
    `filters` (a list is and-ed, a tuple or-ed), `sort` (property, direction) and `group_by`."""
    exprs = [filter_exprs] if isinstance(filter_exprs, str) else filter_exprs
    text = "filters:\n  and:\n" + "".join(f"    - {expr}\n" for expr in exprs)
    if formulas:
        text += "formulas:\n" + "".join(f"  {k}: {v}\n" for k, v in formulas.items())
    text += "views:\n"
    for view in views:
        if isinstance(view, dict):
            text += _view_text(
                view["type"], view["name"], view["columns"],
                group_by=view.get("group_by", group_by), filters=view.get("filters"), sort=view.get("sort"),
            )
        else:
            text += _view_text(*view, group_by=group_by)
    return text


HARDWARE_BASE_PATH = "_bastet/hardware-here.base"
HARDWARE_BASE = _base(
    ['bastet == "facts"', "installed_in == this"],
    [("table", "Table", HARDWARE_LIST_COLUMNS), ("cards", "Cards", HARDWARE_LIST_COLUMNS)],
)
ROLES_BASE_PATH = "_bastet/roles-here.base"
ROLES_BASE = _base(
    ["applies_to == this", 'bastet == "role"'],
    [("table", "Table", ("file.name", "role", "applies_to")), ("cards", "Cards", ("file.name", "role"))],
)
SECRETS_LIST_COLUMNS = ("file.name", "source", "created", "rotated", "rotates", "expires")
SECRETS_BASE_PATH = "_bastet/secrets-here.base"
SECRETS_BASE = _base(
    ["applies_to == this", 'bastet == "secret"'],
    [("table", "Table", SECRETS_LIST_COLUMNS), ("cards", "Cards", SECRETS_LIST_COLUMNS)],
    group_by="role",
)

RUNS_BASE_PATH = "_bastet/runs.base"
RUNS_HERE_BASE_PATH = "_bastet/runs-here.base"
RUNS_BOARD_PATH = "_bastet/runs-board.base"
RUNS_BOARD_HERE_PATH = "_bastet/runs-board-here.base"
BOARD_VIEW_TYPE = "kanban"  # the one constant to change if Obsidian names the board view differently
RUNS_COLUMNS = ("file.name", "mode", "status", "started", "changed", "failed", "hosts")
_NEWEST_FIRST = ("started", "DESC")
_RUNS_FILTER = 'bastet == "run"'
_HERE_FILTER = "hosts.contains(this.host)"
_RUNS_VIEWS = [
    {"type": "table", "name": "Changes", "columns": RUNS_COLUMNS, "sort": _NEWEST_FIRST,
     "filters": ('mode == "apply"', 'mode == "gather"', 'status == "failed"')},
    {"type": "table", "name": "Checks", "columns": RUNS_COLUMNS, "sort": _NEWEST_FIRST, "filters": ['mode == "check"']},
    {"type": "table", "name": "Failures", "columns": RUNS_COLUMNS, "sort": _NEWEST_FIRST, "filters": ['status == "failed"']},
    {"type": "table", "name": "All runs", "columns": RUNS_COLUMNS, "sort": _NEWEST_FIRST},
]
# The board groups by a formula, not by `status`, so dragging a card cannot rewrite the recorded status.
_BOARD_VIEWS = [
    {"type": BOARD_VIEW_TYPE, "name": "Board", "columns": RUNS_COLUMNS, "sort": _NEWEST_FIRST, "group_by": "formula.outcome"}
]
_BOARD_FORMULAS = {"outcome": "note.status"}
RUNS_BASE = _base([_RUNS_FILTER], _RUNS_VIEWS)
RUNS_HERE_BASE = _base([_RUNS_FILTER, _HERE_FILTER], _RUNS_VIEWS)
RUNS_BOARD_BASE = _base([_RUNS_FILTER], _BOARD_VIEWS, formulas=_BOARD_FORMULAS)
RUNS_BOARD_HERE_BASE = _base([_RUNS_FILTER, _HERE_FILTER], _BOARD_VIEWS, formulas=_BOARD_FORMULAS)
VIEWS = {
    HARDWARE_BASE_PATH: HARDWARE_BASE,
    ROLES_BASE_PATH: ROLES_BASE,
    SECRETS_BASE_PATH: SECRETS_BASE,
    RUNS_BASE_PATH: RUNS_BASE,
    RUNS_HERE_BASE_PATH: RUNS_HERE_BASE,
    RUNS_BOARD_PATH: RUNS_BOARD_BASE,
    RUNS_BOARD_HERE_PATH: RUNS_BOARD_HERE_BASE,
}
RUNS_SECTION = "\n## Runs\n\n![[runs.base]]\n\n![[runs-board.base]]\n"
RUNS_HERE_SECTION = "\n## Runs\n\n![[runs-here.base]]\n\n![[runs-board-here.base]]\n"
ROLES_SECTION = "\n## Roles\n\n![[roles-here.base]]\n"
SECRETS_SECTION = "\n## Secrets\n\n![[secrets-here.base]]\n"


def has_roles_section(body: str) -> bool:
    return "roles-here.base" in body or "\n## Roles" in "\n" + body


def has_secrets_section(body: str) -> bool:
    return "secrets-here.base" in body or "\n## Secrets" in "\n" + body

HARDWARE_SECTION = "\n## Hardware\n\n![[hardware-here.base]]\n"
_LEGACY_SUMMARY = re.compile(r"## Summary\n\n!\[\[(?:host|hardware)-summary\.base\]\]")


def facts_name(page: str) -> str:
    return f"{page} facts"


def facts_embed(page: str) -> str:
    return f"![[{facts_name(page)}]]"


def ensure_views(root: Path) -> list[Change]:
    """Create missing views and refresh outdated ones; files under _bastet/ belong to Bastet."""
    changes = []
    for rel, content in VIEWS.items():
        path = root / rel
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if before != content:
            changes.append(Change(path, before, content))
    return changes


def has_hardware_section(body: str) -> bool:
    return "hardware-here.base" in body or "\n## Hardware" in "\n" + body


def insert_after_title(text: str, section: str) -> str:
    """Insert `section` right after the first `# ` heading below the frontmatter (or at the top of the body)."""
    lines = text.split("\n")
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    insert_at = start
    for i in range(start, len(lines)):
        if lines[i].startswith("# "):
            insert_at = i + 1
            break
    block = section.strip("\n").split("\n")
    tail = [""] if insert_at < len(lines) and lines[insert_at].strip() else []
    return "\n".join(lines[:insert_at] + [""] + block + tail + lines[insert_at:])


def ensure_page_embed(text: str, embed: str) -> str:
    """Put `embed` right under the page title: replaces Bastet's earlier Bases summary block, else inserts it once."""
    if embed in text:
        return text
    if _LEGACY_SUMMARY.search(text):
        return _LEGACY_SUMMARY.sub(embed.replace("\\", "\\\\"), text, count=1)
    return insert_after_title(text, "\n" + embed + "\n")
