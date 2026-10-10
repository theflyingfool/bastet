"""Problems the inventory doesn't block on, found by `bastet doctor` and (where safe) fixed.

`diagnose(ctx)` takes `ctx` by duck typing (`.inventory`, `.types`, `.root`, `.repo`), the same as
`bastet.core.secrets.health.findings` -- core never imports typer, so it never imports `cli.common`.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from bastet.core.changes import Change
from bastet.core.factsnote import hardware_facts_path
from bastet.core.frontmatter import Document, remove_keys
from bastet.core.inventory import Inventory, stale_fact_removal, stale_hardware_removal
from bastet.core.refreshstate import last_reason as last_refresh_skip_reason
from bastet.core.views import facts_embed

# A key the inventory warning already called removable can still be waiting for its first value:
# the warning's own wording doesn't require that (it's about what to tell the person), but a fix
# that deletes data must.
_HAS_VALUE = lambda facts, key: facts.get(key) not in (None, "")  # noqa: E731

_RETIRED_EMBED = re.compile(r"!\[\[([^\]|]+?) (?:summary|reports)(?:\|[^\]]*)?\]\]")


@dataclass
class Problem:
    where: str
    message: str
    severity: str
    fix: Change | None = None
    fix_note: str | None = None


def _where(root: Path, file: Path | None, line: int | None) -> str:
    if file is None:
        return ""
    try:
        rel = file.relative_to(root)
    except ValueError:
        rel = file
    return f"{rel}:{line}" if line is not None else str(rel)


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def fix_retired_embeds(text: str, targets: set[str]) -> str | None:
    """Replace every `![[<name> summary]]`/`![[<name> reports]]` embed for a name in `targets`
    (a host or hardware item with a facts note) with one `![[<name> facts]]`; several retired
    embeds for the same name collapse into the one that's already there, or the first occurrence.
    Returns None when nothing in `text` needed it."""
    changed = False
    seen: set[str] = set()

    def repl(m: re.Match) -> str:
        nonlocal changed
        name = m.group(1)
        key = name.lower()
        if key not in targets:
            return m.group(0)
        changed = True
        if key in seen or facts_embed(name) in text:
            return ""
        seen.add(key)
        return facts_embed(name)

    result = _RETIRED_EMBED.sub(repl, text)
    return result if changed else None


def _inventory_problems(inv: Inventory) -> list[Problem]:
    """Every inventory problem except the stale-key warnings -- those get their own, fix-capable
    category below instead, so nothing is listed twice."""
    out = []
    for p in inv.problems:
        if "are gathered facts; they now live in" in p.error.message:
            continue
        out.append(Problem(where=_where(inv.root, p.error.file, p.error.line), message=p.error.message, severity=p.severity))
    return out


def _host_problems(inv: Inventory, doc: Document, types, retired_targets: set[str]) -> list[Problem]:
    problems: list[Problem] = []
    rel = _rel(inv.root, doc.path)
    current = doc.path.read_text(encoding="utf-8")

    removable, pending = stale_fact_removal(inv, doc, types)
    if removable or pending:
        from bastet.core.inventory import stale_fact_message

        message = stale_fact_message(doc, removable, pending)
        facts = inv.facts_for(doc.name)
        fixable = [k for k in removable if _HAS_VALUE(facts, k)]
        fix = None
        fix_note = None
        if fixable:
            fixed = remove_keys(current, fixable, doc.path)
            fix = Change(doc.path, current, fixed)
            fix_note = f"{rel}: removed {', '.join(fixable)} (now in {doc.name} facts)"
            current = fixed
        problems.append(Problem(where=rel, message=message, severity="warning", fix=fix, fix_note=fix_note))

    fixed_embed = fix_retired_embeds(current, retired_targets)
    if fixed_embed is not None:
        problems.append(Problem(
            where=rel,
            message=f"{rel} still embeds a retired note; replace with {facts_embed(doc.name)}",
            severity="warning",
            fix=Change(doc.path, current, fixed_embed),
            fix_note=f"{rel}: replaced the retired embed with {facts_embed(doc.name)}",
        ))
    return problems


def _hardware_problems(inv: Inventory, doc: Document, retired_targets: set[str]) -> list[Problem]:
    problems: list[Problem] = []
    rel = _rel(inv.root, doc.path)
    current = doc.path.read_text(encoding="utf-8")

    removable = stale_hardware_removal(inv, doc)
    if removable:
        facts = inv.facts_for(doc.name)
        fixable = [k for k in removable if _HAS_VALUE(facts, k)]
        note_path = hardware_facts_path(inv.root, doc.name).relative_to(inv.root).as_posix()
        message = f"{', '.join(removable)} are gathered facts; they now live in {note_path} (remove them from this note)"
        fix = None
        fix_note = None
        if fixable:
            fixed = remove_keys(current, fixable, doc.path)
            fix = Change(doc.path, current, fixed)
            fix_note = f"{rel}: removed {', '.join(fixable)} (now in {doc.name} facts)"
            current = fixed
        problems.append(Problem(where=rel, message=message, severity="warning", fix=fix, fix_note=fix_note))

    fixed_embed = fix_retired_embeds(current, retired_targets)
    if fixed_embed is not None:
        problems.append(Problem(
            where=rel,
            message=f"{rel} still embeds a retired note; replace with {facts_embed(doc.name)}",
            severity="warning",
            fix=Change(doc.path, current, fixed_embed),
            fix_note=f"{rel}: replaced the retired embed with {facts_embed(doc.name)}",
        ))
    return problems


def _other_page_problems(inv: Inventory, doc: Document, retired_targets: set[str]) -> list[Problem]:
    """A page that's neither a host nor a hardware note (the lab file, a group, a location) might
    still embed a now-retired note of one that is."""
    rel = _rel(inv.root, doc.path)
    current = doc.path.read_text(encoding="utf-8")
    fixed = fix_retired_embeds(current, retired_targets)
    if fixed is None:
        return []
    return [Problem(
        where=rel, message=f"{rel} still embeds a retired note",
        severity="warning", fix=Change(doc.path, current, fixed),
        fix_note=f"{rel}: replaced the retired embed",
    )]


def diagnose(ctx) -> list[Problem]:
    """Every problem `bastet doctor` lists: today's inventory problems, stale gathered keys on
    host and hardware notes, pages still embedding a retired note, why the last refresh was
    skipped, and a pending push."""
    inv = ctx.inventory
    problems: list[Problem] = _inventory_problems(inv)

    hosts = inv.of_kind("host")
    hardware = inv.of_kind("hardware")
    retired_targets = {d.name.lower() for d in (*hosts, *hardware)}

    for doc in hosts:
        problems += _host_problems(inv, doc, ctx.types, retired_targets)
    for doc in hardware:
        problems += _hardware_problems(inv, doc, retired_targets)
    for doc in (*inv.of_kind("lab"), *inv.of_kind("group"), *inv.of_kind("location")):
        problems += _other_page_problems(inv, doc, retired_targets)

    reason = last_refresh_skip_reason(inv.root)
    if reason:
        problems.append(Problem(where="", message=f"refresh skipped: {reason}", severity="warning"))

    if ctx.repo.is_repo() and ctx.repo.pending_push():
        problems.append(Problem(where="", message="local commits are not pushed yet", severity="warning"))

    return problems


def merged_changes(problems: list[Problem]) -> list[Change]:
    """One `Change` per path, even when more than one problem fixes the same file: the first
    problem's `before` and the last one's `after`, so a stale key removed and a retired embed
    replaced on the same note both land in the one write."""
    result: list[Change] = []
    index: dict[Path, int] = {}
    for p in problems:
        if p.fix is None:
            continue
        pos = index.get(p.fix.path)
        if pos is None:
            index[p.fix.path] = len(result)
            result.append(Change(p.fix.path, p.fix.before, p.fix.after))
        else:
            result[pos].after = p.fix.after
    return result
