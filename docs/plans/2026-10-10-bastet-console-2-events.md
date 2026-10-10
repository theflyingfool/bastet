# Console output, plan 2: events and the JSONL record — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts.

**Goal:** every `bastet run` records what it did, in order, as events: a full-detail masked JSONL file on the controller for every run, plus live events on the terminal from `-vv`.

**Architecture:** a new `bastet/events/` package. The engine and the CLI call a module-level `emit(kind, host, **data)`, which is a no-op outside a recording. A `Recorder` puts events on a thread-safe queue; one consumer thread masks each event and hands it to sinks (the JSONL file, the live terminal view). Normal output is unchanged: it still renders from the `HostRun` that `run_host` returns.

**Tech Stack:** Python ≥3.12, Typer, Pydantic (config), pytest. Rich only through `bastet.ui`.

**Spec:** `docs/specs/2026-10-10-bastet-console-output-design.md`, "Plan 2: events and JSONL" and "Failure handling". Left for plan 3: run notes, the Runs Bases, `--log-level`.

**Roadmap:** `docs/ROADMAP.md`, milestone 3b. This plan runs before roles subplan 2.

## Decisions made while planning (differences from the spec)

1. **One `Event` dataclass** with a `kind` and a `data` dict, instead of a class per kind. The JSON is the same; a table (`KINDS`) says which keys each kind must carry.
2. **Normal display still renders from `HostRun`,** which `run_host` returns today. The spec says "events folded into the summary"; both are produced by the same code, and a test checks that they agree.
3. **`hook_ran` and `reboot_step` are not defined yet.** Hooks and the reboot plan don't exist until roles subplan 3, which adds those kinds. `refresh` emits nothing yet, and `gather` emits only host-level events (started, finished, skipped), not its individual commands.
4. **No gzip** of old runs: retention only deletes.
5. **`on_change` is a value of the `phase` field** on command and trigger events, not a start/finish pair. Phase pairs exist for `collect`, `read`, `compare`, `apply` and `verify`.
6. **Retention is off by default:** every run is kept forever unless `runs.keep_runs` or `runs.keep_days` is set; `bastet init` asks once (Task 7). The command is `bastet log`, not `runs`, which is too close to `run`.
7. **The output of a read script is never recorded.** It carries file contents, which may hold secrets the masker doesn't know about. Fix and trigger commands record their output, except when any resource in them is marked `secret`.

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet` (including its `runs/` folder), `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (see "Example data" in `docs/ROADMAP.md`). Task 1 makes every test use a temporary data directory.
- **Import direction:** `bastet.events` may import `bastet.ui` and `bastet.core`. `bastet.core` never imports `bastet.events`. `bastet.engine` may import `bastet.events`. Neither `events` nor `engine` imports `typer`.
- **A run never fails because of its record.** An unwritable data directory, a sink that raises, an invalid event, or a full disk is reported once on stderr and the run carries on with the same result and exit code.
- **Nothing unmasked is ever recorded or shown.** Masking happens once, in the consumer thread, before any sink sees an event. A resource marked `secret` has its command text and output replaced, and a read script's output is never recorded.
- **File modes:** the `runs/` directory `0700`, each JSONL file `0600`.
- **Existing output is unchanged** below `-vv`. No existing test may need editing for its expected text.
- **JSONL schema version 1:** `run_started` carries `schema: 1`.
- **Commit trailer:**
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01DBkyXRsdxwovkRErg9n9wt
  ```
  Stage by name, never `git commit -a`. The privacy pre-commit hook runs on every commit.
- **Each task:** failing tests first and seen failing, then implement, then the task's own test files green. The user runs the wider suite at the checkpoints.

## Review Focus

1. **A secret value never reaches the JSONL, the live terminal view or `log export`.** Check every path a value could take: fix command text, command output, a diff, a read script's output, an error message, a trigger. A `secret` resource shows `(hidden: secret resource)` and no output.
2. **A run never fails because of the record.** The data directory unwritable (or a file where the directory should be), a sink raising on the third event, an invalid event: the command's result and exit code are the same as without recording.
3. **Parallel runs:** many hosts emitting at once never produce a torn or interleaved JSONL line; each host's events stay in order; `run_finished` is last; Ctrl-C leaves a usable file whose last event is `run_finished` with status `interrupted`.
4. **Tests and tools never write to the real data directory.**
5. **Odd inputs:** a run with no hosts, a host skipped before it starts, an empty or torn JSONL file in `runs/`, a run id such as `../x` given to `log export`, a command with very large output.

## File structure

| File | Responsibility |
|---|---|
| `src/bastet/events/model.py` | `Event`, the `KINDS` table, `level_of`, `make_event`, masking |
| `src/bastet/events/recorder.py` | `Recorder`, `recording()`, `emit()`, `phase()`, `host_scope()`, `ListSink` |
| `src/bastet/events/jsonl.py` | `JsonlSink`, run directory helpers, pruning, run summaries |
| `src/bastet/events/terminal.py` | `TerminalSink`: live events from `-vv` |
| `src/bastet/events/__init__.py` | the public names |
| `src/bastet/cli/log.py` | `bastet log` (list) and `bastet log export` |
| `src/bastet/cli/common.py` | `recorded_run()`: builds sinks from config and `-v` |
| `src/bastet/engine/run.py` | emissions in `run_host`, `_read`, `_exec` |
| `src/bastet/cli/run.py`, `gather.py` | the recording around `run`, host scopes, skips |
| `src/bastet/core/config.py` | `RunsConfig` (`runs: {keep_runs, keep_days}`) |

---

### Task 1: The event model, masking, and a safe data directory for tests

**Files:**
- Create: `src/bastet/events/__init__.py`, `src/bastet/events/model.py`
- Modify: `tests/conftest.py`
- Test: `tests/events/test_event_model.py`

**Interfaces (produces):**
```python
SCHEMA = 1
KINDS: dict[str, tuple[str, ...]]          # kind -> data keys it must carry
@dataclass(frozen=True)
class Event:
    kind: str; run_id: str; t: str; elapsed: float; host: str | None; data: dict
    level: int  (property)
    def to_json(self) -> str
def level_of(kind: str, data: dict) -> int
def make_event(kind: str, run_id: str, started: float, host: str | None, data: dict) -> Event   # ValueError if invalid
def mask_value(value: object) -> object      # ACTIVE.mask over every string, recursively
def mask_event(event: Event) -> Event
```

**Behaviour:**
- **`KINDS`** (required data keys):

  | kind | keys |
  |---|---|
  | `run_started` | `command`, `schema` |
  | `run_finished` | `status`, `duration` |
  | `host_started` | `mode` |
  | `host_finished` | `status` |
  | `host_skipped` | `reason` |
  | `phase_started` | `phase` |
  | `phase_finished` | `phase`, `duration` |
  | `item_checked` | `item`, `status`, `phase` |
  | `command_run` | `phase`, `command`, `exit`, `duration` |
  | `trigger_fired` | `trigger`, `ok` |
  | `note` | `message` |

- **Levels:** `phase_*` 2; `command_run` 3; `item_checked` 1 unless its `status` is `compliant` (then 2); everything else 1.
- **`make_event`** raises `ValueError` for an unknown kind or a missing key. `t` is a UTC ISO timestamp with milliseconds; `elapsed` is `time.monotonic() - started`.
- **`to_json`** is one line: `{"kind", "run_id", "t", "elapsed", "host", "data"}`, `ensure_ascii=False`, `default=str`.
- **Masking** uses `bastet.core.secrets.redact.ACTIVE.mask` on every string in `data` (dicts and lists recursively); other types pass through; keys are not masked.
- **`tests/conftest.py`** gains an autouse fixture that sets `XDG_DATA_HOME` to a fresh temporary directory for every test, so nothing can write under the real `~/.local/share/bastet`. Tests that set it themselves later still win.

- [ ] **Step 1: Write the failing tests**

Create `tests/events/test_event_model.py`:

```python
import json
import time

import pytest

from bastet.core.config import data_dir
from bastet.core.secrets.redact import ACTIVE
from bastet.events.model import KINDS, Event, level_of, make_event, mask_event, mask_value


def ev(kind="note", host=None, **data):
    data = data or {"message": "hi"}
    return make_event(kind, "20261010-120000-ab12", time.monotonic(), host, data)


def test_every_kind_can_be_made_with_exactly_its_required_keys():
    for kind, keys in KINDS.items():
        event = make_event(kind, "r1", time.monotonic(), None, {k: 1 for k in keys})
        assert event.kind == kind


def test_unknown_kind_and_missing_key_are_errors():
    with pytest.raises(ValueError, match="unknown event kind"):
        make_event("nope", "r1", time.monotonic(), None, {})
    with pytest.raises(ValueError, match="missing"):
        make_event("command_run", "r1", time.monotonic(), "pve1", {"phase": "apply"})


def test_levels():
    assert level_of("run_started", {}) == 1
    assert level_of("phase_started", {}) == 2 and level_of("phase_finished", {}) == 2
    assert level_of("command_run", {}) == 3
    assert level_of("item_checked", {"status": "would-change"}) == 1
    assert level_of("item_checked", {"status": "failed"}) == 1
    assert level_of("item_checked", {"status": "compliant"}) == 2
    assert ev("note", message="x").level == 1


