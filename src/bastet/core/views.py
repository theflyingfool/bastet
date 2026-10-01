"""Bastet-owned Obsidian views (Bases) and the page sections that embed them."""

import re
from pathlib import Path

from bastet.core.changes import Change

HARDWARE_LIST_COLUMNS = ("file.name", "category", "model", "serial", "size", "status")


def _yaml_list(items: tuple[str, ...], indent: str = "      ") -> str:
    return "".join(f"{indent}- {item}\n" for item in items)


def _base(filter_expr: str, views: list[tuple[str, str, tuple[str, ...]]]) -> str:
    """A .base file: one filter, then views in order (the first is the one shown by default)."""
    text = f"filters:\n  and:\n    - {filter_expr}\nviews:\n"
    for view_type, name, columns in views:
        text += f"  - type: {view_type}\n    name: {name}\n    order:\n" + _yaml_list(columns)
    return text


HARDWARE_BASE_PATH = "_bastet/hardware-here.base"
HARDWARE_BASE = _base(
    "installed_in == this",
    [("table", "Table", HARDWARE_LIST_COLUMNS), ("cards", "Cards", HARDWARE_LIST_COLUMNS)],
)
VIEWS = {HARDWARE_BASE_PATH: HARDWARE_BASE}

HARDWARE_SECTION = "\n## Hardware\n\n![[hardware-here.base]]\n"
_LEGACY_SUMMARY = re.compile(r"## Summary\n\n!\[\[(?:host|hardware)-summary\.base\]\]")


def summary_name(page: str) -> str:
    return f"{page} summary"


def summary_embed(page: str) -> str:
    return f"![[{summary_name(page)}]]"


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
