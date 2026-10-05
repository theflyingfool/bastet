"""Check and apply reports, grouped by what's managed, never by role."""

from bastet.engine.model import ABSENT, FieldChange, show_value
from bastet.engine.run import HostRun, Item

FAMILIES = ("System", "Packages", "Users", "Services", "Files", "Commands", "Other")


def change_text(c: FieldChange, *, secret: bool) -> str:
    if c.field == "content" or c.field.endswith(":content"):
        where = "" if c.field == "content" else c.field[: -len(":content")] + ": "
        return where + ("(absent) → create" if c.before == ABSENT else "differs → update")
    return f"{c.field}: {show_value(c.before, secret=secret)} → {show_value(c.after, secret=secret)}"


def _item_lines(item: Item) -> list[str]:
    label = item.resource.label
    if item.status == "compliant":
        return [f"  {label}  ✓ compliant"]
    lines = [f"  {label}"]
    tick = " ✓" if item.status == "changed" else (" ⚠" if item.status == "attention" else "")
    lines += [f"    {change_text(c, secret=item.resource.secret)}{tick}" for c in item.changes]
    if item.status == "failed":
        for n, line in enumerate((item.error or "failed").splitlines()):
            lines.append(f"    ✗ {line}" if n == 0 else f"      {line}")
    elif item.status == "skipped":
        lines.append(f"    – skipped ({item.error})")
    if item.diff:
        lines += [f"      {line}" for line in item.diff.splitlines()]
    if len(item.origins) > 1:
        lines.append(f"    ← {', '.join(item.origins)}")
    return lines


def summary(run: HostRun) -> str:
    parts = [
        f"{run.count('changed')} changed" if run.applied else f"{run.count('would-change')} to change",
        f"{run.count('compliant')} compliant",
        f"{run.count('failed')} failed",
    ]
    if run.count("attention"):
        parts.append(f"{run.count('attention')} need attention")
    if run.count("skipped"):
        parts.append(f"{run.count('skipped')} skipped")
    return f"{run.host}: " + " · ".join(parts)


def render_host(run: HostRun, *, full: bool) -> str:
    lines = [f"{'HOST: ' + run.host:<38}{'applied' if run.applied else 'check'}", ""]
    families = list(FAMILIES) + sorted({i.resource.family for i in run.items} - set(FAMILIES))
    collapsed: list[str] = []
    for family in families:
        shown: list[str] = []
        for item in run.items:
            if item.resource.family != family:
                continue
            if item.status == "compliant" and not full:
                collapsed.append(item.resource.label)
                continue
            shown += _item_lines(item)
        if shown:
            lines += [family, *shown, ""]
    if run.triggers:
        lines.append("On change")
        lines += [f"  {t.trigger.label} ✓" if t.ok else f"  {t.trigger.label} ✗ {t.error}" for t in run.triggers]
        lines.append("")
    if collapsed:
        lines += [f"{', '.join(collapsed)}: compliant ✓", ""]
    lines.append(summary(run))
    return "\n".join(lines) + "\n"


def render_runs(runs: list[HostRun], *, verbose: bool = False) -> str:
    """One host: every item. Several hosts: changes only, unless verbose."""
    full = verbose or len(runs) == 1
    text = "\n".join(render_host(r, full=full) for r in runs)
    if len(runs) > 1:
        applied = any(r.applied for r in runs)
        key, word = ("changed", "changed") if applied else ("would-change", "to change")
        text += (f"\nall: {len(runs)} hosts · {sum(r.count(key) for r in runs)} {word} · "
                 f"{sum(r.count('failed') for r in runs)} failed\n")
    return text