def test_to_json_is_one_line_and_round_trips():
    event = ev("item_checked", "pve1", item="/etc/motd", status="changed", phase="apply", changes=["a → b"], path=__import__("pathlib").Path("/x"))
    line = event.to_json()
    assert "\n" not in line
    parsed = json.loads(line)
    assert parsed["kind"] == "item_checked" and parsed["host"] == "pve1" and parsed["run_id"] == "20261010-120000-ab12"
    assert parsed["data"]["changes"] == ["a → b"] and parsed["data"]["path"] == "/x"
    assert parsed["t"].endswith("Z") and isinstance(parsed["elapsed"], float)


def test_non_ascii_is_kept_readable():
    assert "→" in ev("note", message="a → b").to_json()


def test_mask_value_is_recursive_and_leaves_keys_and_other_types():
    ACTIVE.add("hunter2-value")
    masked = mask_value({"a": ["x hunter2-value", {"b": "hunter2-value"}], "n": 3, "hunter2-value": 1})
    assert "hunter2-value" not in json.dumps({k: v for k, v in masked.items() if k != "hunter2-value"})
    assert masked["n"] == 3 and "hunter2-value" in masked  # keys are not masked


def test_mask_event_masks_the_data_only():
    ACTIVE.add("hunter2-value")
    event = mask_event(ev("note", "pve1", message="pw hunter2-value"))
    assert "hunter2-value" not in event.data["message"] and event.host == "pve1" and event.kind == "note"


def test_the_test_suite_never_uses_the_real_data_directory():
    real = __import__("pathlib").Path.home() / ".local" / "share" / "bastet"
    assert data_dir() != real
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/events/test_event_model.py -q`
Expected: collection error, `No module named 'bastet.events'`.

- [ ] **Step 3: Implement**

`src/bastet/events/model.py`:

```python
"""Run events: what a run did, as plain data. The JSONL record and the live view are built from these."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from bastet.core.secrets.redact import ACTIVE

SCHEMA = 1

KINDS: dict[str, tuple[str, ...]] = {
    "run_started": ("command", "schema"),
    "run_finished": ("status", "duration"),
    "host_started": ("mode",),
    "host_finished": ("status",),
    "host_skipped": ("reason",),
    "phase_started": ("phase",),
    "phase_finished": ("phase", "duration"),
    "item_checked": ("item", "status", "phase"),
    "command_run": ("phase", "command", "exit", "duration"),
    "trigger_fired": ("trigger", "ok"),
    "note": ("message",),
}


def level_of(kind: str, data: dict) -> int:
    """1 changes and failures, 2 every item and phase, 3 commands, 4 (display only) their output."""
    if kind in ("phase_started", "phase_finished"):
        return 2
    if kind == "command_run":
        return 3
    if kind == "item_checked":
        return 2 if data.get("status") == "compliant" else 1
    return 1


@dataclass(frozen=True)
class Event:
    kind: str
    run_id: str
    t: str
    elapsed: float
    host: str | None
    data: dict

    @property
    def level(self) -> int:
        return level_of(self.kind, self.data)

    def to_json(self) -> str:
        return json.dumps(
            {"kind": self.kind, "run_id": self.run_id, "t": self.t, "elapsed": round(self.elapsed, 3),
             "host": self.host, "data": self.data},
            ensure_ascii=False, default=str,
        )


def make_event(kind: str, run_id: str, started: float, host: str | None, data: dict) -> Event:
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind!r}")
    missing = [k for k in KINDS[kind] if k not in data]
    if missing:
        raise ValueError(f"{kind} is missing {', '.join(missing)}")
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return Event(kind, run_id, now, time.monotonic() - started, host, dict(data))


def mask_value(value: object) -> object:
    if isinstance(value, str):
        return ACTIVE.mask(value)
    if isinstance(value, dict):
        return {k: mask_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_value(v) for v in value]
    return value


def mask_event(event: Event) -> Event:
    return replace(event, host=event.host, data=mask_value(event.data))
```

`src/bastet/events/__init__.py`: leave empty for now (Task 2 fills it).

In `tests/conftest.py` add:

```python
@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path_factory, monkeypatch):
    """Run records go under `$XDG_DATA_HOME/bastet/runs`; no test may write to the real one."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path_factory.mktemp("xdg_data")))
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/events/test_event_model.py tests/core/test_config.py -q`
Expected: all pass. A failure in `test_config.py` means a config test relied on the real `XDG_DATA_HOME`; fix the test's own environment, not the fixture.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/events/__init__.py src/bastet/events/model.py tests/conftest.py tests/events/test_event_model.py
git commit -m "events: the event model and masking; tests always use a temporary data directory"
```

---

### Task 2: The recorder: queue, consumer thread, sinks, scopes

**Files:**
- Create: `src/bastet/events/recorder.py`
- Modify: `src/bastet/events/__init__.py`
- Test: `tests/events/test_recorder.py`

**Interfaces (consumes):** Task 1's `Event`, `make_event`, `mask_event`, `SCHEMA`.

**Interfaces (produces):**
```python
class Sink(Protocol):
    name: str
    def handle(self, event: Event) -> None: ...
    def close(self) -> None: ...
class ListSink:                      # tests: .events: list[Event]
class Recorder:
    run_id: str; status: str | None; dropped: int
    def emit(self, kind: str, host: str | None = None, **data) -> None
    def close(self) -> None          # emits run_finished, drains the queue, closes sinks
def new_run_id() -> str              # "20261010-120000-ab12" (UTC time, 6 random hex)
def emit(kind: str, host: str | None = None, **data) -> None     # no-op outside a recording
def recording(command: str, sinks: list[Sink], *, run_id: str | None = None, **extra) -> ContextManager[Recorder]
def phase(host: str, name: str) -> ContextManager[None]          # phase_started / phase_finished(duration)
def host_scope(host: str, mode: str) -> ContextManager[HostScope]
class HostScope:  def record(self, run) -> None;  status: str | None     # run: anything with .count(str) and .stopped
```

**Behaviour:**
- **`recording`** creates a `Recorder`, makes it the active one, emits `run_started` (`command`, `schema`, plus `extra`), yields it, and on exit emits `run_finished` and closes. A nested `recording` yields the active recorder unchanged. Status: `rec.status` if the caller set it; else `interrupted` on `KeyboardInterrupt`, `failed` on any other exception, `ok` on a clean exit. The exception always propagates.
- **`run_finished`** data: `status`, `duration` (seconds), `hosts`, `changed`, `failed`, `skipped`. The counts are summed from the `host_finished` events' `changed`, `failed`, `skipped` values.
- **Consumer thread:** takes events off the queue in order, masks each (`mask_event`), and calls each sink's `handle`. A sink that raises is reported once on stderr (`warning: <name> output stopped: <error>`, yellow) and dropped; the other sinks and the run continue.
- **An invalid event** (`ValueError` from `make_event`) is dropped, counted in `dropped`, and reported once on stderr. It never raises into the caller.
- **`close`** waits for the consumer to drain (a few seconds at most), then calls each sink's `close` (errors reported, not raised).
- **`host_scope`** emits `host_started` (`mode`), yields a `HostScope`, then emits `host_finished` with `status` and the counts from `scope.record(run)`. `status` is `error` (with `error=<message>`) if the block raised, else `scope.status` if set, else `failed` when the recorded run has failures or was stopped, else `ok`. The exception propagates.

- [ ] **Step 1: Write the failing tests**

Create `tests/events/test_recorder.py`:

