"""The run recorder: events go on a queue, one thread masks them and hands them to sinks."""

from __future__ import annotations

import contextlib
import queue
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Protocol

from bastet.events.model import SCHEMA, Event, make_event, mask_event
from bastet.ui import out

_STOP = object()
DRAIN_SECONDS = 10


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
        self._counts = {"hosts": 0, "changed": 0, "failed": 0, "skipped": 0}
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
                self._counts["hosts"] += 1
                for key in ("changed", "failed", "skipped"):
                    self._counts[key] += int(data.get(key) or 0)
        self._queue.put(event)

    def _consume(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            event = mask_event(item)
            for sink in list(self.sinks):
                try:
                    sink.handle(event)
                except Exception as exc:
                    self.sinks.remove(sink)
                    self._complain(f"sink:{sink.name}", f"{sink.name} output stopped: {exc}")

    def close(self) -> None:
        self.emit("run_finished", None, status=self.status or "ok",
                  duration=round(time.monotonic() - self._started, 3), **self._counts)
        self._queue.put(_STOP)
        self._thread.join(DRAIN_SECONDS)
        for sink in self.sinks:
            try:
                sink.close()
            except Exception as exc:
                self._complain(f"close:{sink.name}", f"{sink.name} could not be closed: {exc}")


_active: Recorder | None = None


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
        recorder.close()
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
                       "compliant": run.count("compliant")}
        self.failed = bool(self.counts["failed"] or run.stopped)


@contextlib.contextmanager
def host_scope(host: str, mode: str) -> Iterator[HostScope]:
    scope = HostScope()
    emit("host_started", host, mode=mode)
    try:
        yield scope
    except BaseException as exc:
        emit("host_finished", host, status="error", error=str(getattr(exc, "message", None) or exc), **scope.counts)
        raise
    status = scope.status or ("failed" if scope.failed else "ok")
    emit("host_finished", host, status=status, **scope.counts)
