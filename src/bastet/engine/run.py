"""One host through the six phases: collect, read, compare, apply, on change, verify."""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace

from bastet.core.errors import BastetError
from bastet.engine.model import FieldChange, ReadError, Resource, Trigger, Unsupported, show_value
from bastet.engine.script import NOT_REPORTED, exec_script, new_mark, read_script, split_results


class ConflictError(BastetError):
    """Two sources want different things for the same item."""


@dataclass
class Batch:
    """Resources from one source (later: one role file), applied in order; a failure stops the rest of it."""

    name: str
    resources: list[Resource]


@dataclass
class Item:
    resource: Resource
    origins: list[str]
    triggers: list[Trigger]
    status: str = "compliant"
    changes: list[FieldChange] = field(default_factory=list)
    current: dict[str, object] = field(default_factory=dict)
    error: str | None = None
    diff: str | None = None


@dataclass
class TriggerRun:
    trigger: Trigger
    ok: bool
    error: str | None = None


@dataclass
class HostRun:
    host: str
    applied: bool
    items: list[Item]
    triggers: list[TriggerRun] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for i in self.items if i.status == status)

    @property
    def ok(self) -> bool:
        return self.count("failed") == 0 and all(t.ok for t in self.triggers)


def collect_items(batches: list[Batch]) -> list[tuple[Batch, list[Item]]]:
    """Phase 1: one item per identity; the same desired state merges, different desired state is an error."""
    seen: dict[str, Item] = {}
    planned: list[tuple[Batch, list[Item]]] = []
    for batch in batches:
        mine: list[Item] = []
        for res in batch.resources:
            item = seen.get(res.identity)
            if item is None:
                item = Item(res, [batch.name], list(res.on_change))
                seen[res.identity] = item
                mine.append(item)
                continue
            item.resource = _merge(item.resource, res, item.origins[0], batch.name)
            if batch.name not in item.origins:
                item.origins.append(batch.name)
            for t in res.on_change:
                if t not in item.triggers:
                    item.triggers.append(t)
        planned.append((batch, mine))
    return planned


def _merge(a: Resource, b: Resource, a_from: str, b_from: str) -> Resource:
    """Same item from two sources: fields only one side sets combine; both setting different values is a conflict."""
    if type(a) is not type(b):
        raise ConflictError(f"{b.label}: {a_from} and {b_from} describe it differently")
    updates: dict[str, object] = {}
    clashes: list[str] = []
    soft = getattr(type(a), "SOFT_DEFAULTS", ())
    for f in fields(a):
        if f.name == "on_change":
            continue
        va, vb = getattr(a, f.name), getattr(b, f.name)
        if f.name in soft and va != vb and f.default in (va, vb):
            updates[f.name] = vb if va == f.default else va
            continue
        if f.name == "secret":
            updates["secret"] = bool(va or vb)
        elif va is None and vb is not None:
            updates[f.name] = vb
        elif vb is not None and va != vb:
            clashes.append(f.name)
    if clashes:
        raise ConflictError(f"{b.label}: {a_from} and {b_from} want different {', '.join(clashes)}")
    return replace(a, **updates) if updates else a


def _tail(stderr: str, returncode: int) -> str:
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    return "\n".join(lines[-5:]) if lines else f"exit status {returncode}"


def _assess(item: Item, results: dict) -> None:
    item.error, item.diff, item.changes = None, None, []
    if any(r is NOT_REPORTED for r in results.values()):
        item.status, item.error = "failed", "no output for this read (the read script stopped early)"
        return
    if any(r.denied for r in results.values()):
        item.status, item.error = "failed", "needs root: sudo -n is not available"
        return
    try:
        item.current = item.resource.current(results)
        item.changes = item.resource.compare(item.current)
    except Unsupported as e:
        item.status, item.error = "skipped", str(e)
        return
    except ReadError as e:
        item.status, item.error = "failed", f"couldn't read: {e}"
        return
    if not item.changes:
        item.status = "compliant"
    else:
        item.status = "attention" if item.resource.report_only() else "would-change"
    if item.changes and not item.resource.secret:
        item.diff = item.resource.diff_text(item.current)