```python
import threading

import pytest

from bastet import events
from bastet.core.secrets.redact import ACTIVE
from bastet.events.recorder import ListSink, Recorder, new_run_id, recording


def kinds(sink):
    return [e.kind for e in sink.events]


def test_run_started_first_run_finished_last_and_order_kept():
    sink = ListSink()
    with recording("run -c", [sink]) as rec:
        events.emit("note", None, message="one")
        events.emit("note", None, message="two")
    assert kinds(sink) == ["run_started", "note", "note", "run_finished"]
    assert [e.data["message"] for e in sink.events[1:3]] == ["one", "two"]
    assert sink.events[0].data["command"] == "run -c" and sink.events[0].data["schema"] == 1
    assert sink.events[-1].data["status"] == "ok"


def test_emit_outside_a_recording_is_a_no_op():
    events.emit("note", None, message="nobody listening")


def test_status_follows_the_exception():
    for exc, status in ((ValueError("x"), "failed"), (KeyboardInterrupt(), "interrupted")):
        sink = ListSink()
        with pytest.raises(type(exc)):
            with recording("run", [sink]):
                raise exc
        assert sink.events[-1].kind == "run_finished" and sink.events[-1].data["status"] == status


def test_an_explicit_status_wins_even_when_an_exception_passes():
    sink = ListSink()
    with pytest.raises(RuntimeError):
        with recording("run", [sink]) as rec:
            rec.status = "ok"
            raise RuntimeError("exit 0")
    assert sink.events[-1].data["status"] == "ok"


def test_counts_are_summed_from_host_finished():
    sink = ListSink()
    with recording("run", [sink]):
        events.emit("host_finished", "a", status="ok", changed=2, failed=0, skipped=1)
        events.emit("host_finished", "b", status="failed", changed=1, failed=3, skipped=0)
    done = sink.events[-1].data
    assert (done["hosts"], done["changed"], done["failed"], done["skipped"]) == (2, 3, 3, 1)


def test_many_threads_lose_nothing_and_keep_per_thread_order():
    sink = ListSink()
    with recording("run", [sink]):
        def worker(n):
            for i in range(50):
                events.emit("note", f"h{n}", message=f"{n}-{i}")

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    notes = [e for e in sink.events if e.kind == "note"]
    assert len(notes) == 400
    for n in range(8):
        mine = [int(e.data["message"].split("-")[1]) for e in notes if e.host == f"h{n}"]
        assert mine == list(range(50))
    assert sink.events[-1].kind == "run_finished"


def test_masking_happens_before_any_sink_sees_the_event():
    ACTIVE.add("hunter2-value")
    sink = ListSink()
    with recording("run", [sink]):
        events.emit("note", "pve1", message="pw hunter2-value", extra={"deep": ["hunter2-value"]})
    note = next(e for e in sink.events if e.kind == "note")
    assert "hunter2-value" not in note.to_json()


def test_a_failing_sink_is_reported_once_and_dropped_while_the_others_continue(capsys):
    class Boom(ListSink):
        name = "boom"

        def handle(self, event):
            super().handle(event)
            if len(self.events) == 3:
                raise OSError("disk full")

    boom, good = Boom(), ListSink()
    with recording("run", [boom, good]):
        for i in range(5):
            events.emit("note", None, message=str(i))
    assert len(good.events) == 7 and len(boom.events) == 3
    err = capsys.readouterr().err
    assert err.count("boom output stopped: disk full") == 1


def test_an_invalid_event_is_dropped_counted_and_reported_once(capsys):
    sink = ListSink()
    with recording("run", [sink]) as rec:
        events.emit("command_run", "pve1", phase="apply")
        events.emit("command_run", "pve1", phase="apply")
        events.emit("nope", None)
    assert rec.dropped == 3 and "command_run" not in kinds(sink)
    assert capsys.readouterr().err.count("dropped an invalid event") <= 2  # once per distinct problem


def test_nested_recording_reuses_the_active_recorder():
    sink = ListSink()
    with recording("run", [sink]) as outer:
        with recording("gather", [ListSink()]) as inner:
            assert inner is outer
        events.emit("note", None, message="still recording")
    assert kinds(sink).count("run_started") == 1 and "note" in kinds(sink)


def test_phase_and_host_scope_emit_pairs():
    sink = ListSink()
    with recording("run", [sink]):
        with events.host_scope("pve1", "check") as scope:
            with events.phase("pve1", "read"):
                pass

            class Run:
                stopped = False

                def count(self, status):
                    return {"changed": 2, "failed": 0, "skipped": 1}.get(status, 0)

            scope.record(Run())
    got = [(e.kind, e.data.get("phase") or e.data.get("mode") or e.data.get("status")) for e in sink.events[1:-1]]
    assert got == [("host_started", "check"), ("phase_started", "read"), ("phase_finished", "read"), ("host_finished", "ok")]
    finished = next(e for e in sink.events if e.kind == "host_finished")
    assert (finished.data["changed"], finished.data["skipped"]) == (2, 1)


def test_host_scope_reports_an_error_and_reraises():
    sink = ListSink()
    with recording("run", [sink]):
        with pytest.raises(ValueError):
            with events.host_scope("pve1", "apply"):
                raise ValueError("connection lost")
    finished = next(e for e in sink.events if e.kind == "host_finished")
    assert finished.data["status"] == "error" and "connection lost" in finished.data["error"]


def test_a_failed_run_makes_the_host_failed():
    sink = ListSink()

    class Run:
        stopped = False

        def count(self, status):
            return 1 if status == "failed" else 0

    with recording("run", [sink]):
        with events.host_scope("pve1", "apply") as scope:
            scope.record(Run())
    assert next(e for e in sink.events if e.kind == "host_finished").data["status"] == "failed"


def test_run_ids_sort_by_time_and_are_unique():
    ids = [new_run_id() for _ in range(50)]
    assert len(set(ids)) == 50 and all(len(i) == len("20261010-120000-ab12") for i in ids)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/events/test_recorder.py -q`
Expected: collection error, `cannot import name 'recorder'` / `emit`.

- [ ] **Step 3: Implement**

`src/bastet/events/recorder.py`:

```python
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
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]


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
```

`src/bastet/events/__init__.py`:

```python
from bastet.events.recorder import ListSink, Recorder, emit, host_scope, new_run_id, phase, recording

__all__ = ["ListSink", "Recorder", "emit", "host_scope", "new_run_id", "phase", "recording"]
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/events -q`
Expected: all pass. If the invalid-event test is flaky about how many warnings print, keep the `<= 2` bound but make sure each distinct problem is reported at most once.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/events/recorder.py src/bastet/events/__init__.py tests/events/test_recorder.py
git commit -m "events: recorder with a queue, a masking consumer thread, sinks and scopes"
```

---

### Task 3: The JSONL record, retention, and `bastet log`

**Files:**
- Create: `src/bastet/events/jsonl.py`, `src/bastet/cli/log.py`
- Modify: `src/bastet/core/config.py` (`RunsConfig`), `src/bastet/cli/app.py` (register `runs`)
- Test: `tests/events/test_jsonl.py`, `tests/cli/test_log_cli.py`, a config test in `tests/core/test_config.py`

**Interfaces (produces):**
```python
def runs_dir(data: Path) -> Path                                  # data / "runs"
class JsonlSink:  name = "jsonl"; path: Path; def __init__(self, directory: Path, run_id: str)
def prune(directory: Path, *, keep_runs: int | None, keep_days: int | None, now: float | None = None) -> list[Path]   # the files removed; a limit of None keeps every run
def summarize(path: Path) -> dict      # id, command, started, status ("unfinished" without run_finished), hosts, changed, failed
def resolve_run(directory: Path, ident: str) -> Path      # an id, a unique prefix, or "latest"; BastetError otherwise
class RunsConfig(BaseModel):  keep_runs: int | None = None; keep_days: int | None = None    # Config.runs; None keeps every run
```

**Behaviour:**
- **`JsonlSink`** creates the directory `0700` and the file `0600` (exclusive create; an existing id is an error), writes one `event.to_json()` line per event and flushes each.
- **`prune`** removes the oldest files beyond `keep_runs` and any older than `keep_days` (by modification time). Only `*.jsonl` files. A file that can't be removed is reported on stderr and skipped. Returns the removed paths.
- **`summarize`** reads the first line and the last complete line (from the last 64 KB). A torn or empty file gives `status: "unfinished"` and blanks, never an error.
- **`resolve_run`:** `ident` must match `[0-9A-Za-z-]+` (anything else, such as `../x`, is an error). `latest` is the newest file. A prefix matching several files is an error naming them.
- **`bastet log`** lists the 20 newest runs (`--all` for every one) as a table: id, started, status, command, hosts. No runs: "No runs recorded yet."
- **`bastet log export <run> [--out FILE]`** prints the JSONL (or writes it to `--out`). The file is already masked, so it is written as is.
- **`runs.keep_runs` / `runs.keep_days`** in `bastet.yml`, each unset (keep every run, the default) or at least 1.

- [ ] **Step 1: Write the failing tests**

Create `tests/events/test_jsonl.py`:

```python
import json
import os
import stat
import time

import pytest

from bastet import events
from bastet.core.errors import BastetError
from bastet.events.jsonl import JsonlSink, prune, resolve_run, summarize
from bastet.events.recorder import recording


def make_run(directory, run_id="20261010-120000-aaaa", notes=2):
    sink = JsonlSink(directory, run_id)
    with recording("run -c", [sink], run_id=run_id):
        for i in range(notes):
            events.emit("note", "pve1", message=f"n{i}")
    return sink.path


