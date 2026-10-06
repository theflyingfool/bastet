"""One security note per host (_bastet/reports/<host> reports.md), written by check and apply from the reports."""

from __future__ import annotations

from pathlib import Path

from bastet.core.links import make_link
from bastet.core.yamlstyle import dump_frontmatter
from bastet.engine.security import REPORTS

SECURITY_DIR = "_bastet/reports"


def security_path(root: Path, host: str) -> Path:
    return root / SECURITY_DIR / f"{host} reports.md"


def security_items(items) -> list:
    return [i for i in items if hasattr(i.resource, "security_section")]


def security_note(host: str, items, when: str) -> str:
    order = {cls: n for n, cls in enumerate(REPORTS)}
    parts = [f"Security reports for [[{host}]], refreshed by `bastet check` and `bastet apply`.\n"]
    for item in sorted(security_items(items), key=lambda i: order.get(type(i.resource), len(order))):
        res = item.resource
        if item.status in ("failed", "skipped") or not item.current:
            parts.append(f"\n## {res.title}\n\n_not read: {item.error or 'no result'}_\n")
        else:
            parts.append("\n" + res.security_section(item.current))
    front = dump_frontmatter({"security_of": make_link(host), "checked": when})
    return f"---\n{front}---\n" + "".join(parts)
