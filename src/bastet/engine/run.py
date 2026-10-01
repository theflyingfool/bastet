"""One host through the six phases of spec 9.2: collect, read, compare, apply, on change, verify."""

from __future__ import annotations

from dataclasses import dataclass, field

from bastet.core.errors import BastetError
from bastet.engine.model import FieldChange, ReadError, Resource, Trigger, Unsupported, show_value
from bastet.engine.script import exec_script, new_mark, read_script, split_results


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
            a, b = item.resource.desired(), res.desired()
            if a != b:
                keys = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
                raise ConflictError(
                    f"{res.label}: {item.origins[0]} and {batch.name} want different {', '.join(keys)}"
                )
            if batch.name not in item.origins:
                item.origins.append(batch.name)
            for t in res.on_change:
                if t not in item.triggers:
                    item.triggers.append(t)
        planned.append((batch, mine))
    return planned


def _tail(stderr: str, returncode: int) -> str:
    lines = [line for line in stderr.strip().splitlines() if line.strip()]
    return "\n".join(lines[-5:]) if lines else f"exit status {returncode}"


def _assess(item: Item, results: dict) -> None:
    item.error, item.diff, item.changes = None, None, []
    if any(r.denied for r in results.values()):
        item.status, item.error = "failed", "needs root: sudo -n is not available"
        return
    try:
        item.current = item.resource.current(results)
    except Unsupported as e:
        item.status, item.error = "skipped", str(e)
        return
    except ReadError as e:
        item.status, item.error = "failed", f"couldn't read: {e}"
        return
    item.changes = item.resource.compare(item.current)
    item.status = "would-change" if item.changes else "compliant"
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


def run_host(runner, host: str, batches: list[Batch], *, apply: bool) -> HostRun:
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
    for batch, mine in planned:  # phase 4
        pending: list[Trigger] = []
        broken: str | None = None
        for item in mine:
            if item.status != "would-change":
                continue
            if broken is not None:
                item.status, item.error = "skipped", f"earlier failure: {broken}"
                continue
            path = item.resource.touches()
            if path is not None and path in touched:
                _assess(item, _read(runner, [item])[0])
                if item.status != "would-change":
                    continue
            commands = item.resource.fix(item.changes, item.current)
            res = runner.run(exec_script(commands, root=item.resource.root, mark=new_mark()))
            if res.returncode != 0:
                item.status, item.error = "failed", _tail(res.stderr, res.returncode)
                broken = item.resource.label
                continue
            item.status = "changed"
            changed.append(item)
            if path is not None:
                touched.add(path)
            for t in item.triggers:
                if t not in pending:
                    pending.append(t)
        for t in sorted(pending, key=lambda t: t.order):  # phase 5
            res = runner.run(exec_script([t.command], root=t.root, mark=new_mark()))
            run.triggers.append(TriggerRun(t, res.returncode == 0, None if res.returncode == 0 else _tail(res.stderr, res.returncode)))

    if changed:  # phase 6
        for item, results in zip(changed, _read(runner, changed)):
            try:
                remaining = item.resource.compare(item.resource.current(results))
            except (ReadError, Unsupported) as e:
                item.status, item.error = "failed", f"couldn't verify: {e}"
                continue
            if remaining:
                item.status, item.error = "failed", _still(remaining[0], item.resource.secret)
    return run