def test_one_json_object_per_line_with_private_modes(tmp_path):
    path = make_run(tmp_path / "runs")
    lines = path.read_text().splitlines()
    parsed = [json.loads(line) for line in lines]
    assert [p["kind"] for p in parsed] == ["run_started", "note", "note", "run_finished"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_an_existing_run_id_is_refused(tmp_path):
    make_run(tmp_path / "runs")
    with pytest.raises(FileExistsError):
        JsonlSink(tmp_path / "runs", "20261010-120000-aaaa")


def test_prune_by_count_and_age_only_touches_jsonl(tmp_path):
    d = tmp_path / "runs"
    paths = [make_run(d, f"2026101{i}-120000-aaaa") for i in range(5)]
    (d / "notes.txt").write_text("keep")
    old = time.time() - 200 * 86400
    os.utime(paths[0], (old, old))
    removed = prune(d, keep_runs=3, keep_days=90)
    assert sorted(p.name for p in removed) == sorted(p.name for p in paths[:2])
    assert sorted(p.name for p in d.glob("*.jsonl")) == sorted(p.name for p in paths[2:])
    assert (d / "notes.txt").exists()


def test_prune_with_no_limits_keeps_everything(tmp_path):
    d = tmp_path / "runs"
    paths = [make_run(d, f"2026101{i}-120000-aaaa") for i in range(3)]
    old = time.time() - 4000 * 86400
    os.utime(paths[0], (old, old))
    assert prune(d, keep_runs=None, keep_days=None) == []
    assert len(list(d.glob("*.jsonl"))) == 3
    assert [p.name for p in prune(d, keep_runs=None, keep_days=90)] == [paths[0].name]


def test_prune_reports_a_file_it_cannot_remove_and_goes_on(tmp_path, monkeypatch, capsys):
    d = tmp_path / "runs"
    paths = [make_run(d, f"2026101{i}-120000-aaaa") for i in range(3)]
    real = type(paths[0]).unlink

    def flaky(self, *a, **k):
        if self.name.startswith("20261010"):
            raise PermissionError("nope")
        return real(self, *a, **k)

    monkeypatch.setattr(type(paths[0]), "unlink", flaky)
    removed = prune(d, keep_runs=1, keep_days=90)
    assert [p.name for p in removed] == [paths[1].name]
    assert "could not remove" in capsys.readouterr().err


def test_summarize_finished_unfinished_torn_and_empty(tmp_path):
    d = tmp_path / "runs"
    done = make_run(d, "20261010-120000-aaaa")
    info = summarize(done)
    assert info["id"] == "20261010-120000-aaaa" and info["command"] == "run -c" and info["status"] == "ok"
    unfinished = d / "20261010-130000-bbbb.jsonl"
    unfinished.write_text(done.read_text().splitlines()[0] + "\n")
    assert summarize(unfinished)["status"] == "unfinished"
    torn = d / "20261010-140000-cccc.jsonl"
    torn.write_text(done.read_text().splitlines()[0] + '\n{"kind": "run_fini')
    assert summarize(torn)["status"] == "unfinished"
    empty = d / "20261010-150000-dddd.jsonl"
    empty.write_text("")
    assert summarize(empty)["status"] == "unfinished" and summarize(empty)["command"] == ""


def test_resolve_run_by_id_prefix_latest_and_errors(tmp_path):
    d = tmp_path / "runs"
    a, b = make_run(d, "20261010-120000-aaaa"), make_run(d, "20261011-120000-bbbb")
    assert resolve_run(d, "20261010-120000-aaaa") == a
    assert resolve_run(d, "20261011") == b
    assert resolve_run(d, "latest") == b
    with pytest.raises(BastetError, match="more than one"):
        resolve_run(d, "2026101")
    with pytest.raises(BastetError, match="no run"):
        resolve_run(d, "20269999")
    for bad in ("../x", "a/b", "", ".."):
        with pytest.raises(BastetError):
            resolve_run(d, bad)


def test_latest_with_no_runs_is_a_clear_error(tmp_path):
    with pytest.raises(BastetError, match="no runs"):
        resolve_run(tmp_path / "runs", "latest")
```

Create `tests/cli/test_log_cli.py`:

```python
from bastet.cli.app import app
from bastet.core.config import data_dir
from bastet.events.jsonl import JsonlSink, runs_dir
from bastet.events.recorder import recording
from bastet import events


def record(run_id, command="run -c"):
    sink = JsonlSink(runs_dir(data_dir()), run_id)
    with recording(command, [sink], run_id=run_id):
        events.emit("host_finished", "pve1", status="ok", changed=1, failed=0, skipped=0)
    return sink.path


def test_log_with_nothing_recorded(runner, inventory):
    result = runner.invoke(app, ["log"])
    assert result.exit_code == 0 and "No runs recorded yet." in result.output


def test_log_lists_newest_first_with_status_and_command(runner, inventory):
    record("20261010-120000-aaaa", "run -c")
    record("20261011-120000-bbbb", "run -a pve1")
    result = runner.invoke(app, ["log"])
    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if "2026" in line]
    assert lines[0].startswith("  20261011-120000-bbbb") and "run -a pve1" in lines[0] and "ok" in lines[0]
    assert lines[1].startswith("  20261010-120000-aaaa")


def test_log_shows_twenty_unless_all(runner, inventory):
    for i in range(25):
        record(f"202610{i:02d}-120000-aaaa")
    assert len([l for l in runner.invoke(app, ["log"]).output.splitlines() if "2026" in l]) == 20
    assert len([l for l in runner.invoke(app, ["log", "--all"]).output.splitlines() if "2026" in l]) == 25


def test_export_prints_the_file_or_writes_it(runner, inventory, tmp_path):
    path = record("20261010-120000-aaaa")
    result = runner.invoke(app, ["log", "export", "latest"])
    assert result.exit_code == 0 and result.output == path.read_text()
    dest = tmp_path / "out.jsonl"
    result = runner.invoke(app, ["log", "export", "20261010", "--out", str(dest)])
    assert result.exit_code == 0 and dest.read_text() == path.read_text()


def test_export_errors_are_clean(runner, inventory):
    record("20261010-120000-aaaa")
    for ident in ("../etc/passwd", "nope"):
        result = runner.invoke(app, ["log", "export", ident])
        assert result.exit_code == 1 and "Traceback" not in result.output
```

Add to `tests/core/test_config.py`:

```python
def test_log_config_defaults_and_limits(tmp_path):
    from bastet.core.config import RunsConfig

    assert RunsConfig().keep_runs is None and RunsConfig().keep_days is None
    assert RunsConfig(keep_runs=10, keep_days=None).keep_runs == 10
    for bad in ({"keep_runs": 0}, {"keep_days": 0}):
        with pytest.raises(Exception):
            RunsConfig(**bad)
```
(import `pytest` at the top of that file if it isn't already imported.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/events/test_jsonl.py tests/cli/test_log_cli.py tests/core/test_config.py -q`
Expected: failures: no `bastet.events.jsonl`, no `log` command, no `RunsConfig`.

- [ ] **Step 3: Implement**

`src/bastet/core/config.py`: add (next to `ParallelConfig`) and a `runs` field on `Config`:

```python
class RunsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_runs: int | None = None  # None: keep every run
    keep_days: int | None = None

    @field_validator("keep_runs", "keep_days")
    @classmethod
    def _at_least_one(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("must be at least 1, or empty to keep every run")
        return value
```
and `runs: RunsConfig = RunsConfig()` in `Config`.

`src/bastet/events/jsonl.py`:

```python
"""The run record: one JSONL file per run under the controller's data directory."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.events.model import Event
from bastet.ui import out

_ID = re.compile(r"[0-9A-Za-z-]+")
_TAIL = 65536


def runs_dir(data: Path) -> Path:
    return data / "runs"


class JsonlSink:
    name = "jsonl"

    def __init__(self, directory: Path, run_id: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        self.path = directory / f"{run_id}.jsonl"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self._file = os.fdopen(fd, "w", encoding="utf-8")

    def handle(self, event: Event) -> None:
        self._file.write(event.to_json() + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def _files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.jsonl")) if directory.is_dir() else []


def prune(directory: Path, *, keep_runs: int | None, keep_days: int | None, now: float | None = None) -> list[Path]:
    """Remove the oldest records beyond the limits. A limit of None keeps every run."""
    files = _files(directory)
    doomed: set[Path] = set()
    if keep_runs is not None and len(files) > keep_runs:
        doomed |= set(files[:-keep_runs])
    if keep_days is not None:
        cutoff = (now if now is not None else time.time()) - keep_days * 86400
        doomed |= {f for f in files if f.stat().st_mtime < cutoff}
    removed: list[Path] = []
    for path in sorted(doomed):
        try:
            path.unlink()
            removed.append(path)
        except OSError as exc:
            out.secho(f"warning: could not remove old run record {path.name}: {exc}", fg="yellow", err=True)
    return removed


def _parse(line: str) -> dict | None:
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def summarize(path: Path) -> dict:
    info = {"id": path.stem, "command": "", "started": "", "status": "unfinished", "hosts": 0, "changed": 0, "failed": 0}
    try:
        with path.open("rb") as f:
            first = f.readline().decode("utf-8", "replace")
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - _TAIL))
            tail = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return info
    started = _parse(first)
    if started and started.get("kind") == "run_started":
        info["command"] = started["data"].get("command", "")
        info["started"] = started.get("t", "")
    finished = _parse(tail[-1]) if tail else None
    if finished and finished.get("kind") == "run_finished":
        data = finished["data"]
        info.update(status=data.get("status", "unfinished"), hosts=data.get("hosts", 0),
                    changed=data.get("changed", 0), failed=data.get("failed", 0))
    return info


def resolve_run(directory: Path, ident: str) -> Path:
    if not _ID.fullmatch(ident):
        raise BastetError(f"{ident!r} is not a run id")
    files = _files(directory)
    if ident == "latest":
        if not files:
            raise BastetError("no runs recorded yet")
        return files[-1]
    matches = [f for f in files if f.stem.startswith(ident)]
    if not matches:
        raise BastetError(f"no run matching {ident!r}")
    if len(matches) > 1:
        raise BastetError(f"more than one run matches {ident!r}: " + ", ".join(f.stem for f in matches))
    return matches[0]
```

`src/bastet/cli/log.py`:

