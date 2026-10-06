"""The facts note: one per host at `_bastet/facts/<host>.md`, written by gather, read by everyone else.

Unlike host notes, this one is wholly Bastet's: it is rewritten on every gather, and nothing in it is
meant to be hand-edited. `host_data` (bastet.core.hostview) is how the rest of Bastet reads it together
with the host note's own declared keys.
"""

from pathlib import Path

from bastet.core.changes import Change
from bastet.core.errors import BastetError
from bastet.core.frontmatter import new_document, parse_document
from bastet.core.links import make_link
from bastet.core.views import summary_embed

FACTS_DIR = "_bastet/facts"
META_KEYS = ("bastet", "host", "gathered", "cssclasses")
# The order `extract()` (bastet.core.facts) inserts keys in; anything else sorts alphabetically after.
FACT_ORDER = (
    "hostname", "os", "kernel", "arch", "virtualization", "chassis", "cpu", "cpu_cores", "cpu_threads",
    "ram", "storage", "interfaces", "gateway", "bridges", "bonds", "vlans",
)


def facts_path(root: Path, host: str) -> Path:
    return root / FACTS_DIR / f"{host}.md"


def _ordered_keys(facts: dict) -> list[str]:
    rest = sorted(k for k in facts if k not in FACT_ORDER)
    return [k for k in FACT_ORDER if k in facts] + rest


def render_facts(host: str, facts: dict, gathered: str) -> str:
    data: dict[str, object] = {
        "bastet": "facts",
        "host": make_link(host),
        "gathered": gathered,
        "cssclasses": ["bastet-facts"],
    }
    for key in _ordered_keys(facts):
        data[key] = facts[key]
    body = (
        f"# {host} facts\n\n"
        f"Written by Bastet on every gather; don't edit. Your settings live in [[{host}]].\n\n"
        f"{summary_embed(host)}\n"
    )
    return new_document(data, body)


def _facts_only(data: dict) -> dict:
    return {k: v for k, v in data.items() if k not in META_KEYS}


def facts_change(root: Path, host: str, facts: dict, gathered: str) -> Change | None:
    """A Change to write `facts` to the host's facts note, or None if only `gathered` would differ."""
    path = facts_path(root, host)
    before = path.read_text(encoding="utf-8") if path.exists() else None
    if before is not None:
        try:
            existing = parse_document(before, path)
        except BastetError:
            existing = None
        if existing is not None and _facts_only(existing.data) == facts:
            return None
    after = render_facts(host, facts, gathered)
    if before == after:
        return None
    return Change(path, before, after)
