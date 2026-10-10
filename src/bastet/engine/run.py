"""One host through the six phases: collect, read, compare, apply, on change, verify."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, fields, replace

from bastet import events
from bastet.core.errors import BastetError
from bastet.engine.model import FieldChange, ReadError, Resource, Trigger, Unsupported, show_value
from bastet.engine.script import NOT_REPORTED, exec_script, new_mark, read_script, split_results
from bastet.engine.slots import apply_order


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
    stopped: bool = False

    def count(self, status: str) -> int:
        return sum(1 for i in self.items if i.status == status)

    @property
    def ok(self) -> bool:
        return (
            not self.stopped
            and self.count("failed") == 0
            and all(t.ok for t in self.triggers)
        )


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
        if f.name in ("on_change", "provides"):
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
    if tuple(dict.fromkeys((*a.provides, *b.provides))) != a.provides:
        updates["provides"] = tuple(dict.fromkeys((*a.provides, *b.provides)))
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


def _item_event(host: str, item: Item, phase: str) -> None:
    from bastet.engine.report import change_text  # lazy: report imports this module

    # A failed secret resource's error may echo its content; the report keeps its text, the record does not.
    error = "(hidden: secret resource)" if item.resource.secret and item.status == "failed" else item.error
    events.emit(
        "item_checked", host, item=item.resource.label, family=item.resource.family, status=item.status, phase=phase,
        changes=[change_text(c, secret=item.resource.secret) for c in item.changes],
        error=error, diff=item.diff, origins=list(item.origins),
    )


def _command_event(host: str, phase: str, command: str, exit_code: int | None, started: float, *,
                   stdout: str = "", stderr: str = "", error: str | None = None, hidden: bool = False) -> None:
    events.emit("command_run", host, phase=phase, command=command, exit=exit_code,
                duration=round(time.monotonic() - started, 3), stdout=stdout, stderr=stderr, error=error, hidden=hidden)


def _read_label(items: list[Item]) -> str:
    labels = [i.resource.label for i in items]
    extra = f" … (+{len(labels) - 5} more)" if len(labels) > 5 else ""
    return "read " + ", ".join(labels[:5]) + extra


def _read(runner, items: list[Item], *, host: str, phase: str) -> list[dict]:
    groups = [i.resource.reads() for i in items]
    mark = new_mark()
    started = time.monotonic()
    try:
        result = runner.run(read_script(groups, mark))
    except BaseException as exc:
        _command_event(host, phase, _read_label(items), None, started, error=str(getattr(exc, "message", None) or exc))
        raise
    # A read's output is file contents and may hold secrets the masker doesn't know: never recorded.
    _command_event(host, phase, _read_label(items), result.returncode, started)
    return split_results(result.stdout, groups, mark)


def _still(c: FieldChange, secret: bool) -> str:
    if c.field == "content":
        return "contents still differ after apply"
    return f"still {c.field} {show_value(c.before, secret=secret)} after apply (wanted {show_value(c.after, secret=secret)})"


FIX_TIMEOUT = 1800


def _exec(runner, commands: list[str], root: bool, timeout: int, *, host: str, phase: str,
          hidden: bool = False) -> tuple[bool, str | None]:
    """Run a fix or trigger; a timeout or lost connection is a failure of this step, not of the whole run."""
    shown = "(hidden: secret resource)" if hidden else "; ".join(commands)
    started = time.monotonic()
    try:
        res = runner.run(exec_script(commands, root=root, mark=new_mark()), timeout=timeout)
    except BastetError as e:
        _command_event(host, phase, shown, None, started, error=str(e), hidden=hidden)
        return False, str(e)
    _command_event(host, phase, shown, res.returncode, started, hidden=hidden,
                   stdout="" if hidden else res.stdout, stderr="" if hidden else res.stderr)
    return (True, None) if res.returncode == 0 else (False, _tail(res.stderr, res.returncode))


def run_host(
    runner,
    host: str,
    batches: list[Batch],
    *,
    apply: bool,
    fix_timeout: int = FIX_TIMEOUT,
    should_stop: Callable[[], bool] | None = None,
) -> HostRun:
    with events.phase(host, "collect"):
        planned = collect_items(batches)
        sequence = apply_order(planned)
    items = [i for _, mine in planned for i in mine]
    run = HostRun(host, apply, items)
    if not items:
        return run
    with events.phase(host, "read"):
        read_results = _read(runner, items, host=host, phase="read")
    with events.phase(host, "compare"):
        for item, results in zip(items, read_results):  # phases 2 and 3
            _assess(item, results)
            _item_event(host, item, "compare")
    if not apply:
        return run

    changed: list[Item] = []
    touched: set[str] = set()
    pending: list[Trigger] = []
    broken: str | None = None
    with events.phase(host, "apply"):
        i = 0
        while i < len(sequence):  # phase 4
            item = sequence[i]
            i += 1
            if item.status == "failed" and not item.resource.report_only() and broken is None:
                broken = item.resource.label
            if item.status != "would-change":
                continue
            if run.stopped or (should_stop is not None and should_stop()):
                run.stopped = True
                item.status, item.error = "skipped", "stopped (Ctrl-C)"
                _item_event(host, item, "apply")
                continue
            if broken is not None:
                item.status, item.error = "skipped", f"earlier failure on this host: {broken}"
                _item_event(host, item, "apply")
                continue
            path = item.resource.touches()
            if path is not None and path in touched:
                _assess(item, _read(runner, [item], host=host, phase="apply")[0])
                if item.status == "failed":
                    broken = item.resource.label
                if item.status != "would-change":
                    _item_event(host, item, "apply")
                    continue
            group = [item]
            key = item.resource.group_key()
            if key is not None:
                while (i < len(sequence) and sequence[i].status == "would-change"
                       and sequence[i].resource.group_key() == key):
                    group.append(sequence[i])
                    i += 1
                commands = type(item.resource).fix_group([(g.resource, g.changes, g.current) for g in group])
            else:
                commands = item.resource.fix(item.changes, item.current)
            ok, error = _exec(runner, commands, any(g.resource.root for g in group), fix_timeout,
                              host=host, phase="apply", hidden=any(g.resource.secret for g in group))
            if not ok:
                for g in group:
                    g.status, g.error = "failed", error
                    _item_event(host, g, "apply")
                broken = item.resource.label
                continue
            for g in group:
                g.status = "changed"
                _item_event(host, g, "apply")
                changed.append(g)
                if g.resource.touches() is not None:
                    touched.add(g.resource.touches())
                for t in g.triggers:
                    if t not in pending:
                        pending.append(t)
        for t in sorted(pending, key=lambda t: t.order):  # phase 5
            ok, error = _exec(runner, [t.command], t.root, fix_timeout, host=host, phase="on_change")
            run.triggers.append(TriggerRun(t, ok, error))
            events.emit("trigger_fired", host, trigger=t.label, ok=ok, error=error)
            if not ok:
                break

    if changed:  # phase 6
        with events.phase(host, "verify"):
            for item, results in zip(changed, _read(runner, changed, host=host, phase="verify")):
                _verify(item, results)
                _item_event(host, item, "verify")
    return run


def _verify(item: Item, results: dict) -> None:
    if any(r is NOT_REPORTED for r in results.values()):
        item.status, item.error = "failed", "couldn't verify: no output for this read"
        return
    try:
        remaining = item.resource.compare(item.resource.current(results))
    except (ReadError, Unsupported) as e:
        item.status, item.error = "failed", f"couldn't verify: {e}"
        return
    if remaining:
        item.status, item.error = "failed", _still(remaining[0], item.resource.secret)