```python
"""`bastet log`: the records of past runs on this computer."""

import sys
from pathlib import Path

import typer

from bastet.cli.common import handles_errors
from bastet.core.config import data_dir
from bastet.events.jsonl import _files, resolve_run, runs_dir, summarize
from bastet.ui import out

log_app = typer.Typer(invoke_without_command=True, help="Records of past runs on this computer.")


@log_app.callback(invoke_without_command=True)
@handles_errors
def log_list(
    ctx: typer.Context,
    all_: bool = typer.Option(False, "--all", help="List every recorded run, not just the newest 20."),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    files = list(reversed(_files(runs_dir(data_dir()))))
    if not files:
        out.echo("No runs recorded yet.")
        return
    rows = []
    for path in files if all_ else files[:20]:
        info = summarize(path)
        rows.append([info["id"], info["started"][:19].replace("T", " "), info["status"], info["command"],
                     f"{info['hosts']} host{'s' if info['hosts'] != 1 else ''}"])
    out.table(rows)


@log_app.command("export")
@handles_errors
def export(
    run: str = typer.Argument(..., help="A run id, the start of one, or 'latest'."),
    out_path: Path | None = typer.Option(None, "--out", "-o", help="Write to this file instead of printing."),
) -> None:
    """Print a run's full record (JSON lines), or write it to a file."""
    path = resolve_run(runs_dir(data_dir()), run)
    text = path.read_text(encoding="utf-8")
    if out_path is not None:
        out_path.write_text(text, encoding="utf-8")
        return
    sys.stdout.write(text)  # the record was masked when written; print it exactly
```

`src/bastet/cli/app.py`: after the `doctor` registration add:

```python
from bastet.cli.runs import log_app  # noqa: E402

app.add_typer(log_app, name="log")
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/events tests/cli/test_log_cli.py tests/core/test_config.py -q`
Expected: all pass. If `test_runs_lists_newest_first_with_status_and_command` fails on the leading spaces, check `out.table`'s indent (two spaces) and not the test.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/events/jsonl.py src/bastet/cli/log.py src/bastet/core/config.py src/bastet/cli/app.py tests/events/test_jsonl.py tests/cli/test_log_cli.py tests/core/test_config.py
git commit -m "events: the JSONL run record, retention, and bastet log / log export"
```

---

### Task 4: Emissions in the engine

**Files:**
- Modify: `src/bastet/engine/run.py`
- Test: `tests/engine/test_run_events.py`

**Interfaces (consumes):** `bastet.events` (`emit`, `phase`). **Produces:** no new public names; `run_host` keeps its signature and return value. `_read` and `_exec` gain keyword arguments (`host`, `phase`, and for `_exec` `hidden`); nothing else calls them.

**Behaviour:**
- `run_host` runs inside these phases, in order: `collect`, `read`, `compare`, and with `apply=True` also `apply` and `verify` (only when something changed). `phase_started`/`phase_finished` bracket each.
- **`item_checked`** (data: `item`, `family`, `status`, `phase`, `changes` (the `change_text` strings, secret values hidden), `error`, `diff`, `origins`) is emitted: for every item after `compare` (`phase: compare`); for every item the apply loop settles, whether `changed`, `failed` or `skipped` (`phase: apply`); and for every changed item after verification (`phase: verify`, status `changed` if verified, `failed` otherwise).
- **`command_run`** (data: `phase`, `command`, `exit`, `duration`, `stdout`, `stderr`, `error`, `hidden`) is emitted for each read script (phase `read`, or `apply`/`verify` for re-reads), each fix (phase `apply`) and each trigger (phase `on_change`).
  - A read's `command` is `read <first five labels>` plus ` … (+N more)`; its `stdout`/`stderr` are always empty.
  - A fix or trigger keeps its text and output, **unless any resource in it is `secret`**: then `command` is `(hidden: secret resource)`, `hidden` is true, and the output is empty.
  - A runner error gives `exit: None` and `error: <message>`.
- **`trigger_fired`** (`trigger`, `ok`, `error`) follows each trigger's command event.
- The returned `HostRun` is exactly what it was before.

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_run_events.py`:

```python
import json

from bastet.core.remote import LocalRunner
from bastet.core.secrets.redact import ACTIVE
from bastet.engine.model import Trigger
from bastet.engine.run import Batch, run_host
from bastet.events import ListSink, recording
from engine_fakes import Broken, Flag, NoSystemd


def record(fn):
    sink = ListSink()
    with recording("test", [sink]):
        fn()
    return [e for e in sink.events if e.kind not in ("run_started", "run_finished")]


def shape(evts):
    return [(e.kind, e.data.get("phase")) for e in evts]


def test_a_check_emits_the_read_side_phases_only(tmp_path):
    p = tmp_path / "a"
    evts = record(lambda: run_host(LocalRunner(), "pve1", [Batch("one", [Flag(path=str(p), value="1")])], apply=False))
    assert shape(evts) == [
        ("phase_started", "collect"), ("phase_finished", "collect"),
        ("phase_started", "read"), ("command_run", "read"), ("phase_finished", "read"),
        ("phase_started", "compare"), ("item_checked", "compare"), ("phase_finished", "compare"),
    ]
    item = next(e for e in evts if e.kind == "item_checked")
    assert item.host == "pve1" and item.data["status"] == "would-change" and item.data["changes"] == ["value: (absent) → 1"]
    assert not p.exists()


def test_an_apply_emits_apply_commands_triggers_and_verification(tmp_path):
    p = tmp_path / "a"
    batch = Batch("one", [Flag(path=str(p), value="1")])
    sink = ListSink()
    with recording("test", [sink]):
        run_host(LocalRunner(), "pve1", [batch], apply=True)
    evts = [e for e in sink.events if e.kind not in ("run_started", "run_finished")]
    phases = [e.data["phase"] for e in evts if e.kind == "phase_started"]
    assert phases == ["collect", "read", "compare", "apply", "verify"]
    fix = next(e for e in evts if e.kind == "command_run" and e.data["phase"] == "apply")
    assert fix.data["exit"] == 0 and fix.data["hidden"] is False and "printf" in fix.data["command"] and fix.data["duration"] >= 0
    final = [e for e in evts if e.kind == "item_checked" and e.data["phase"] == "apply"]
    assert [e.data["status"] for e in final] == ["changed"]
    verified = [e for e in evts if e.kind == "item_checked" and e.data["phase"] == "verify"]
    assert [e.data["status"] for e in verified] == ["changed"]


def test_triggers_emit_a_command_and_a_trigger_event(tmp_path):
    marker = tmp_path / "marker"
    trigger = Trigger("touch marker", f"touch {marker}", root=False)
    flag = Flag(path=str(tmp_path / "a"), value="1", on_change=(trigger,))
    evts = record(lambda: run_host(LocalRunner(), "pve1", [Batch("one", [flag])], apply=True))
    cmd = [e for e in evts if e.kind == "command_run" and e.data["phase"] == "on_change"]
    fired = [e for e in evts if e.kind == "trigger_fired"]
    assert len(cmd) == 1 and len(fired) == 1 and fired[0].data["ok"] is True and fired[0].data["trigger"] == "touch marker"
    assert marker.exists()


def test_a_failing_fix_records_its_exit_and_stderr_and_skips_the_rest(tmp_path):
    batch = Batch("one", [Broken(path=str(tmp_path / "a"), value="1"), Flag(path=str(tmp_path / "b"), value="2")])
    evts = record(lambda: run_host(LocalRunner(), "pve1", [batch], apply=True))
    fix = next(e for e in evts if e.kind == "command_run" and e.data["phase"] == "apply")
    assert fix.data["exit"] == 3 and "boom" in fix.data["stderr"]
    settled = {e.data["item"].split("/")[-1]: e.data["status"] for e in evts if e.kind == "item_checked" and e.data["phase"] == "apply"}
    assert settled == {"a": "failed", "b": "skipped"}


def test_a_read_never_records_its_output(tmp_path):
    p = tmp_path / "a"
    p.write_text("file-contents-that-might-be-secret")
    evts = record(lambda: run_host(LocalRunner(), "pve1", [Batch("one", [Flag(path=str(p), value="1")])], apply=False))
    read = next(e for e in evts if e.kind == "command_run")
    assert read.data["stdout"] == "" and read.data["stderr"] == "" and read.data["command"].startswith("read ")
    assert "file-contents-that-might-be-secret" not in "".join(e.to_json() for e in evts)


def test_a_secret_resource_hides_its_command_output_changes_and_diff(tmp_path):
    ACTIVE.add("unrelated-value")  # the masker knows nothing about the secret below
    secret = "s3cret-value-xyz"
    evts = record(lambda: run_host(LocalRunner(), "pve1", [Batch("one", [Flag(path=str(tmp_path / "a"), value=secret, secret=True)])], apply=True))
    blob = "".join(e.to_json() for e in evts)
    assert secret not in blob
    fix = next(e for e in evts if e.kind == "command_run" and e.data["phase"] == "apply")
    assert fix.data["hidden"] is True and fix.data["command"] == "(hidden: secret resource)" and fix.data["stdout"] == ""
    item = next(e for e in evts if e.kind == "item_checked" and e.data["phase"] == "compare")
    assert item.data["changes"] == ["value: (secret) → (secret)"] and item.data["diff"] is None


def test_an_unsupported_item_is_reported_as_skipped(tmp_path):
    evts = record(lambda: run_host(LocalRunner(), "pve1", [Batch("one", [NoSystemd(path=str(tmp_path / "a"), value="1")])], apply=False))
    item = next(e for e in evts if e.kind == "item_checked")
    assert item.data["status"] == "skipped" and "no systemd" in item.data["error"]


def test_events_agree_with_the_host_run(tmp_path):
    batch = Batch("one", [Flag(path=str(tmp_path / "a"), value="1"), Broken(path=str(tmp_path / "b"), value="2"), Flag(path=str(tmp_path / "c"), value="3")])
    result = {}
    evts = record(lambda: result.setdefault("run", run_host(LocalRunner(), "pve1", [batch], apply=True)))
    run = result["run"]
    last = {}
    for e in evts:
        if e.kind == "item_checked":
            last[e.data["item"]] = e.data["status"]
    assert last == {i.resource.label: i.status for i in run.items}


def test_an_unrecorded_run_is_unchanged(tmp_path):
    run = run_host(LocalRunner(), "pve1", [Batch("one", [Flag(path=str(tmp_path / "a"), value="1")])], apply=True)
    assert run.ok and run.count("changed") == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/engine/test_run_events.py -q`