def _read(runner, items: list[Item]) -> list[dict]:
    groups = [i.resource.reads() for i in items]
    mark = new_mark()
    result = runner.run(read_script(groups, mark))
    return split_results(result.stdout, groups, mark)


def _still(c: FieldChange, secret: bool) -> str:
    if c.field == "content":
        return "contents still differ after apply"
    return f"still {c.field} {show_value(c.before, secret=secret)} after apply (wanted {show_value(c.after, secret=secret)})"


FIX_TIMEOUT = 1800


def _exec(runner, commands: list[str], root: bool, timeout: int) -> tuple[bool, str | None]:
    """Run a fix or trigger; a timeout or lost connection is a failure of this step, not of the whole run."""
    try:
        res = runner.run(exec_script(commands, root=root, mark=new_mark()), timeout=timeout)
    except BastetError as e:
        return False, str(e)
    return (True, None) if res.returncode == 0 else (False, _tail(res.stderr, res.returncode))


def run_host(runner, host: str, batches: list[Batch], *, apply: bool, fix_timeout: int = FIX_TIMEOUT) -> HostRun:
    planned = collect_items(batches)
    items = [i for _, mine in planned for i in mine]
    run = HostRun(host, apply, items)
    if not items:
        return run
    for item, results in zip(items, _read(runner, items)):  # phases 2 and 3
        _assess(item, results)
    if not apply:
        return run

    changed: list[Item] = []
    touched: set[str] = set()
    host_broken: str | None = None  # a failure in an earlier batch stops every later batch too
    for batch, mine in planned:  # phase 4
        pending: list[Trigger] = []
        broken: str | None = None
        i = 0
        while i < len(mine):
            item = mine[i]
            i += 1
            if item.status == "failed" and broken is None and host_broken is None:
                broken = item.resource.label
            if item.status != "would-change":
                continue
            if host_broken is not None:
                item.status, item.error = "skipped", f"earlier failure on this host: {host_broken}"
                continue
            if broken is not None:
                item.status, item.error = "skipped", f"earlier failure: {broken}"
                continue
            path = item.resource.touches()
            if path is not None and path in touched:
                _assess(item, _read(runner, [item])[0])
                if item.status == "failed":
                    broken = item.resource.label
                if item.status != "would-change":
                    continue
            group = [item]
            key = item.resource.group_key()
            if key is not None:
                while (i < len(mine) and mine[i].status == "would-change"
                       and mine[i].resource.group_key() == key):
                    group.append(mine[i])
                    i += 1
                commands = type(item.resource).fix_group([(g.resource, g.changes, g.current) for g in group])
            else:
                commands = item.resource.fix(item.changes, item.current)
            ok, error = _exec(runner, commands, any(g.resource.root for g in group), fix_timeout)
            if not ok:
                for g in group:
                    g.status, g.error = "failed", error
                broken = item.resource.label
                continue
            for g in group:
                g.status = "changed"
                changed.append(g)
                if g.resource.touches() is not None:
                    touched.add(g.resource.touches())
                for t in g.triggers:
                    if t not in pending:
                        pending.append(t)
        if host_broken is None and broken is not None:
            host_broken = broken
        for t in sorted(pending, key=lambda t: t.order):  # phase 5
            ok, error = _exec(runner, [t.command], t.root, fix_timeout)
            run.triggers.append(TriggerRun(t, ok, error))

    if changed:  # phase 6
        for item, results in zip(changed, _read(runner, changed)):
            if any(r is NOT_REPORTED for r in results.values()):
                item.status, item.error = "failed", "couldn't verify: no output for this read"
                continue
            try:
                remaining = item.resource.compare(item.resource.current(results))
            except (ReadError, Unsupported) as e:
                item.status, item.error = "failed", f"couldn't verify: {e}"
                continue
            if remaining:
                item.status, item.error = "failed", _still(remaining[0], item.resource.secret)
    return run
