"""The run recorder: events go on a queue, one thread masks them and hands them to sinks."""

from __future__ import annotations

import contextlib
import queue
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from bastet.events.model import SCHEMA, Event, make_event, mask_event
from bastet.ui import out

if TYPE_CHECKING:
    from bastet.core.changes import Change

_STOP = object()
DRAIN_SECONDS = 10
FLUSH_SECONDS = 2


class _Flush:
    """A marker on the queue: set once the consumer has handled everything queued before it."""

    def __init__(self) -> None:
        self.done = threading.Event()


class Sink(Protocol):
    name: str

    def handle(self, event: Event) -> None: ...

    def close(self) -> None: ...


class ListSink:
    """Keeps every event (tests)."""

    name = "list"

    def __init__(self) -> None:
        self.events: list[Event] = []

    def handle(self, event: Event) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass


class MemorySink:
    """Keeps the events a command's own run note needs, as dicts, without command output."""

    name = "memory"

    def __init__(self, max_level: int = 1) -> None:
        self.max_level = max_level
        self.events: list[dict] = []

    def handle(self, event: Event) -> None:
        if event.level > self.max_level:
            return
        d = event.to_dict()
        if event.kind == "command_run":
            d["data"] = {k: v for k, v in d["data"].items() if k not in ("stdout", "stderr")}
        self.events.append(d)

    def close(self) -> None:
        pass


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