Expected: failures, no events are emitted yet (empty lists).

- [ ] **Step 3: Implement** (`src/bastet/engine/run.py`)

Add `import time` and `from bastet import events` at the top, then these helpers above `run_host`:

```python
def _item_event(host: str, item: Item, phase: str) -> None:
    from bastet.engine.report import change_text  # lazy: report imports this module

    events.emit(
        "item_checked", host, item=item.resource.label, family=item.resource.family, status=item.status, phase=phase,
        changes=[change_text(c, secret=item.resource.secret) for c in item.changes],
        error=item.error, diff=item.diff, origins=list(item.origins),
    )


def _command_event(host: str, phase: str, command: str, exit_code: int | None, started: float, *,
                   stdout: str = "", stderr: str = "", error: str | None = None, hidden: bool = False) -> None:
    events.emit("command_run", host, phase=phase, command=command, exit=exit_code,
                duration=round(time.monotonic() - started, 3), stdout=stdout, stderr=stderr, error=error, hidden=hidden)


def _read_label(items: list[Item]) -> str:
    labels = [i.resource.label for i in items]
    extra = f" … (+{len(labels) - 5} more)" if len(labels) > 5 else ""
    return "read " + ", ".join(labels[:5]) + extra
```

Replace `_read` and `_exec`:

```python
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
```

Then change `run_host` as follows (the logic is unchanged; only the marked lines are new or edited):

```python
    with events.phase(host, "collect"):
        planned = collect_items(batches)
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
    host_broken: str | None = None
    with events.phase(host, "apply"):
        for batch, mine in planned:  # phase 4
            ... (the existing batch loop, indented one level, with these additions)
```

Additions inside the batch loop (everything else stays as it is):
- Right after each of the three `item.status, item.error = "skipped", ...` assignments in the loop (stopped, `host_broken`, `broken`): `_item_event(host, item, "apply")` before the `continue`.
- In the `touched` re-read branch: `_assess(item, _read(runner, [item], host=host, phase="apply")[0])`, and when it ends `!= "would-change"`: `_item_event(host, item, "apply")` before `continue` (keep the `broken` update as it is).
- The fix call becomes: `ok, error = _exec(runner, commands, any(g.resource.root for g in group), fix_timeout, host=host, phase="apply", hidden=any(g.resource.secret for g in group))`.
- After `g.status, g.error = "failed", error` for each `g` in the failure branch: `_item_event(host, g, "apply")`.
- After `g.status = "changed"` in the success branch: `_item_event(host, g, "apply")`.
- Triggers: 
  ```python
  ok, error = _exec(runner, [t.command], t.root, fix_timeout, host=host, phase="on_change")
  run.triggers.append(TriggerRun(t, ok, error))
  events.emit("trigger_fired", host, trigger=t.label, ok=ok, error=error)
  ```

The verify block becomes:

```python
    if changed:  # phase 6
        with events.phase(host, "verify"):
            for item, results in zip(changed, _read(runner, changed, host=host, phase="verify")):
                ... (existing body; call `_item_event(host, item, "verify")` once per item, after its final status is set,
                     including before each `continue`)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/engine -q`
Expected: the new tests pass and every existing engine test passes unmodified. If an existing test calls `_read` or `_exec` directly, update only its call to pass `host="h", phase="read"` (and say so in the commit message).

- [ ] **Step 5: Commit**

```bash
git add src/bastet/engine/run.py tests/engine/test_run_events.py
git commit -m "engine: emit phase, item, command and trigger events from run_host"
```

---

### Task 5: The live terminal view (`-vv` and above)

**Files:**
- Create: `src/bastet/events/terminal.py`
- Test: `tests/events/test_terminal_sink.py`

**Interfaces (consumes):** `Event`, `bastet.ui.out`. **Produces:** `TerminalSink(level: int)` with `name = "terminal"`, `handle(event)`, `close()`.

**Behaviour:** `level` is the display level, 2 to 4 (`-vv` is 2). An event is shown when `event.level <= level`; `command_run` output is shown only at level 4. Every line is prefixed `<host>: ` when the event has a host. Lines and styles:

| event | line | style |
|---|---|---|
| `host_started` | `<mode> started` | dim |
| `host_finished` | `<status>: N changed · N failed · N skipped` | green / red for `error`, `failed` |
| `host_skipped` | `skipped: <reason>` | dim |
| `phase_started` | `<phase>…` | dim |
| `phase_finished` | `<phase> done (0.3s)` | dim |
| `item_checked` | `  <mark> <item>  <status>`, then each change on its own line indented 6, then the error in red | by status (below) |
| `command_run` | `  $ <command>  → exit N (0.2s)` or `→ error (0.2s)`; at level 4 its stdout then stderr lines indented 4 | dim |
| `trigger_fired` | `  trigger <label> ✓` / `✗ <error>` | green / red |
| `note` | the message | yellow |
| `run_finished` | `run <id>: <status> in 12.3s (bastet log export <id>)` | dim |

Marks and styles by item status: `compliant` ✓ green, `changed` ✓ green, `would-change` ~ yellow, `attention` ⚠ yellow, `failed` ✗ red, `skipped` – dim. `run_started` prints nothing.

- [ ] **Step 1: Write the failing tests**

Create `tests/events/test_terminal_sink.py`:

```python
import io
import time

from bastet.events.model import make_event
from bastet.events.terminal import TerminalSink
from bastet.ui import Console, use


def ev(kind, host="pve1", **data):
    return make_event(kind, "20261010-120000-ab12", time.monotonic(), host, data)


def render(level, *events):
    buf = io.StringIO()
    with use(Console(buf, io.StringIO(), color=False)):
        sink = TerminalSink(level)
        for e in events:
            sink.handle(e)
    return buf.getvalue()


ITEM = ev("item_checked", item="/etc/motd", status="would-change", phase="compare", changes=["differs → update"], error=None)
CMD = ev("command_run", phase="apply", command="printf x > /etc/motd", exit=0, duration=0.25, stdout="out line", stderr="err line", error=None, hidden=False)


def test_level_two_shows_items_and_phases_but_not_commands():
    text = render(2, ev("phase_started", phase="read"), ITEM, CMD, ev("phase_finished", phase="read", duration=0.3))
    assert "pve1: read…" in text and "pve1:   ~ /etc/motd  would-change" in text
    assert "pve1:       differs → update" in text and "read done (0.3s)" in text
    assert "$ " not in text


def test_level_three_adds_commands_with_exit_and_timing_but_no_output():
    text = render(3, CMD)
    assert "pve1:   $ printf x > /etc/motd  → exit 0 (0.2s)" in text or "(0.3s)" in text
    assert "out line" not in text


def test_level_four_adds_output():
    text = render(4, CMD)
    assert "pve1:     out line" in text and "pve1:     err line" in text


def test_compliant_items_are_level_two_so_a_level_one_view_would_hide_them():
    compliant = ev("item_checked", item="/etc/ok", status="compliant", phase="compare", changes=[], error=None)
    assert "/etc/ok" in render(2, compliant)


def test_failed_item_shows_its_error_and_a_hidden_command_shows_no_output():
    failed = ev("item_checked", item="/etc/x", status="failed", phase="apply", changes=[], error="boom")
    hidden = ev("command_run", phase="apply", command="(hidden: secret resource)", exit=1, duration=0.1, stdout="", stderr="", error=None, hidden=True)
    text = render(4, failed, hidden)
    assert "✗ /etc/x  failed" in text and "boom" in text and "(hidden: secret resource)" in text


def test_run_level_and_host_level_lines():
    text = render(
        2,
        ev("host_started", mode="apply"),
        ev("host_finished", status="ok", changed=2, failed=0, skipped=1),
        ev("host_skipped", host="media01", reason="not managed"),
        ev("trigger_fired", trigger="restart chrony", ok=False, error="no unit"),
        ev("note", host=None, message="careful"),
        ev("run_finished", host=None, status="ok", duration=12.34),
    )
    assert "pve1: apply started" in text and "pve1: ok: 2 changed · 0 failed · 1 skipped" in text
    assert "media01: skipped: not managed" in text and "trigger restart chrony ✗ no unit" in text
    assert "careful" in text and "run 20261010-120000-ab12: ok in 12.3s" in text
    assert render(2, ev("run_started", host=None, command="run", schema=1)) == ""


def test_a_sink_never_raises_on_odd_data():
    odd = ev("item_checked", item="/x", status="mystery", phase="compare", changes=None, error=None)
    assert "/x" in render(2, odd)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/events/test_terminal_sink.py -q`
Expected: `No module named 'bastet.events.terminal'`.

- [ ] **Step 3: Implement**

`src/bastet/events/terminal.py`:

