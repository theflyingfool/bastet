"""Run work on several hosts at once: a jobs cap, dependency ordering (a guest waits for its
node), isolated errors per host, and clean Ctrl-C handling.
"""

import bisect
import queue
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

from bastet.core.errors import BastetError

T = TypeVar("T")

_local = threading.local()
_stop_event = threading.Event()


def in_worker() -> bool:
    """True when called from inside a `run_parallel` worker thread."""
    return getattr(_local, "is_worker", False)


def stopping() -> bool:
    """True once a Ctrl-C has told `run_parallel` to stop starting new hosts.

    Long-running work can check this between steps to stop early.
    """
    return _stop_event.is_set()


@dataclass
class HostLog:
    """One host's output, collected while it runs so it can be printed as a block when it's done."""

    host: str
    lines: list[tuple[str, str | None]] = field(default_factory=list)

    def echo(self, text: str) -> None:
        self.lines.append((text, None))

    def secho(self, text: str, fg: str | None = None) -> None:
        self.lines.append((text, fg))


@dataclass
class Outcome(Generic[T]):
    host: str
    status: Literal["done", "error", "not-started"]
    value: T | None
    error: str | None
    log: HostLog


class HostFailed(Exception):
    """Raise from `work` to fail a host for dependency purposes (a dependent is skipped with
    "its node <host> failed", same as any other error) while still keeping a result `on_done`
    can show -- e.g. a host whose own run produced a rendered report, just not a clean one."""

    def __init__(self, message: str, value: object = None) -> None:
        super().__init__(message)
        self.value = value


def break_cycles(deps: Mapping[str, str], order: Sequence[str]) -> tuple[dict[str, str], list[list[str]]]:
    """Drop any edge in `deps` (a host -> the host it waits for) that closes a cycle, including a
    host that (directly or indirectly) depends on itself. Walking `order` makes this deterministic:
    for the first host (in `order`) whose own chain of dependencies loops back to it, that
    dependency is dropped -- the host runs as if it had none. Returns the cleaned map and the list
    of cycles found, each as the chain of host names from the loop back to itself (e.g. `[a, b, a]`),
    for callers that want to report them.
    """
    out = dict(deps)
    cycles: list[list[str]] = []
    for start in order:
        if start not in out:
            continue
        path = [start]
        node = out.get(start)
        while node is not None:
            if node == start:
                cycles.append(path + [node])
                del out[start]
                break
            if node in path:
                break  # a cycle elsewhere in the chain; handled when its own host is the start
            path.append(node)
            node = out.get(node)
    return out, cycles


def run_parallel(
    hosts: Sequence[str],
    work: Callable[[str, HostLog], T],
    *,
    jobs: int,
    on_done: Callable[[Outcome[T]], None] | None = None,
    after: Mapping[str, str] | None = None,
) -> list[Outcome[T]]:
    """Run `work(host, log)` for each host, at most `jobs` at once, returning outcomes in the
    order `hosts` was given. `on_done` is called on this thread, in completion order, as soon
    as each host finishes. See bastet.core.parallel module docstring for the Ctrl-C and `after`
    rules.
    """
    hosts = list(hosts)
    hostset = set(hosts)
    deps = {h: n for h, n in (after or {}).items() if h in hostset and n in hostset}
    deps, _ = break_cycles(deps, hosts)
    index = {host: i for i, host in enumerate(hosts)}
    _stop_event.clear()

    ready = {h: threading.Event() for h in hosts}  # host's outcome has been decided
    go = {h: threading.Event() for h in hosts}  # the main thread has decided run-or-skip
    outcomes: dict[str, Outcome[T]] = {}
    permission: dict[str, bool] = {}
    events: "queue.Queue[tuple[str, str]]" = queue.Queue()  # ("ready" | "done", host)

    def finish(outcome: Outcome[T]) -> None:
        outcomes[outcome.host] = outcome
        ready[outcome.host].set()
        events.put(("done", outcome.host))

    def run_one(host: str) -> None:
        _local.is_worker = True
        dep = deps.get(host)
        if dep is not None:
            ready[dep].wait()
            dep_outcome = outcomes[dep]
            if dep_outcome.status == "not-started":
                # its node never ran at all (e.g. Ctrl-C) -- this guest never got a chance either
                finish(Outcome(host, "not-started", None, None, HostLog(host)))
                return
            if dep_outcome.status != "done":
                finish(Outcome(host, "error", None, f"its node {dep} failed", HostLog(host)))
                return
            # Dependency-free hosts are pre-admitted (in input order) before any thread starts;
            # a dependent host's readiness is only known once its node finishes, so it asks here.
            events.put(("ready", host))
        go[host].wait()
        if not permission[host]:
            finish(Outcome(host, "not-started", None, None, HostLog(host)))
            return
        log = HostLog(host)
        try:
            value = work(host, log)
            outcome = Outcome(host, "done", value, None, log)
        except HostFailed as exc:
            outcome = Outcome(host, "error", exc.value, str(exc), log)
        except BastetError as exc:
            outcome = Outcome(host, "error", None, exc.message, log)
        except Exception as exc:
            outcome = Outcome(host, "error", None, f"unexpected error: {exc.__class__.__name__}: {exc}", log)
        finish(outcome)

    # Hosts with no dependency are ready from the start: decide their admission order (input
    # order, up to `jobs`) right here, deterministically, before any thread exists to race over it.
    waiting: list[str] = [h for h in hosts if h not in deps]
    active = 0

    def admit() -> None:
        nonlocal active
        while waiting and (stopping() or active < jobs):
            host = waiting.pop(0)
            if stopping():
                permission[host] = False
            else:
                permission[host] = True
                active += 1
            go[host].set()

    admit()

    threads = [threading.Thread(target=run_one, args=(host,)) for host in hosts]
    for t in threads:
        t.start()

    remaining = len(hosts)

    def handle(kind: str, host: str, *, guard_on_done: bool) -> None:
        nonlocal active, remaining
        if kind == "ready":
            bisect.insort(waiting, host, key=lambda h: index[h])
            admit()
            return
        if permission.get(host):
            active -= 1
        remaining -= 1
        if on_done is not None:
            if guard_on_done:
                try:
                    on_done(outcomes[host])
                except BaseException:
                    pass  # a second failure during the drain must not abort the drain
            else:
                on_done(outcomes[host])
        admit()

    try:
        while remaining > 0:
            kind, host = events.get()
            handle(kind, host, guard_on_done=False)
    except BaseException as exc:
        # Any exception out of `on_done` -- not just Ctrl-C -- must still let every worker thread
        # reach a decision (go.set()) and be joined, or they hang forever as non-daemon threads.
        _stop_event.set()
        admit()  # release anything already waiting for a slot as not-started
        while remaining > 0:
            kind, host = events.get()
            handle(kind, host, guard_on_done=True)
        for t in threads:
            t.join()
        raise exc

    for t in threads:
        t.join()

    return [outcomes[host] for host in hosts]
