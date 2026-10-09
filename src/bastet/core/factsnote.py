"""The facts note: one per host (and one per hardware item) at `_bastet/facts/<name> facts.md`.

It's the single Bastet note per object: its frontmatter holds the gathered facts plus `warnings`,
`drift` and (for hardware) `missing_since`; its body holds the summary cards, warnings, the
resolved-roles table and (hosts only) the security section, in that order. Three different commands
write to it, each owning a different part, so each must leave the others' parts alone:

- `gather` (`facts_change`/`hardware_facts_change`) owns the frontmatter. It never touches the body:
  a brand new note gets an empty body (refresh fills it in moments later), an existing note keeps
  whatever body it already has.
- `refresh` (bastet.core.render) owns the body's sections 1-3 (cards, warnings, the roles table). It
  rewrites them from what's stored, so a later refresh can't drop a warning gather found. It leaves
  the security section (after `SECURITY_MARKER`, if any) untouched.
- `check`/`apply` (the run command) own the security section. They rewrite only what's after
  `SECURITY_MARKER`, leaving the frontmatter and the first three body sections alone.

`host_data`/`hardware_data` (bastet.core.hostview) are how the rest of Bastet reads the frontmatter
together with the host or hardware note's own declared keys.
"""

from pathlib import Path

from bastet.core.changes import Change
from bastet.core.errors import BastetError
from bastet.core.frontmatter import new_document, parse_document
from bastet.core.links import make_link

FACTS_DIR = "_bastet/facts"
META_KEYS = ("bastet", "host", "item", "gathered", "cssclasses")
# Stored in frontmatter alongside the facts, but not themselves facts: never fed into `facts_for`'s
# result, so they never leak into `host_data`, `show`, roles' `HostInfo`, and the like.
NOTE_KEYS = ("warnings", "drift")
# Keys a host's *own* gather never produces -- they're observed by something else (a Proxmox node
# seeing a guest's vmid; a UniFi device seeing a host's cabling) -- so a direct gather of the host
# itself must keep whatever is already there instead of wiping it.
OBSERVED_BY_OTHERS = ("vmid", "links")
# The order `extract()` (bastet.core.facts) inserts keys in; anything else sorts alphabetically after.
FACT_ORDER = (
    "hostname", "os", "kernel", "arch", "virtualization", "chassis", "cpu", "cpu_cores", "cpu_threads",
    "ram", "storage", "interfaces", "gateway", "bridges", "bonds", "vlans",
)
# Obsidian comment syntax (invisible in preview): marks where check/apply's security section starts,
# distinct from anything sections 1-3 can produce (they use `> [!...]` callouts and tables, never this).
SECURITY_MARKER = "%%bastet:security%%\n"


def facts_path(root: Path, host: str) -> Path:
    return root / FACTS_DIR / f"{host} facts.md"


def hardware_facts_path(root: Path, item: str) -> Path:
    return root / FACTS_DIR / f"{item} facts.md"


def split_security(body: str) -> tuple[str, str]:
    """(everything before the security section, the security section itself, marker included)."""
    idx = body.find(SECURITY_MARKER)
    return (body, "") if idx == -1 else (body[:idx], body[idx:])


def _ordered_keys(facts: dict) -> list[str]:
    rest = sorted(k for k in facts if k not in FACT_ORDER)
    return [k for k in FACT_ORDER if k in facts] + rest


def render_facts(
    host: str, facts: dict, gathered: str | None, *, warnings: list[str] | None = None,
    drift: list[str] | None = None, body: str = "",
) -> str:
    data: dict[str, object] = {"bastet": "facts", "host": make_link(host)}
    if gathered:
        data["gathered"] = gathered
    data["cssclasses"] = ["bastet-facts"]
    for key in _ordered_keys(facts):
        data[key] = facts[key]
    if warnings:
        data["warnings"] = list(warnings)
    if drift:
        data["drift"] = list(drift)
    return new_document(data, body)


def _read(path: Path):
    """The note at `path`, parsed, or None if it doesn't exist or doesn't parse."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    try:
        return parse_document(text, path)
    except BastetError:
        return None


def facts_change(
    root: Path, host: str, facts: dict, gathered: str, *, warnings: list[str] | None = None,
    drift: list[str] | None = None,
) -> Change | None:
    """A Change updating the host's facts note's frontmatter, or None if nothing but `gathered` would
    change. The body (sections 1-4) is left exactly as it was -- empty for a brand new note, since
    refresh fills it in right after a gather writes this."""
    path = facts_path(root, host)
    before = path.read_text(encoding="utf-8") if path.exists() else None
    existing = _read(path)
    body = existing.body if existing is not None else ""
    if existing is not None:
        old_facts = {k: v for k, v in existing.data.items() if k not in META_KEYS and k not in NOTE_KEYS}
        old_warnings = existing.data.get("warnings") or []
        old_drift = existing.data.get("drift") or []
        new_warnings = list(warnings) if warnings is not None else old_warnings
        new_drift = list(drift) if drift is not None else old_drift
        if old_facts == facts and list(old_warnings) == new_warnings and list(old_drift) == new_drift:
            return None
    else:
        new_warnings = list(warnings) if warnings else []
        new_drift = list(drift) if drift else []
    after = render_facts(host, facts, gathered, warnings=new_warnings, drift=new_drift, body=body)
    if before == after:
        return None
    return Change(path, before, after)


def render_hardware_facts(item: str, facts: dict, gathered: str | None, *, body: str = "") -> str:
    data: dict[str, object] = {"bastet": "facts", "item": make_link(item)}
    if gathered:
        data["gathered"] = gathered
    data["cssclasses"] = ["bastet-facts"]
    for key in sorted(facts):
        data[key] = facts[key]
    return new_document(data, body)


def hardware_facts_change(root: Path, item: str, facts: dict, gathered: str) -> Change | None:
    """A Change updating a hardware item's facts note's frontmatter, or None if only `gathered` would
    differ. The body is left exactly as it was, like `facts_change`."""
    path = hardware_facts_path(root, item)
    before = path.read_text(encoding="utf-8") if path.exists() else None
    existing = _read(path)
    body = existing.body if existing is not None else ""
    if existing is not None:
        old_facts = {k: v for k, v in existing.data.items() if k not in META_KEYS}
        if old_facts == facts:
            return None
    after = render_hardware_facts(item, facts, gathered, body=body)
    if before == after:
        return None
    return Change(path, before, after)