```python
"""The live view of a run's events on the terminal, from -vv."""

from __future__ import annotations

from bastet.events.model import Event
from bastet.ui import out

MARKS = {
    "compliant": ("✓", "green"), "changed": ("✓", "green"), "would-change": ("~", "yellow"),
    "attention": ("⚠", "yellow"), "failed": ("✗", "red"), "skipped": ("–", "dim"),
}


class TerminalSink:
    name = "terminal"

    def __init__(self, level: int) -> None:
        self.level = level

    def close(self) -> None:
        pass

    def handle(self, event: Event) -> None:
        if event.level > self.level:
            return
        for text, style in self._lines(event):
            out.secho(text, style)

    def _lines(self, e: Event) -> list[tuple[str, str | None]]:
        h = f"{e.host}: " if e.host else ""
        d = e.data
        if e.kind == "host_started":
            return [(f"{h}{d['mode']} started", "dim")]
        if e.kind == "host_finished":
            counts = f"{d.get('changed', 0)} changed · {d.get('failed', 0)} failed · {d.get('skipped', 0)} skipped"
            bad = d["status"] in ("error", "failed")
            return [(f"{h}{d['status']}: {counts}", "red" if bad else "green")]
        if e.kind == "host_skipped":
            return [(f"{h}skipped: {d['reason']}", "dim")]
        if e.kind == "phase_started":
            return [(f"{h}{d['phase']}…", "dim")]
        if e.kind == "phase_finished":
            return [(f"{h}{d['phase']} done ({d['duration']:.1f}s)", "dim")]
        if e.kind == "item_checked":
            mark, style = MARKS.get(d["status"], ("·", None))
            lines: list[tuple[str, str | None]] = [(f"{h}  {mark} {d['item']}  {d['status']}", style)]
            lines += [(f"{h}      {change}", style) for change in d.get("changes") or []]
            if d.get("error"):
                lines.append((f"{h}      {d['error']}", "red"))
            return lines
        if e.kind == "command_run":
            result = "error" if d["exit"] is None else f"exit {d['exit']}"
            lines = [(f"{h}  $ {d['command']}  → {result} ({d['duration']:.1f}s)", "dim")]
            if self.level >= 4:
                for stream in ("stdout", "stderr"):
                    lines += [(f"{h}    {line}", "dim") for line in (d.get(stream) or "").splitlines()]
            return lines
        if e.kind == "trigger_fired":
            ok = d["ok"]
            return [(f"{h}  trigger {d['trigger']} " + ("✓" if ok else f"✗ {d.get('error') or ''}".rstrip()),
                     "green" if ok else "red")]
        if e.kind == "note":
            return [(f"{h}{d['message']}", "yellow")]
        if e.kind == "run_finished":
            return [(f"run {e.run_id}: {d['status']} in {d['duration']:.1f}s (bastet log export {e.run_id})", "dim")]
        return []
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/events/test_terminal_sink.py -q`
Expected: all pass. The `0.25` duration rounds to `0.2` or `0.3` depending on float formatting; the test accepts both, so don't "fix" the formatting.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/events/terminal.py tests/events/test_terminal_sink.py
git commit -m "events: the live terminal view for -vv and above"
```

---

### Task 6: Wire the recording into `bastet run`

**Files:**
- Modify: `src/bastet/cli/common.py` (`recorded_run`), `src/bastet/cli/run.py`, `src/bastet/cli/gather.py`
- Test: `tests/cli/test_run_recording.py`

**Interfaces (consumes):** Tasks 2, 3 and 5. **Produces:** `recorded_run(command: str, verbose: int = 0)` in `cli/common.py`, a context manager yielding the `Recorder`.

**Behaviour:**
- **`recorded_run`:** loads `runs` settings from the config (defaults when the config can't be read), prunes old records, opens a `JsonlSink` for a new run id, and, when `verbose >= 2`, adds `TerminalSink(min(verbose, 4))`. If the JSONL can't be opened or pruned (unwritable directory, a file in its place), it prints `warning: not recording this run: <error>` on stderr and carries on without that sink.
- **`bastet run -v`** becomes a count. `-v` keeps today's meaning (show compliant items: `verbose >= 1` is what `_run` receives as its bool); `-vv`, `-vvv`, `-vvvv` set the live view level.
- **`run()`** wraps its whole body (the `-g`, `-c`, `-a` and default paths) in `recorded_run(<command>, verbose)`. The command text is `run` plus the flags given (`-g`, `-c`, `-a`, `--exclude X`) and the selectors, in that order. `typer.Exit` sets `rec.status` to `ok` for exit code 0 and `failed` otherwise; the existing `KeyboardInterrupt` handler sets `rec.status = "interrupted"` before it raises `typer.Exit(1)`.
- **Host scopes:** `check_work` runs inside `host_scope(host, "check")`, `apply_work` inside `host_scope(host, "apply")`, and gather's `work` inside `host_scope(host, "gather")`. They call `scope.record(<HostRun>)` with the check or apply result (for the apply, the apply's own `HostRun`, not the lynis one); gather sets `scope.status = "failed"` when its command failed.
- **Skips:** each place that prints that a host is skipped or has nothing to do also emits `host_skipped` with the same reason: `not managed`, `no roles`, `nothing to manage yet`, gather's `gather: false`, and a planning error (`error: <message>`).

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_run_recording.py`. Base the end-to-end setup on the closest existing test in `tests/cli/test_check_apply.py` (read how it points a host at a local runner and a role file, and reuse that fixture or helper; do not invent a new way to fake the connection). Tests:

```python
import json

from bastet.cli.app import app
from bastet.core.config import data_dir
from bastet.events.jsonl import runs_dir


def records():
    return sorted(runs_dir(data_dir()).glob("*.jsonl"))


def events_of(path):
    return [json.loads(line) for line in path.read_text().splitlines()]
```

1. **A check leaves one record:** after `run -c` on the prepared host (reuse the setup above), `records()` has exactly one file; its first event is `run_started` with `data.command == "run -c"` and `schema == 1`; its last is `run_finished` with `status == "ok"`; it contains `host_started`, `phase_started`, `item_checked` and `host_finished` events for the host; and `host_finished.data.status` agrees with the printed result.
2. **An apply** record has a `command_run` event with `phase == "apply"` and `exit == 0`.
3. **Nothing printed changes below `-vv`:** the output of `run -c` and `run -c -v` has no `read…` or `$ ` lines; `run -c -vv` prints `pve1: read…` and per-item lines; `-vvv` adds `$ ` command lines; `-vvvv` adds output lines. `-v` still shows compliant items as before.
4. **A failing command records `failed`:** `run -c` against an inventory with a role error (use the unknown-role setup from `test_run_cli.py`) exits non-zero and the record's `run_finished.data.status == "failed"`.
5. **Early exits are `ok`:** `run` on an inventory with no hosts prints "No hosts yet" (or the existing message), exits 0, and the record says `ok` with `hosts == 0`.
6. **The record can't be written:** set `XDG_DATA_HOME` to a path whose `bastet` entry is a regular file (create the file); `run -c` still exits with its normal code and result, prints `warning: not recording this run` on stderr, and `-vv` still prints the live view.
7. **A skipped host is recorded:** an `other`-type host in the inventory gives a `host_skipped` event with `reason == "not managed"`.
8. **`bastet log`** lists the run that `run -c` just made.
9. **Secrets:** register a secret value (`ACTIVE.add("hunter2-value")`) and use it as a role option via the secret mechanism the existing `test_secret_leaks.py` uses; the record, `-vvvv` output and `log export` contain no `hunter2-value`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/cli/test_run_recording.py -q`
Expected: failures: no records are written.

- [ ] **Step 3: Implement**

`src/bastet/cli/common.py`: add

```python
@contextlib.contextmanager
def recorded_run(command: str, verbose: int = 0):
    """The record of this run: a JSONL file on the controller, plus the live view from -vv."""
    from bastet.core.config import RunsConfig
    from bastet.events import new_run_id, recording
    from bastet.events.jsonl import JsonlSink, prune, runs_dir
    from bastet.events.terminal import TerminalSink

    try:
        runs_cfg = load_config(config_path()).runs
    except BastetError:
        runs_cfg = RunsConfig()
    run_id = new_run_id()
    sinks: list = []
    try:
        directory = runs_dir(data_dir())
        prune(directory, keep_runs=runs_cfg.keep_runs, keep_days=runs_cfg.keep_days)
        sinks.append(JsonlSink(directory, run_id))
    except OSError as exc:
        out.secho(f"warning: not recording this run: {exc}", fg="yellow", err=True)
    if verbose >= 2:
        sinks.append(TerminalSink(min(verbose, 4)))
    with recording(command, sinks, run_id=run_id) as recorder:
        yield recorder
