"""Run work on several hosts at once: a jobs cap, dependency ordering (a guest waits for its
node), isolated errors per host, and clean Ctrl-C handling.
"""

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
    hostset = set(hosts)
    deps = {h: n for h, n in (after or {}).items() if h in hostset and n in hostset}
    _stop_event.clear()

    ready = {h: threading.Event() for h in hosts}  # host's outcome has been decided
    go = {h: threading.Event() for h in hosts}  # the main thread has decided run-or-skip
    outcomes: dict[str, Outcome[T]] = {}
    permission: dict[str, bool] = {}
    events: "queue.Queue[tuple[str, object]]" = queue.Queue()  # ("ready", host) | ("done", Outcome)

    def finish(outcome: Outcome[T]) -> None:
        outcomes[outcome.host] = outcome
        ready[outcome.host].set()
        events.put(("done", outcome))

    def run_one(host: str) -> None:
        _local.is_worker = True
        dep = deps.get(host)
        if dep is not None:
            ready[dep].wait()
            if outcomes[dep].status != "done":
                finish(Outcome(host, "error", None, f"its node {dep} failed", HostLog(host)))
                return
        # Ask the main thread for permission before touching `work`, so admission (the jobs cap
        # and Ctrl-C) is decided in one place and never races a worker that's already running.
        events.put(("ready", host))
        go[host].wait()
        if not permission[host]:
            finish(Outcome(host, "not-started", None, None, HostLog(host)))
            return
        log = HostLog(host)
        try:
            value = work(host, log)
            outcome = Outcome(host, "done", value, None, log)
        except BastetError as exc:
            outcome = Outcome(host, "error", None, exc.message, log)
        except Exception as exc:
            outcome = Outcome(host, "error", None, f"unexpected error: {exc.__class__.__name__}: {exc}", log)
        finish(outcome)

    threads = [threading.Thread(target=run_one, args=(host,)) for host in hosts]
    for t in threads:
        t.start()

    waiting: list[str] = []
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

    remaining = len(hosts)
    interrupted = False
    try:
        while remaining > 0:
            kind, payload = events.get()
            if kind == "ready":
                waiting.append(payload)  # type: ignore[arg-type]
                admit()
            else:
                outcome = payload
                if permission.get(outcome.host):  # type: ignore[union-attr]
                    active -= 1
                remaining -= 1
                if on_done is not None:
                    on_done(outcome)  # type: ignore[arg-type]
                admit()
    except KeyboardInterrupt:
        interrupted = True
        _stop_event.set()
        admit()  # release anything already waiting for a slot as not-started
        while remaining > 0:
            kind, payload = events.get()
            if kind == "ready":
                waiting.append(payload)  # type: ignore[arg-type]
                admit()
            else:
                outcome = payload
                if permission.get(outcome.host):  # type: ignore[union-attr]
                    active -= 1
                remaining -= 1
                if on_done is not None:
                    on_done(outcome)  # type: ignore[arg-type]

    for t in threads:
        t.join()

    results = [outcomes[host] for host in hosts]
    if interrupted:
        raise KeyboardInterrupt
    return results