class Recorder:
    def __init__(self, run_id: str, sinks: list[Sink]) -> None:
        self.run_id = run_id
        self.sinks = list(sinks)
        self.status: str | None = None
        self.dropped = 0
        self._started = time.monotonic()
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._host_counts: dict[str, dict[str, int]] = {}  # latest counts per host: a later scope replaces an earlier one
        self._reported: set[str] = set()
        self._thread = threading.Thread(target=self._consume, name="bastet-events", daemon=True)
        self._thread.start()

    def _complain(self, key: str, message: str) -> None:
        with self._lock:
            if key in self._reported:
                return
            self._reported.add(key)
        try:
            out.secho(f"warning: {message}", fg="yellow", err=True)
        except Exception:
            pass

    def emit(self, kind: str, host: str | None = None, **data) -> None:
        try:
            event = make_event(kind, self.run_id, self._started, host, data)
        except ValueError as exc:
            with self._lock:
                self.dropped += 1
            self._complain(f"invalid:{exc}", f"events: dropped an invalid event: {exc}")
            return
        if kind == "host_finished":
            with self._lock:
                mine = self._host_counts.setdefault(host or "", {"changed": 0, "failed": 0, "skipped": 0})
                if any(key in data for key in mine):  # a scope that recorded nothing keeps the earlier counts
                    mine.update({key: int(data.get(key) or 0) for key in mine})
        self._queue.put(event)

    def _totals(self) -> dict[str, int]:
        with self._lock:
            rows = list(self._host_counts.values())
        return {"hosts": len(rows), **{key: sum(r[key] for r in rows) for key in ("changed", "failed", "skipped")}}

    def _consume(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if isinstance(item, _Flush):
                item.done.set()
                continue
            try:
                self._handle(item)
            except Exception as exc:  # the consumer must never die: the rest of the run is still recorded
                self._complain("consumer", f"events: an event was lost: {exc}")

    def _handle(self, item: Event) -> None:
        try:
            event = mask_event(item)
        except Exception as exc:
            # Unmasked content is never written: a data-free note stands in for the event.
            self._complain("masking", f"events: masking failed, an event was dropped: {exc}")
            event = Event("note", item.run_id, item.t, item.elapsed, item.host,
                          {"message": "(masking failed: an event was dropped)"})
        for sink in list(self.sinks):
            try:
                sink.handle(event)
            except Exception as exc:
                if sink in self.sinks:
                    self.sinks.remove(sink)
                self._complain(f"sink:{sink.name}", f"{sink.name} output stopped: {exc}")

    def flush(self, *, force: bool = False) -> None:
        """Wait (briefly) until every event emitted so far has reached the live view.

        This puts a host's own live lines before its report. It does not order other hosts' lines
        when hosts run in parallel: those keep printing while this host's report does.
        Without a sink that shows events live there is nothing to wait for, unless `force` is set.
        """
        if not self._thread.is_alive() or not (force or any(getattr(s, "live", False) for s in self.sinks)):
            return
        marker = _Flush()
        self._queue.put(marker)
        marker.done.wait(FLUSH_SECONDS)

    def close(self) -> None:
        self.emit("run_finished", None, status=self.status or "ok",
                  duration=round(time.monotonic() - self._started, 3), **self._totals())
        self._queue.put(_STOP)
        self._thread.join(DRAIN_SECONDS)
        for sink in self.sinks:
            try:
                sink.close()
            except Exception as exc:
                self._complain(f"close:{sink.name}", f"{sink.name} could not be closed: {exc}")


_active: Recorder | None = None


def flush() -> None:
    """Let the live view catch up before something else prints (a host's finished report)."""
    recorder = _active
    if recorder is not None:
        recorder.flush()


def note_change(root: Path, detail: int) -> "Change | None":
    """The run note for the active run at `detail`, as a change to write; None when nothing is recording one."""
    recorder = _active
    sink = next((s for s in recorder.sinks if isinstance(s, MemorySink)), None) if recorder else None
    if recorder is None or sink is None:
        return None
    recorder.flush(force=True)
    from bastet.core.changes import Change
    from bastet.events.runnote import RUNS_DIR, note_name, render_run_note, summarize

    events = list(sink.events)
    if not events:
        return None
    s = summarize(events)
    path = root / RUNS_DIR / f"{note_name(s.started, s.mode, s.run_id)}.md"
    before = path.read_text(encoding="utf-8") if path.exists() else None
    return Change(path, before, render_run_note(events, detail, recorder.status))


def set_status(status: str) -> None:
    """Give the active run its final status, unless one is already set (the first reason wins)."""
    recorder = _active
    if recorder is not None and recorder.status is None:
        recorder.status = status


def emit(kind: str, host: str | None = None, **data) -> None:
    recorder = _active
    if recorder is not None:
        recorder.emit(kind, host, **data)


@contextlib.contextmanager
def recording(command: str, sinks: list[Sink], *, run_id: str | None = None, **extra) -> Iterator[Recorder]:
    global _active
    if _active is not None:
        yield _active
        return
    recorder = Recorder(run_id or new_run_id(), sinks)
    _active = recorder
    recorder.emit("run_started", None, command=command, schema=SCHEMA, **extra)
    try:
        yield recorder
    except KeyboardInterrupt:
        if recorder.status is None:
            recorder.status = "interrupted"
        raise
    except BaseException:
        if recorder.status is None:
            recorder.status = "failed"
        raise
    finally:
        try:
            recorder.close()
        finally:
            _active = None


@contextlib.contextmanager
def phase(host: str, name: str) -> Iterator[None]:
    emit("phase_started", host, phase=name)
    started = time.monotonic()
    try:
        yield
    finally:
        emit("phase_finished", host, phase=name, duration=round(time.monotonic() - started, 3))


class HostScope:
    def __init__(self) -> None:
        self.status: str | None = None
        self.counts: dict[str, int] = {}
        self.failed = False

    def record(self, run) -> None:
        """Take the counts from a finished `HostRun` (anything with `count(status)` and `stopped`)."""
        self.counts = {"changed": run.count("changed"), "failed": run.count("failed"), "skipped": run.count("skipped"),
                       "compliant": run.count("compliant"), "would_change": run.count("would-change")}
        self.failed = bool(self.counts["failed"] or run.stopped)


@contextlib.contextmanager
def host_scope(host: str, mode: str) -> Iterator[HostScope]:
    scope = HostScope()
    emit("host_started", host, mode=mode)
    try:
        yield scope
    except BaseException as exc:
        # Failures already recorded (a failed apply raises HostFailed) make the host failed; `error`
        # is for exceptions before any run was recorded.
        status = "failed" if scope.failed else "error"
        emit("host_finished", host, status=status, error=str(getattr(exc, "message", None) or exc), **scope.counts)
        raise
    status = scope.status or ("failed" if scope.failed else "ok")
    emit("host_finished", host, status=status, **scope.counts)