```

`src/bastet/cli/run.py`:
- Change the option: `verbose: int = typer.Option(0, "--verbose", "-v", count=True, help="Show compliant items (-v); live events (-vv), commands (-vvv) and their output (-vvvv).")`.
- In `run()`, after the `check and apply_` validation, build `command` and wrap the existing `with guard_prompts():` body:

  ```python
  command = " ".join(["run", *(["-g"] if gather else []), *(["-c"] if check else []), *(["-a"] if apply_ else []),
                      *[arg for x in exclude for arg in ("--exclude", x)], *(hosts or [])])
  with guard_prompts(), recorded_run(command, verbose) as rec:
      try:
          ... existing body, with verbose=verbose >= 1 wherever `_run(...)` is called ...
      except typer.Exit as exc:
          rec.status = "ok" if (exc.exit_code or 0) == 0 else "failed"
          raise
  ```
  In the existing `except KeyboardInterrupt:` handler add `rec.status = "interrupted"` before `raise typer.Exit(1) from None`.
- `check_work`: wrap the body in `with events.host_scope(host, "check") as scope:` and after `run_host(...)`: `scope.record(result)`; return it. `apply_work`: `with events.host_scope(host, "apply") as scope:`; after the apply `done = run_host(...)` (when not `None`): `scope.record(done)`. Import `from bastet import events`.
- At each skip print in `_run` (`not managed by Bastet`, `no roles`, `nothing to manage yet`) add `events.emit("host_skipped", doc.name, reason=<the same reason>)`; in the `except BastetError as exc:` planning handler add `events.emit("host_skipped", doc.name, reason=f"error: {exc.message}")` next to the red message.

`src/bastet/cli/gather.py`: in `work`, wrap in `with events.host_scope(host, "gather") as scope:` and set `scope.status = "failed"` before returning the `("failed", ...)` tuple; at the `skipped (gather: false)` echoes add `events.emit("host_skipped", doc.name, reason="gather: false")`.

Imports: `contextlib`, `data_dir`, `config_path`, `load_config` are already imported in `common.py`; check before adding.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/cli/test_run_recording.py tests/cli/test_run_cli.py tests/cli/test_check_apply.py tests/cli/test_apply_parallel.py tests/cli/test_gather.py tests/cli/test_gather_parallel.py -q`
Expected: the new tests pass and every existing test passes unmodified.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/cli/common.py src/bastet/cli/run.py src/bastet/cli/gather.py tests/cli/test_run_recording.py
git commit -m "run: record every run as events (JSONL), live view from -vv, host scopes and skips"
```

---

### Task 7: `bastet init` asks how long to keep run records

**Files:**
- Modify: `src/bastet/core/initialize.py` (`InitOptions.keep_days`, the config it writes), `src/bastet/cli/init.py` (option, prompt, summary line)
- Test: `tests/core/test_initialize.py`, `tests/cli/test_init.py`

**Behaviour:**
- **Only when `init` creates a new config.** If a config already exists it is left alone, and the existing "Using <file> (edit it to change …)" line gains "or how long run records are kept".
- **The question:** `Keep run records for how many days? (Enter to keep them forever)`. Enter, blank or `forever` keeps every run; a whole number of 1 or more is the number of days; anything else (text, 0, negative) says `Enter a number of days, or press Enter to keep every run.` and asks again.
- **`--keep-days N`** (minimum 1) answers it without asking. `-y` means forever.
- **The config it writes** always has the knobs visible: `runs: {keep_runs: null, keep_days: null}`, or `keep_days: N` when a number was given. `keep_runs` is never asked; it stays `null`.
- **The summary** before "Go ahead?" gains `  run records  kept forever` or `  run records  kept for N days`.

- [ ] **Step 1: Write the failing tests**

In `tests/core/test_initialize.py` (use the existing `opts(...)` helper; add `keep_days` to its defaults dict as `None`):

```python
def test_init_writes_the_retention_knobs_visible_and_forever_by_default(tmp_path):
    cfg = tmp_path / "cfg" / "bastet.yml"
    initialize(cfg, opts(tmp_path), keys_dir=tmp_path / "cfg" / "ssh")
    text = cfg.read_text()
    assert "keep_runs" in text and "keep_days" in text
    loaded = load_config(cfg)
    assert loaded.runs.keep_runs is None and loaded.runs.keep_days is None


def test_init_writes_a_chosen_number_of_days(tmp_path):
    cfg = tmp_path / "cfg" / "bastet.yml"
    initialize(cfg, opts(tmp_path, keep_days=45), keys_dir=tmp_path / "cfg" / "ssh")
    assert load_config(cfg).runs.keep_days == 45 and load_config(cfg).runs.keep_runs is None


def test_init_leaves_an_existing_config_alone(tmp_path):
    cfg = tmp_path / "cfg" / "bastet.yml"
    initialize(cfg, opts(tmp_path, keep_days=45), keys_dir=tmp_path / "cfg" / "ssh")
    before = cfg.read_text()
    initialize(cfg, opts(tmp_path, keep_days=7), keys_dir=tmp_path / "cfg" / "ssh")
    assert cfg.read_text() == before
```

In `tests/cli/test_init.py` (follow the file's existing way of invoking `init` with a temporary `BASTET_CONFIG`; read two existing tests first):

```python
def test_init_yes_keeps_run_records_forever(...):          # -y, no question asked; summary says "run records  kept forever"
def test_init_keep_days_option(...):                       # --keep-days 30 -y; config has keep_days 30; summary "kept for 30 days"
def test_init_asks_and_enter_means_forever(...):           # interactive; the keep-days answer is just Enter; config has null
def test_init_reasks_on_a_bad_answer(...):                 # answers "abc", "0", then "45"; two "Enter a number of days" lines; config 45
def test_init_with_an_existing_config_does_not_ask(...):   # second run: no "Keep run records" prompt, config unchanged
```
Write these out fully against the file's existing helpers; the prompt order is: after the lab and domain questions, before the stylesheet question.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/core/test_initialize.py tests/cli/test_init.py -q`
Expected: failures: no `keep_days` field, no question.

- [ ] **Step 3: Implement**

`InitOptions` gains `keep_days: int | None = None`. In `initialize()`'s new-config branch:

```python
data = {"inventory": inventory, "ssh": {...as before...},
        "runs": {"keep_runs": None, "keep_days": options.keep_days}}
```
(`dump_frontmatter` must write `null` for `None`; if it writes something `load_config` rejects, fix the writer for `None`, not the config model.)

In `cli/init.py`:

```python
def _ask_keep_days(yes: bool) -> int | None:
    if yes:
        return None
    while True:
        answer = typer.prompt("Keep run records for how many days? (Enter to keep them forever)",
                              default="", show_default=False).strip().lower()
        if answer in ("", "forever"):
            return None
        if answer.isdigit() and int(answer) >= 1:
            return int(answer)
        out.echo("Enter a number of days, or press Enter to keep every run.")
```
Add `keep_days: int | None = typer.Option(None, "--keep-days", min=1, help="Keep run records this many days (default: forever).")`. After the stylesheet question: `days = keep_days if keep_days is not None else _ask_keep_days(yes)` when `existing is None`, else `None`; pass `keep_days=days` into `InitOptions`; add the summary line after the stylesheet line (only when `existing is None`).

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/core/test_initialize.py tests/cli/test_init.py tests/core/test_config.py -q`
Expected: all pass, and no existing init test edited except adding `keep_days` to the `opts` helper.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/core/initialize.py src/bastet/cli/init.py tests/core/test_initialize.py tests/cli/test_init.py
git commit -m "init: ask how long to keep run records (Enter keeps every run)"
```

---

### Task 8: Docs, roadmap, spec, and a real-terminal check

**Files:**
- Modify: `src/bastet/data/docs/commands.md`, `src/bastet/data/docs/troubleshooting.md`, `docs/ROADMAP.md`, `docs/specs/2026-10-10-bastet-console-output-design.md`
- Test: `tests/core/test_docs.py` (the existing docs tests must stay green)

- [ ] **Step 1: Docs**
  - `commands.md`: document `bastet run -v/-vv/-vvv/-vvvv`, `bastet log` and `bastet log export <run> [--out FILE]`.
  - `troubleshooting.md`: one paragraph: every run is recorded under `~/.local/share/bastet/runs/`, kept forever unless `runs.keep_runs` or `runs.keep_days` is set in `bastet.yml`; the record is masked but contains command output, so treat it like logs.
  - Plain user-facing text, no plan or spec references.
- [ ] **Step 2: Spec.** Check the "Plan 2: events and JSONL" section of the spec against what was built, and record the decisions from this plan's "Decisions made while planning" that it doesn't already state.
- [ ] **Step 3: Roadmap.** In "Run logs (milestone 3b)" mark plan 2 done (events, JSONL, `-vv` live view, `bastet log`), leave plan 3 (run notes, Runs Bases, `--log-level`) not started, and update "Now" to name plan 3 as next. Leave the "Turning git off" item alone.
- [ ] **Step 4: Run** `uv run pytest tests/core/test_docs.py tests/events -q` and `scripts/privacy-check`. Expected: green, and the privacy check prints nothing.
- [ ] **Step 5: Real-terminal check (the user does this).** In a terminal against a sandbox inventory (the `run-bastet` skill sets one up): `bastet run -c -vv` shows phases and per-item lines coloured by status; `-vvv` adds `$ command → exit 0 (0.2s)` lines; `-vvvv` adds output; `bastet log` lists the run; `bastet log export latest | head -3` prints JSON lines; the file under `~/.local/share/bastet/runs/` is mode `0600`; a deliberately wrong role option fails the host but still leaves a record ending in `run_finished` with `status: failed`.
- [ ] **Step 6: Commit**

```bash
git add src/bastet/data/docs/commands.md src/bastet/data/docs/troubleshooting.md docs/ROADMAP.md docs/specs/2026-10-10-bastet-console-output-design.md
git commit -m "docs: runs, -vv, the run record; roadmap and spec updated for console plan 2"
```
