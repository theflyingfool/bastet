# Console output, plan 3: run notes in the vault — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repo, the `bastet-run-plan` skill supplies the Bastet-specific parts.

**Goal:** a run that changes something leaves a short, readable note in the vault, in the command's own commit; an explicit `bastet log note` makes the note of any run; `bastet log show` prints a run's deeper detail in the terminal; and a Runs Base lists the runs.

**Architecture:** a renderer turns a run's events (the dict lines the JSONL holds) into a Markdown note at a detail of 1 to 3. While a run is recorded, a small in-memory sink keeps its events up to the configured detail; `finish()` renders the note from them and adds it to the command's one commit, only when that commit exists anyway. `bastet log note` renders from the JSONL file, and `bastet log show` replays the JSONL through the live terminal view. The Bases and their embeds live in Bastet's own notes (the dashboard and each host's facts note), so none of your notes is edited.

**Tech Stack:** Python ≥3.12, Typer, Pydantic (config), pytest, Obsidian Bases (files only; Bastet cannot render them).

**Spec:** `docs/specs/2026-10-10-bastet-console-output-design.md`, "Plan 3: run notes and Obsidian views". Plans 1 and 2 are merged.

**Roadmap:** `docs/ROADMAP.md`, milestone 3b. This plan runs before roles subplan 2.

## Decisions made while planning

1. **A run gets a note only when its command makes a commit anyway.** A check that writes nothing is not a real run for the vault: no note, no commit. It is still in the JSONL and in `bastet log`, and `bastet log note` can make its note. (Trade-off: a failed check that writes nothing leaves no trace in the vault.)
2. **The vault note is level 1 by default** (what changed and what failed, with why). `runs.note_detail` in `bastet.yml` raises it for every automatic note: 1 changes and failures, 2 every item by phase, 3 also the commands with exit code and timing. It is capped at 3, so command output can never reach git. Deeper detail is read from the JSONL.
3. **Deeper detail is read in the terminal,** with `bastet log show <run> [-v…]`, which replays the record through the same view as `bastet run -vv`. The raw lines come from `bastet log export`.
4. **Nothing is deleted.** There is no `--remove`, and refresh never deletes a run note. (Removal is deferred project-wide.)
5. **The command text is not in the file name.** The name is `<date time> <mode> <id suffix>`, for example `2026-10-10 1218 apply 22d326.md`. No character in a command (`*`, `/`, `@`, `#`) can break a note name, and the id's random part keeps names unique and lets `log note` find its file.
6. **The default note is built from events kept in memory,** because `finish()` commits before the recorder closes. Its counts come from the events so far; its status is the recorder's when one is set (an interrupted run), else it is worked out from the events, counting a host with a planning error as failed. Only gather's outer Ctrl-C handler writes nothing; an interrupted check or apply still commits what it had (that is how `_run` behaves today), so its note says `interrupted`.
7. **The per-host Base filters on `hosts.contains(this.host)`** and is embedded in the host's facts note, whose frontmatter has `host: "[[name]]"`. Per the Bases documentation, `this` is the file that contains the embed.
8. **The board is a built-in `kanban` view, read-only by construction.** It groups by a formula (`formulas: outcome: note.status`, `groupBy: property: formula.outcome`), so dragging a card cannot rewrite a recorded outcome. The documentation lists Kanban as a built-in view type but does not print the exact `type:` string; `kanban` is the expected one and the view type is one constant (`BOARD_VIEW_TYPE`). `groupBy` is written as the documented map (`property:` and `direction:`), which also corrects the existing secrets Base. These Bases need Obsidian 1.14 or later.
9. **Run notes are a new inventory kind, `run`,** marked `generated: true`.
10. **Automatic notes are best-effort.** If rendering or writing the note fails, `finish()` warns and still commits the command's own changes. An explicit `bastet log note` reports its errors normally.
11. **`init` and `doctor --fix` enable Obsidian's Bases core plugin** (Task 5), since every Base Bastet writes needs it.

## Global Constraints

- **Unit tests** never touch the real inventory, `~/.config/bastet`, `~/.local/share/bastet` (including `runs/`), `~/.ssh`, the real `~/.cache` or `$XDG_RUNTIME_DIR`; no network; `tmp_path` only; placeholder data only (see "Example data" in `docs/ROADMAP.md`). `tests/conftest.py` already gives every test a temporary data directory.
- **Test file basenames must be unique across `tests/`** (there are no `__init__.py` files). Use the names given in each task.
- **One commit per command.** An automatic run note is part of the command's one commit and never causes a commit that would not otherwise happen. An explicit `bastet log note` is a command in its own right and makes its own commit.
- **A run never fails because of its note.** Rendering or writing an automatic note is best-effort: a failure is a warning, and the command's own changes are still committed.
- **No deletes.** Nothing in this plan removes a note or a record.
- **Nothing unmasked in a note.** Command text and every other string go through the masker (`ACTIVE`) before they are written. A `secret` resource's command is already `(hidden: secret resource)` in the events, and a note never contains command output.
- **Automatic commands never modify your notes.** Run notes live under `_bastet/runs/`; the Bases are embedded in Bastet's own notes.
- **Import direction:** `bastet.events` may import `bastet.core` and `bastet.ui`; `bastet.core` never imports `bastet.events`; `events` and `engine` never import `typer`.
- **Existing output is unchanged.** No existing test may need editing except where a task says so.
- **Commit trailer:**
  ```
  Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01DBkyXRsdxwovkRErg9n9wt
  ```
  Stage by name, never `git commit -a`. The privacy pre-commit hook runs on every commit.
- **Each task:** failing tests first and seen failing, then implement, then the task's own test files green. The user runs the wider suite at the checkpoints.

## Review Focus

1. **No note and no commit for a run that writes nothing.** A second identical check makes no commit. A run that fails before writing anything leaves no note. An interrupted check or apply that commits still gets a note, and it says `interrupted`.
2. **The note matches the run.** Its status, counts and host links agree with what the command printed: a host with a planning error or a connection exception is a failed host in the note, an earlier failure is never wiped by a later scope with no counts, and every failure has its reason (item errors, a host's exception, a failed trigger, a run-level warning) in the default note.
3. **A secret never reaches a note** at any detail: command text, an item's error, a diff. A note never holds command output, and `note_detail` cannot be set above 3.
4. **Note names are safe.** A command containing `*`, `/`, `#` or `[[` cannot change the file name. Two runs in the same minute do not collide. `log note` on a run that already has a note replaces that same file.
5. **A failing note never costs the commit.** If rendering or writing the note raises, the command still commits its own changes and warns.
6. **The rest of Bastet copes with `bastet: run` notes:** the inventory loads them without problems, `show`, `refresh` and `doctor` ignore them, and refresh does not delete them. One commit per command still holds, including when the refresh was skipped (a busy repo, a plain secret).
7. **Odd inputs to `log note` and `log show`:** a run whose JSONL is unfinished, torn, empty or pruned; a run with no hosts; a host whose name contains spaces or brackets; very large records.

## File structure

| File | Responsibility |
|---|---|
| `src/bastet/events/runnote.py` | `infer_mode`, `note_name`, `summarize`, `render_run_note`, `find_notes` |
| `src/bastet/events/model.py` | `Event.to_dict()`, `Event.from_dict()` |
| `src/bastet/events/recorder.py` | `MemorySink`, `note_change()`, `flush(force=...)` |
| `src/bastet/core/config.py` | `RunsConfig.note_detail` |
| `src/bastet/cli/common.py` | `recorded_run(..., mode=..., note_detail=...)`; `finish()` adds the note |
| `src/bastet/cli/run.py` | passes the mode and the configured detail |
| `src/bastet/cli/log.py` | `bastet log note` and `bastet log show` |
| `src/bastet/core/inventory.py` | `run` joins `KINDS` |
| `src/bastet/core/views.py` | per-view filters and sort, the `groupBy` map, the four Runs Bases |
| `src/bastet/core/render.py` | `## Runs` sections in the dashboard and the host facts summary |
| `src/bastet/core/initialize.py`, `src/bastet/core/doctor.py` | enable the Bases core plugin; a `doctor` problem with a fix |

---

### Task 1: The run-note renderer

**Files:**
- Create: `src/bastet/events/runnote.py`
- Modify: `src/bastet/events/model.py` (`Event.to_dict`, `Event.from_dict`)
- Test: `tests/events/test_runnote.py`

**Interfaces (produces):**
```python
RUNS_DIR = "_bastet/runs"
def infer_mode(command: str) -> str                         # "check" | "apply" | "gather"
def note_name(started: str, mode: str, run_id: str) -> str  # "2026-10-10 1218 apply 22d326"
def summarize(events: list[dict], status: str | None = None) -> RunSummary
def render_run_note(events: list[dict], detail: int, status: str | None = None) -> str  # detail 1..3
def find_notes(root: Path, run_id: str) -> list[Path]       # notes under _bastet/runs whose frontmatter `run` is run_id
@dataclass
class RunSummary: run_id, command, mode, started, user, status, duration, hosts, changed, failed, skipped
```
`Event.to_dict()` returns the dict `to_json` serialises (`kind`, `run_id`, `t`, `elapsed`, `host`, `data`). `Event.from_dict(d)` is its inverse (a classmethod).

**Behaviour:**
- **`infer_mode`:** `-a` in the command words gives `apply`; else `-c` gives `check`; else `-g` alone gives `gather`; a bare `run` is `apply`. `run_started.data.mode`, when present, wins.
- **`summarize(events, status=None)`:** the first `run_started` gives `command`, `started` (its `t`), `user`, `mode`. Hosts are the unique host names of `host_finished` events and of `host_skipped` events whose reason starts with `error:` (a planning error), in order. For each host, `changed`, `failed` and `skipped` take a later `host_finished`'s values **only for keys it carries** (a scope that omits counts, such as the gather scope or an error, keeps the earlier ones), its status is the worst seen (`error`, then `failed`, then `ok`), and a planning-error host counts one failure. `status` is the `status` argument when given, else `run_finished`'s when present, else `failed` if any host is `failed` or `error` or has failures, else `ok`. `duration` comes from `run_finished` or is the largest `elapsed`.
- **Frontmatter** (flat; `hosts` are links so Bases can filter on them): `bastet: run`, `generated: true`, `run`, `command`, `mode`, `started`, `hosts`, `changed`, `failed`, `status`, `detail`. Written with `dump_frontmatter`.
- **Body:** `# <mode> <date> <time>`, then a summary line (`` `command` · by <user> · N hosts · N changed · N failed · took Ns · status ``), then one section per host.
  - **Always (every detail):** run-level `note` events (no host) in a `## Notes` list under the summary; and per host, after its heading, the host's own exception (`- error: <text>` from `host_finished`'s `error`), any failed trigger (`- ✗ trigger <label>: <error>`), and `host_skipped` reasons. A failure must explain itself without opening the JSONL.
  - **Detail 1:** per host `## <host>: <status>`, then one bullet per item whose latest `item_checked` status is not `compliant` (`- ✓ <item>: <changes>`; a failed item adds its error), then `note` messages.
  - **Detail 2:** per host, the events grouped by phase heading (`### read`, `### compare`, `### apply`, `### verify`) in order, with every `item_checked` (compliant ones too) and its changes.
  - **Detail 3:** adds each `command_run` as `` - `$ <command>` → exit N (0.2s) `` (never its output) and each `trigger_fired`.
  - A hidden command shows `(hidden: secret resource)` at every detail.
- Every string is masked with `ACTIVE.mask` on the way out. A detail above 3 is treated as 3.

- [ ] **Step 1: Write the failing tests**

Create `tests/events/test_runnote.py`:

```python
import time

from bastet.core.secrets.redact import ACTIVE
from bastet.events.model import Event, make_event
from bastet.events.runnote import infer_mode, note_name, render_run_note, summarize


def ev(kind, host=None, **data):
    return make_event(kind, "20261010-121800-22d326", time.monotonic(), host, data).to_dict()


def apply_run():
    return [
        ev("run_started", command="run -a pve1", schema=1, mode="apply", user="alice"),
        ev("host_started", "pve1", mode="apply"),
        ev("phase_started", "pve1", phase="compare"),
        ev("item_checked", "pve1", item="/etc/motd", status="would-change", phase="compare", changes=["differs → update"], error=None),
        ev("item_checked", "pve1", item="/etc/ok", status="compliant", phase="compare", changes=[], error=None),
        ev("phase_finished", "pve1", phase="compare", duration=0.1),
        ev("phase_started", "pve1", phase="apply"),
        ev("command_run", "pve1", phase="apply", command="printf x > /etc/motd", exit=0, duration=0.25,
           stdout="wrote it", stderr="", error=None, hidden=False),
        ev("item_checked", "pve1", item="/etc/motd", status="changed", phase="apply", changes=["differs → update"], error=None),
        ev("item_checked", "pve1", item="/etc/bad", status="failed", phase="apply", changes=[], error="boom"),
        ev("phase_finished", "pve1", phase="apply", duration=0.4),
        ev("host_finished", "pve1", status="failed", changed=1, failed=1, skipped=0),
        ev("run_finished", status="failed", duration=1.5, hosts=1, changed=1, failed=1, skipped=0),
    ]


def test_event_dict_round_trip():
    e = make_event("note", "r1", time.monotonic(), "pve1", {"message": "x"})
    assert Event.from_dict(e.to_dict()).to_dict() == e.to_dict()


def test_modes():
    assert infer_mode("run -c box") == "check" and infer_mode("run") == "apply" and infer_mode("run -g") == "gather"
    assert infer_mode("run -g -a x") == "apply" and infer_mode("run -g -c") == "check"


def test_note_name_has_no_command_text():
    assert note_name("2026-10-10T12:18:00.123Z", "apply", "20261010-121800-22d326") == "2026-10-10 1218 apply 22d326"


def test_summarize_a_finished_run():
    s = summarize(apply_run())
    assert (s.command, s.mode, s.user, s.status, s.hosts) == ("run -a pve1", "apply", "alice", "failed", ["pve1"])
    assert (s.changed, s.failed, s.skipped, s.duration) == (1, 1, 0, 1.5)


def test_summarize_an_unfinished_run_uses_the_events_so_far():
    unfinished = apply_run()[:-1]
    s = summarize(unfinished)
    assert s.status == "failed" and s.duration > 0 and s.hosts == ["pve1"]
    ok = [ev("run_started", command="run -c", schema=1), ev("host_finished", "pve1", status="ok", changed=0, failed=0, skipped=0)]
    assert summarize(ok).status == "ok"


def test_a_later_host_finished_replaces_an_earlier_one():
    events = apply_run()[:1] + [
        ev("host_finished", "pve1", status="ok", changed=0, failed=0, skipped=0),
        ev("host_finished", "pve1", status="ok", changed=2, failed=0, skipped=0),
    ]
    s = summarize(events)
    assert s.hosts == ["pve1"] and s.changed == 2


def test_detail_one_lists_only_changes_and_failures_using_the_latest_status():
    text = render_run_note(apply_run(), 1)
    assert text.startswith("---\n") and "bastet: run" in text and "mode: apply" in text and "detail: 1" in text
    assert "[[pve1]]" in text
    assert "## pve1" in text and "✓ /etc/motd" in text and "✗ /etc/bad" in text and "boom" in text
    assert "/etc/ok" not in text and "$ " not in text and "### " not in text


def test_detail_two_groups_by_phase_and_shows_compliant_items():
    text = render_run_note(apply_run(), 2)
    assert text.index("### compare") < text.index("### apply")
    assert "/etc/ok" in text and "$ " not in text


def test_detail_three_adds_commands_but_never_output():
    three = render_run_note(apply_run(), 3)
    assert "$ printf x > /etc/motd" in three and "exit 0" in three and "wrote it" not in three
    assert "wrote it" not in render_run_note(apply_run(), 9)    # above 3 is treated as 3


def test_hidden_commands_are_marked():
    events = apply_run()
    events[7]["data"].update(command="(hidden: secret resource)", hidden=True, stdout="", stderr="")
    assert "(hidden: secret resource)" in render_run_note(events, 3)


def test_secrets_are_masked_everywhere():
    ACTIVE.add("hunter2-value")
    events = apply_run()
    events[3]["data"]["changes"] = ["pw → hunter2-value"]
    events[7]["data"]["command"] = "echo hunter2-value"
    events[0]["data"]["command"] = "run -a hunter2-value"
    for detail in (1, 2, 3):
        assert "hunter2-value" not in render_run_note(events, detail)


def test_a_later_scope_without_counts_keeps_the_earlier_failures():
    events = apply_run()[:-1] + [ev("host_finished", "pve1", status="ok")]
    s = summarize(events)
    assert (s.changed, s.failed) == (1, 1) and s.status == "failed"


def test_a_planning_error_is_a_failed_host_with_a_link_and_a_failed_run():
    events = [ev("run_started", command="run -c", schema=1),
              ev("host_skipped", "media01", reason="error: role files: unknown option"),
              ev("host_finished", "pve1", status="ok", changed=0, failed=0, skipped=0)]
    s = summarize(events)
    assert s.hosts == ["media01", "pve1"] and s.failed == 1 and s.status == "failed"
    text = render_run_note(events, 1)
    assert "[[media01]]" in text and "unknown option" in text


def test_an_explicit_status_wins():
    assert summarize(apply_run()[:-1], status="interrupted").status == "interrupted"
    assert "status: interrupted" in render_run_note(apply_run()[:-1], 1, status="interrupted")


def test_failures_explain_themselves_at_the_default_detail():
    events = [ev("run_started", command="run -a", schema=1),
              ev("note", None, message="refresh skipped: a secret is unlocked"),
              ev("trigger_fired", "pve1", trigger="restart sshd", ok=False, error="unit not found"),
              ev("host_finished", "pve1", status="error", error="connection refused", changed=0, failed=0, skipped=0)]
    text = render_run_note(events, 1)
    assert "refresh skipped: a secret is unlocked" in text and "unit not found" in text and "connection refused" in text


def test_odd_runs_render():
    assert "# " in render_run_note([ev("run_started", command="run -c", schema=1)], 1)    # no hosts, unfinished
    skipped = [ev("run_started", command="run", schema=1), ev("host_skipped", "tv1", reason="not managed")]
    assert "tv1" in render_run_note(skipped, 1) and "not managed" in render_run_note(skipped, 1)
    weird = [ev("run_started", command="run -c 'a*/b#[[x]]'", schema=1),
             ev("host_finished", "my host", status="ok", changed=0, failed=0, skipped=0)]
    assert "my host" in render_run_note(weird, 2)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/events/test_runnote.py -q`
Expected: collection error, `No module named 'bastet.events.runnote'` (and `to_dict` missing).

- [ ] **Step 3: Implement**

In `src/bastet/events/model.py` add to `Event`:

```python
    def to_dict(self) -> dict:
        return {"kind": self.kind, "run_id": self.run_id, "t": self.t, "elapsed": round(self.elapsed, 3),
                "host": self.host, "data": self.data}

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(d["kind"], d["run_id"], d["t"], float(d.get("elapsed", 0.0)), d.get("host"), dict(d.get("data") or {}))
```
and make `to_json` use it: `return json.dumps(self.to_dict(), ensure_ascii=False, default=str)`.

Create `src/bastet/events/runnote.py`:

```python
"""A run's note in the vault, rendered from its events (the dict lines the JSONL holds)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from bastet.core.secrets.redact import ACTIVE
from bastet.core.yamlstyle import dump_frontmatter
from bastet.events.model import level_of

RUNS_DIR = "_bastet/runs"
MAX_DETAIL = 3
MARKS = {"changed": "✓", "compliant": "·", "would-change": "~", "attention": "⚠", "failed": "✗", "skipped": "–"}


def infer_mode(command: str) -> str:
    words = command.split()
    if "-a" in words:
        return "apply"
    if "-c" in words:
        return "check"
    return "gather" if "-g" in words else "apply"


def run_suffix(run_id: str) -> str:
    return run_id.rsplit("-", 1)[-1]


def _when(started: str) -> datetime:
    return datetime.fromisoformat(started.replace("Z", "+00:00"))


def note_name(started: str, mode: str, run_id: str) -> str:
    return f"{_when(started).strftime('%Y-%m-%d %H%M')} {mode} {run_suffix(run_id)}"


@dataclass
class RunSummary:
    run_id: str
    command: str
    mode: str
    started: str
    user: str
    status: str
    duration: float
    hosts: list[str]
    changed: int
    failed: int
    skipped: int


_RANK = {"ok": 0, "failed": 1, "error": 2}


def summarize(events: list[dict], status: str | None = None) -> RunSummary:
    start = next((e for e in events if e["kind"] == "run_started"), None)
    data = start["data"] if start else {}
    finish = next((e for e in reversed(events) if e["kind"] == "run_finished"), None)
    latest: dict[str, dict] = {}

    def host_row(name: str) -> dict:
        return latest.setdefault(name, {"status": "ok", "changed": 0, "failed": 0, "skipped": 0})

    for e in events:
        if e["kind"] == "host_finished" and e["host"]:
            row, d = host_row(e["host"]), e["data"]
            if _RANK.get(d.get("status", "ok"), 0) > _RANK[row["status"]]:
                row["status"] = d["status"]
            for key in ("changed", "failed", "skipped"):
                if key in d:                        # a scope that omits counts keeps the earlier ones
                    row[key] = int(d[key] or 0)
        elif e["kind"] == "host_skipped" and e["host"] and str(e["data"].get("reason", "")).startswith("error:"):
            row = host_row(e["host"])               # a planning error: a failed host
            row["status"] = max(row["status"], "failed", key=_RANK.get)
            row["failed"] = max(row["failed"], 1)
    bad = any(r["status"] != "ok" or r["failed"] for r in latest.values())
    command = data.get("command", "")
    return RunSummary(
        run_id=events[0]["run_id"] if events else "", command=command, mode=data.get("mode") or infer_mode(command),
        started=start["t"] if start else "", user=data.get("user", ""),
        status=status or (finish["data"]["status"] if finish else ("failed" if bad else "ok")),
        duration=finish["data"]["duration"] if finish else max((e["elapsed"] for e in events), default=0.0),
        hosts=list(latest), changed=sum(r["changed"] for r in latest.values()),
        failed=sum(r["failed"] for r in latest.values()), skipped=sum(r["skipped"] for r in latest.values()),
    )


def _item_line(d: dict) -> list[str]:
    mark = MARKS.get(d["status"], "·")
    lines = [f"- {mark} {d['item']}" + (f": {'; '.join(d['changes'])}" if d.get("changes") else f" ({d['status']})")]
    if d.get("error"):
        lines.append(f"  - {d['error']}")
    return lines


def _host_section(host: str, events: list[dict], detail: int) -> list[str]:
    mine = [e for e in events if e["host"] == host]
    done = next((e["data"] for e in reversed(mine) if e["kind"] == "host_finished"), None)
    skip = next((e["data"] for e in mine if e["kind"] == "host_skipped"), None)
    lines = ["", f"## {host}: {done['status'] if done else 'skipped'}"]
    if skip:
        lines.append(f"- skipped: {skip['reason']}")
    if done and done.get("error"):
        lines.append(f"- error: {done['error']}")
    lines += [f"- ✗ trigger {e['data']['trigger']}: {e['data'].get('error') or 'failed'}"
              for e in mine if e["kind"] == "trigger_fired" and not e["data"]["ok"]]
    if detail == 1:
        last: dict[str, dict] = {}
        for e in mine:
            if e["kind"] == "item_checked":
                last[e["data"]["item"]] = e["data"]
        for d in last.values():
            if d["status"] != "compliant":
                lines += _item_line(d)
        lines += [f"- {e['data']['message']}" for e in mine if e["kind"] == "note"]
        return lines
    for e in mine:
        d, kind = e["data"], e["kind"]
        if level_of(kind, d) > detail:
            continue
        if kind == "phase_started":
            lines += ["", f"### {d['phase']}"]
        elif kind == "item_checked":
            lines += _item_line(d)
        elif kind == "command_run":
            result = "error" if d["exit"] is None else f"exit {d['exit']}"
            lines.append(f"- `$ {d['command']}` → {result} ({d['duration']:.1f}s)")
        elif kind == "trigger_fired" and d["ok"]:
            lines.append(f"- trigger {d['trigger']} ✓")
        elif kind == "note":
            lines.append(f"- {d['message']}")
    return lines


def render_run_note(events: list[dict], detail: int, status: str | None = None) -> str:
    detail = max(1, min(detail, MAX_DETAIL))
    s = summarize(events, status)
    when = _when(s.started) if s.started else datetime.now()
    frontmatter = {
        "bastet": "run", "generated": True, "run": s.run_id, "command": s.command, "mode": s.mode, "started": s.started,
        "hosts": [f"[[{h}]]" for h in s.hosts], "changed": s.changed, "failed": s.failed, "status": s.status,
        "detail": detail,
    }
    plural = "host" if len(s.hosts) == 1 else "hosts"
    lines = [
        f"# {s.mode} {when.strftime('%Y-%m-%d %H:%M')}", "",
        f"`{s.command}` · by {s.user or 'unknown'} · {len(s.hosts)} {plural} · {s.changed} changed · "
        f"{s.failed} failed · took {s.duration:.1f}s · {s.status}",
    ]
    run_notes = [e["data"]["message"] for e in events if e["kind"] == "note" and not e["host"]]
    if run_notes:
        lines += ["", "## Notes", *[f"- {m}" for m in run_notes]]
    hosts = list(s.hosts) + [e["host"] for e in events if e["kind"] == "host_skipped" and e["host"] not in s.hosts]
    for host in dict.fromkeys(hosts):
        lines += _host_section(host, events, detail)
    text = "---\n" + dump_frontmatter(frontmatter) + "---\n" + "\n".join(lines) + "\n"
    return ACTIVE.mask(text)


def find_notes(root: Path, run_id: str) -> list[Path]:
    """Notes under _bastet/runs whose `run` is `run_id` (found by the suffix in the name, confirmed by the frontmatter)."""
    folder = root / RUNS_DIR
    found = []
    for path in sorted(folder.glob(f"* {run_suffix(run_id)}.md")) if folder.is_dir() else []:
        try:
            head = path.read_text(encoding="utf-8")[:2000]
        except OSError:
            continue
        if re.search(r"^bastet: run$", head, re.M) and re.search(rf"^run: {re.escape(run_id)}$", head, re.M):
            found.append(path)
    return found
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/events/test_runnote.py tests/events/test_event_model.py -q`
Expected: all pass. If `dump_frontmatter` writes a key differently from an assertion (for example the `hosts` links), adjust the assertion to the writer's actual form, not the writer.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/events/runnote.py src/bastet/events/model.py tests/events/test_runnote.py
git commit -m "events: render a run's note from its events at three levels of detail"
```

---

### Task 2: The run note joins the command's commit

**Files:**
- Modify: `src/bastet/core/config.py` (`RunsConfig.note_detail`), `src/bastet/events/recorder.py` (`MemorySink`, `note_change`, `flush(force=...)`), `src/bastet/events/__init__.py`, `src/bastet/cli/common.py` (`recorded_run`, `finish`), `src/bastet/cli/run.py` (pass the mode and detail), `src/bastet/core/inventory.py` (`KINDS`)
- Test: `tests/core/test_config.py` (addition), `tests/events/test_recorder.py` (additions), `tests/cli/test_run_notes_cli.py`, `tests/core/test_inventory.py` (an addition)

**Interfaces (consumes):** Task 1's `render_run_note`, `note_name`, `summarize`, `RUNS_DIR`. **Produces:**
```python
RunsConfig.note_detail: int = 1                           # 1..3
class MemorySink:  name = "memory"; def __init__(self, max_level: int = 1); events: list[dict]
def note_change(root: Path, detail: int) -> Change | None  # the note for the active run at that detail, or None
Recorder.flush(self, *, force: bool = False)               # force: wait even without a live sink
```

**Behaviour:**
- **`runs.note_detail`** in `bastet.yml`: whole number from 1 to 3, default 1; anything else is a config error naming the key.
- **`recorded_run(command, verbose=0, *, mode=None, note_detail=1)`** adds `MemorySink(max_level=note_detail)` to the sinks and puts `mode` (default `infer_mode(command)`) and `user` (`getpass.getuser()`) in the `run_started` data. `MemorySink` keeps events of its level or below as dicts, **dropping `stdout` and `stderr`** from `command_run` data (a note never shows output, and it keeps memory small).
- **`note_change(root, detail)`:** `None` unless a recording with a `MemorySink` is active and has events. Otherwise it flushes the queue (`force=True`), renders the events kept so far at `detail` with the recorder's status (`rec.status`, e.g. `interrupted`), and returns a `Change` for `root/_bastet/runs/<note_name>.md` (`before` is the file's current text or `None`).
- **`finish()`** (in `cli/common.py`): after computing `paths = ctx.written | {c.path for c in generated}`, if `paths` is empty it returns `False` exactly as today, with **no note**. Otherwise it asks `events.note_change(ctx.root, ctx.config.runs.note_detail)`; if there is a note it writes it (`write_changes`) and adds its path to `paths`, so it joins the one commit. The commit message does not change.
- **Not recording** (every command except `run`): `note_change` is `None`, nothing changes.
- **An interrupted check or apply** still reaches `finish()` and commits, so it gets a note with status `interrupted`. Only gather's outer handler writes nothing.
- **Best-effort:** in `finish()`, any exception while rendering or writing the note is caught, reported as `warning: could not write the run note: <error>` on stderr, and the command's own changes are committed as usual.
- **`run` joins `KINDS`** in `core/inventory.py` so the inventory loads the notes without an "unknown kind" error; refresh does not touch `_bastet/runs/`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/core/test_config.py`:

```python
def test_note_detail_defaults_to_one_and_is_limited_to_one_to_three():
    from bastet.core.config import RunsConfig

    assert RunsConfig().note_detail == 1 and RunsConfig(note_detail=3).note_detail == 3
    for bad in (0, 4, -1):
        with pytest.raises(Exception):
            RunsConfig(note_detail=bad)
```

Add to `tests/events/test_recorder.py`:

```python
def test_memory_sink_keeps_events_up_to_its_level_as_dicts_without_output():
    from bastet.events.recorder import MemorySink

    sink = MemorySink(max_level=3)
    with recording("run", [sink]):
        events.emit("note", None, message="kept")
        events.emit("phase_started", "pve1", phase="read")      # level 2: kept at 3
        events.emit("command_run", "pve1", phase="read", command="cat x", exit=0, duration=0.1,
                    stdout="secret-ish output", stderr="e", error=None, hidden=False)
    kept = {e["kind"] for e in sink.events}
    assert {"note", "phase_started", "command_run"} <= kept and isinstance(sink.events[0], dict)
    command = next(e for e in sink.events if e["kind"] == "command_run")
    assert "stdout" not in command["data"] and "stderr" not in command["data"]
    low = MemorySink(max_level=1)
    with recording("run", [low]):
        events.emit("phase_started", "pve1", phase="read")
    assert "phase_started" not in {e["kind"] for e in low.events}


def test_note_change_is_none_outside_a_recording_or_without_a_memory_sink(tmp_path):
    assert events.note_change(tmp_path, 1) is None
    with recording("run", [ListSink()]):
        assert events.note_change(tmp_path, 1) is None


def test_forced_flush_waits_even_without_a_live_sink():
    sink = ListSink()
    with recording("run", [sink]) as rec:
        events.emit("note", None, message="x")
        rec.flush(force=True)
        assert any(e.kind == "note" for e in sink.events)
```

Create `tests/cli/test_run_notes_cli.py` (copy the `AsRootLocally` class and the `box` fixture from `tests/cli/test_run_recording.py`; read that file first and keep the same way of faking the connection):

```python
def notes(inventory):
    folder = inventory / "_bastet" / "runs"
    return sorted(folder.glob("*.md")) if folder.is_dir() else []


def commit_count(inventory):
    return int(git(inventory, "rev-list", "--count", "HEAD").strip())


def test_a_check_that_writes_something_gets_a_note_in_its_one_commit(runner, box, inventory):
    before = commit_count(inventory)
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    assert commit_count(inventory) == before + 1
    [note] = notes(inventory)
    assert " check " in note.name
    assert note.relative_to(inventory).as_posix() in git(inventory, "show", "--stat", "--name-only", "HEAD")
    text = note.read_text()
    assert "bastet: run" in text and "mode: check" in text and "command: run -c box" in text and "detail: 1" in text


def test_a_second_identical_check_writes_nothing_and_makes_no_commit_and_no_note(runner, box, inventory):
    runner.invoke(app, ["run", "-c", "box"])
    count, existing = commit_count(inventory), notes(inventory)
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    assert commit_count(inventory) == count and notes(inventory) == existing


def test_an_apply_note_is_in_the_apply_commit_with_the_changes(runner, box, inventory):
    result = runner.invoke(app, ["run", "box", "-y"])
    assert result.exit_code == 0, result.output
    apply_notes = [n for n in notes(inventory) if " apply " in n.name]
    assert apply_notes and "changed" in apply_notes[-1].read_text()


def test_an_interrupted_run_that_commits_gets_a_note_saying_so(runner, box, inventory, monkeypatch):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(run_mod, "run_parallel", interrupt)
    runner.invoke(app, ["run", "-c", "box"])
    notes_made = notes(inventory)
    assert notes_made and "status: interrupted" in notes_made[-1].read_text()


def test_a_failing_note_never_costs_the_commit(runner, box, inventory, monkeypatch):
    import bastet.events.runnote as runnote

    def boom(*args, **kwargs):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(runnote, "render_run_note", boom)
    before = commit_count(inventory)
    result = runner.invoke(app, ["run", "-c", "box"])
    assert result.exit_code == 0, result.output
    assert "could not write the run note: render exploded" in result.output
    assert commit_count(inventory) == before + 1 and notes(inventory) == []


def test_the_configured_detail_is_used(runner, box, inventory, tmp_path):
    cfg = tmp_path / "bastet.yml"
    cfg.write_text(cfg.read_text() + "runs:\n  note_detail: 3\n") if cfg.exists() else None
    # use the BASTET_CONFIG file the `inventory` fixture created; then:
    result = runner.invoke(app, ["run", "-c", "box"])
    [note] = notes(inventory)
    assert "detail: 3" in note.read_text() and "$ " in note.read_text()


def test_the_note_never_holds_a_secret(runner, box, inventory, secret_keys):
    # use the same secret setup as tests/cli/test_run_recording.py::test_secrets_never_reach_the_record
    ...
```
(Write the last two tests out fully: for the configured-detail test append the `runs:` block to the file named by `os.environ["BASTET_CONFIG"]`; for the secret test follow that existing test, and assert the secret value appears in no file under `_bastet/runs/`.)

Add to `tests/core/test_inventory.py`:

```python
def test_a_run_note_loads_without_problems(tmp_path):
    root = tmp_path / "lab"
    (root / "_bastet" / "runs").mkdir(parents=True)
    (root / "Homelab.md").write_text("---\nbastet: lab\n---\n# Lab\n")
    (root / "_bastet" / "runs" / "2026-10-10 1218 apply 22d326.md").write_text(
        '---\nbastet: run\ngenerated: true\nrun: 20261010-121800-22d326\nmode: apply\nhosts:\n  - "[[pve1]]"\n---\n# apply\n')
    inv = load_inventory(root, load_host_types())
    assert not inv.problems and len(inv.of_kind("run")) == 1
```
(adapt the imports and helper style to that file.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/core/test_config.py tests/events/test_recorder.py tests/cli/test_run_notes_cli.py tests/core/test_inventory.py -q`
Expected: failures: no `note_detail`, no `MemorySink`, no `note_change`, unknown kind `run`, no note written.

- [ ] **Step 3: Implement**

`core/config.py`: in `RunsConfig` add `note_detail: int = 1` and a validator: `if not 1 <= value <= 3: raise ValueError("must be 1, 2 or 3")` (a separate `field_validator("note_detail")`).

`recorder.py`:

```python
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
```
Change `Recorder.flush` to `def flush(self, *, force: bool = False)` and return early only `if not force and (...)`; keep the thread-alive check. Add:

```python
def note_change(root: Path, detail: int) -> "Change | None":
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
```
Export `MemorySink` and `note_change` from `bastet/events/__init__.py`. `recording()` already passes `**extra` into `run_started`, so `recorded_run` passes `mode=` and `user=`.

`cli/common.py`: `recorded_run(command, verbose=0, *, mode=None, note_detail=1)` appends `MemorySink(max_level=note_detail)` to the sinks and calls `recording(command, sinks, run_id=run_id, mode=mode or infer_mode(command), user=getpass.getuser())`. In `run()` the config is already readable in `recorded_run` (it loads `runs_cfg`), so read `note_detail` from `runs_cfg.note_detail` there and drop the parameter if that is simpler. In `finish()`, after `paths = ...` and the `if not paths: return False` line:

```python
    try:
        note = events.note_change(ctx.root, ctx.config.runs.note_detail)
        if note is not None:
            write_changes([note])
            paths = paths | {note.path}
    except Exception as exc:  # the note is best-effort: the command's own changes still get committed
        out.secho(f"warning: could not write the run note: {exc}", fg="yellow", err=True)
```
(import `from bastet import events` and `getpass` if not present; keep `generated` and the message exactly as they are.)

`cli/run.py`: compute `mode = "apply" if apply_ else "check" if check else "gather" if gather else "apply"` and pass `mode=mode` to `recorded_run`.

`core/inventory.py`: `KINDS = ("lab", "host", "hardware", "group", "location", "role", "secret", "facts", "run")`.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/events tests/cli/test_run_notes_cli.py tests/cli/test_run_recording.py tests/cli/test_check_apply.py tests/cli/test_finish.py tests/core/test_inventory.py tests/core/test_config.py -q`
Expected: all pass. If an existing test asserts the exact files in a check or apply commit, update only that assertion to allow the new note path, and say which test in the commit message.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/core/config.py src/bastet/events/recorder.py src/bastet/events/__init__.py src/bastet/cli/common.py src/bastet/cli/run.py src/bastet/core/inventory.py tests/core/test_config.py tests/events/test_recorder.py tests/cli/test_run_notes_cli.py tests/core/test_inventory.py
git commit -m "run notes: a run that commits gets a note in the same commit; a run that writes nothing gets none"
```

---

### Task 3: `bastet log note` and `bastet log show`

**Files:**
- Modify: `src/bastet/cli/log.py`
- Test: `tests/cli/test_log_note_cli.py`

**Interfaces (consumes):** Task 1's `render_run_note`, `find_notes`, `note_name`, `summarize`, `RUNS_DIR`, `Event.from_dict`; `resolve_run`, `runs_dir` from `events.jsonl`; `TerminalSink` from `events.terminal`; `load_context`, `write_with_confirmation`, `finish` from `cli/common.py`.

**Behaviour:**
- **`bastet log note <run> [-y]`:** resolve the run's JSONL, read its events (skipping lines that aren't valid JSON), render the note at `ctx.config.runs.note_detail`, and write `_bastet/runs/<note_name>.md`, replacing the run's existing note if there is one (`find_notes`). It shows the diff and asks (unless `-y`), then `finish(ctx, "log note <run id>")`: one commit. If the note would not change: `Already up to date.` A record with no `run_started` (empty or torn) is an error: `that record has no start event`. A record that has been pruned: `that run's record is gone` / `no run matching …` (the existing `resolve_run` wording). There is no way to delete a note.
- **`bastet log show <run> [-v…]`:** replays the run's events through `TerminalSink` as `bastet run -vv` shows them live. The level is 1 with no flag or `-v` (changes and failures with why), 2 for `-vv`, 3 for `-vvv`, 4 for `-vvvv` (which adds command output). It prints a header line `<run id>  <command>  <status>` first. Torn or unparsable lines are skipped. It writes nothing.
- **Neither command is recorded,** and neither writes a note for itself.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_log_note_cli.py`. Use the `runner` and `inventory` fixtures and a helper that writes a record into the temporary data directory the way `tests/cli/test_log_cli.py` does (read it first), but with the richer event list from `tests/events/test_runnote.py::apply_run` (copy the `ev` helper and the events; do not import from another test file). Tests:

```python
def test_note_makes_a_note_at_the_configured_detail_in_one_commit(runner, inventory): ...   # exit 0, one new commit, file under _bastet/runs/, "detail: 1"
def test_note_replaces_the_same_file_when_the_configured_detail_changes(runner, inventory): ...  # set runs.note_detail: 3 in BASTET_CONFIG, call again: same path, now has "$ printf x"; two commits
def test_note_is_up_to_date_when_nothing_changes(runner, inventory): ...                      # second identical call: "Already up to date.", no commit
def test_note_for_a_missing_or_pruned_record_is_a_clear_error(runner, inventory): ...          # exit 1, no traceback
def test_note_for_an_empty_or_torn_record_is_a_clear_error(runner, inventory): ...
def test_note_for_a_run_with_odd_command_text_makes_a_safe_file_name(runner, inventory): ...   # command "run -c 'a*/b#[[x]]'": the file name has only date, mode, suffix
def test_note_never_holds_a_secret(runner, inventory): ...                                     # ACTIVE.add a value used in the record's command: not in the note
def test_there_is_no_remove_option(runner, inventory): ...                                     # `log note RUN --remove` exits non-zero ("No such option")
def test_show_default_prints_changes_and_failures_only(runner, inventory): ...
def test_show_vv_adds_phases_and_items_vvv_commands_vvvv_output(runner, inventory): ...         # compare outputs: "wrote it" only at -vvvv
def test_show_skips_torn_lines_and_reports_a_missing_run(runner, inventory): ...
def test_show_writes_nothing(runner, inventory): ...                                           # no new commit, no files
```
Write each out fully against the helpers.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/cli/test_log_note_cli.py -q`
Expected: failures: no `note` or `show` subcommand.

- [ ] **Step 3: Implement** in `src/bastet/cli/log.py`:

```python
def _read_events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and "kind" in d and "data" in d:
            events.append(d)
    return events


@log_app.command("note")
@handles_errors
def note(
    run: str = typer.Argument(..., help="A run id, the start of one, or 'latest'."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask; write and commit."),
) -> None:
    """Make (or re-render) a run's note in the vault from its record, at the detail set by runs.note_detail."""
    ctx = load_context()
    events = _read_events(resolve_run(runs_dir(data_dir()), run))
    if not any(e["kind"] == "run_started" for e in events):
        raise BastetError("that record has no start event")
    s = summarize(events)
    target = ctx.root / RUNS_DIR / f"{note_name(s.started, s.mode, s.run_id)}.md"
    text = render_run_note(events, ctx.config.runs.note_detail)
    before = target.read_text(encoding="utf-8") if target.exists() else None
    if before == text:
        out.echo("Already up to date.")
        return
    if write_with_confirmation(ctx, [Change(target, before, text)], yes):
        finish(ctx, f"log note {s.run_id}")


@log_app.command("show")
@handles_errors
def show(
    run: str = typer.Argument(..., help="A run id, the start of one, or 'latest'."),
    verbose: int = typer.Option(0, "--verbose", "-v", count=True,
                                help="More detail: -vv phases and items, -vvv commands, -vvvv their output."),
) -> None:
    """Print a run's record as the live view shows it (changes and failures by default)."""
    events = _read_events(resolve_run(runs_dir(data_dir()), run))
    s = summarize(events)
    out.echo(f"{s.run_id}  {s.command}  {s.status}")
    sink = TerminalSink(1 if verbose < 2 else min(verbose, 4))
    for d in events:
        sink.handle(Event.from_dict(d))
```
(import `json`, `Change`, `BastetError`, `load_context`, `write_with_confirmation`, `finish`, `summarize`, `render_run_note`, `note_name`, `RUNS_DIR`, `Event`, `TerminalSink`.)

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/cli/test_log_note_cli.py tests/cli/test_log_cli.py tests/test_no_raw_echo.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/cli/log.py tests/cli/test_log_note_cli.py
git commit -m "log: bastet log note makes a run's note from its record; bastet log show prints its detail"
```

---

### Task 4: The Runs Bases and where they are embedded

**Files:**
- Modify: `src/bastet/core/views.py` (`_base` gains per-view filters, sort and the `groupBy` map; the four Bases), `src/bastet/core/render.py` (`## Runs` sections)
- Test: `tests/core/test_runs_views.py`; existing view and render tests, with the `groupBy` change noted below

**Interfaces (produces):**
```python
RUNS_BASE_PATH = "_bastet/runs.base"                    # all runs
RUNS_HERE_BASE_PATH = "_bastet/runs-here.base"          # this host's runs
RUNS_BOARD_PATH = "_bastet/runs-board.base"             # board, all runs
RUNS_BOARD_HERE_PATH = "_bastet/runs-board-here.base"   # board, this host's runs
BOARD_VIEW_TYPE = "kanban"                              # the one constant to change if Obsidian names it differently
RUNS_SECTION = "\n## Runs\n\n![[runs.base]]\n\n![[runs-board.base]]\n"
RUNS_HERE_SECTION = "\n## Runs\n\n![[runs-here.base]]\n\n![[runs-board-here.base]]\n"
```

**Behaviour:**
- **`_base`** accepts an optional `formulas` mapping (rendered as a top-level `formulas:` block before `views:`) and, per view, an optional list of filter expressions (rendered as a view-level `filters:` block, `and:` for a list, `or:` for a tuple) and an optional sort. **`groupBy` is written as the documented map** (`groupBy:\n      property: <name>\n      direction: ASC`), including for the existing secrets Base, which used a plain word before. That is the only change to existing Bases; their other text stays byte-identical.
- **The runs table Bases** (`runs.base` and `runs-here.base`): global filter `bastet == "run"` (the here-variant adds `hosts.contains(this.host)`), views in this order, each sorted by `started` descending with columns `file.name`, `mode`, `status`, `started`, `changed`, `failed`, `hosts`:
  - **Changes** (the default): `mode == "apply"` or `mode == "gather"` or `status == "failed"`;
  - **Checks:** `mode == "check"`;
  - **Failures:** `status == "failed"`;
  - **All runs:** no extra filter.
- **The board Bases:** the same global filters and a top-level `formulas:` block (`outcome: note.status`), one view of type `BOARD_VIEW_TYPE` named `Board`, grouped by `formula.outcome`, sorted by `started` descending. Grouping by a formula keeps the board read-only: a dragged card cannot rewrite the recorded status.
- **`ensure_views`** writes all four (they are in `VIEWS`), refreshing outdated ones as it does the others.
- **The dashboard** gets `RUNS_SECTION` after "Recent changes"; **each host's facts summary** (`host_summary`) gets `RUNS_HERE_SECTION` at its end. Both are Bastet's own notes, so none of yours is edited. Hardware facts notes get nothing.
- Refresh stays idempotent: a second refresh changes nothing.

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_runs_views.py`:

```python
from bastet.core.views import (
    BOARD_VIEW_TYPE, HARDWARE_BASE_PATH, RUNS_BASE_PATH, RUNS_BOARD_HERE_PATH, RUNS_BOARD_PATH, RUNS_HERE_BASE_PATH,
    SECRETS_BASE_PATH, VIEWS,
)


def test_existing_bases_without_grouping_render_exactly_as_before():
    text = VIEWS[HARDWARE_BASE_PATH]
    assert text.startswith('filters:\n  and:\n    - bastet == "facts"\n    - installed_in == this\nviews:\n')
    assert "filters:" not in text.split("views:")[1] and "groupBy" not in text


def test_group_by_is_the_documented_map_in_the_secrets_base():
    text = VIEWS[SECRETS_BASE_PATH]
    assert "groupBy:\n      property: role\n      direction: ASC\n" in text and "groupBy: role" not in text


def test_all_four_runs_bases_are_known():
    for path in (RUNS_BASE_PATH, RUNS_HERE_BASE_PATH, RUNS_BOARD_PATH, RUNS_BOARD_HERE_PATH):
        assert path in VIEWS


def test_runs_base_has_the_four_views_in_order_with_filters_and_newest_first():
    text = VIEWS[RUNS_BASE_PATH]
    assert text.startswith('filters:\n  and:\n    - bastet == "run"\n')
    names = [line.split(": ", 1)[1] for line in text.splitlines() if line.strip().startswith("name: ")]
    assert names == ["Changes", "Checks", "Failures", "All runs"]
    changes = text.split("name: Changes")[1].split("name: Checks")[0]
    assert 'mode == "apply"' in changes and 'mode == "gather"' in changes and 'status == "failed"' in changes and "or:" in changes
    assert 'mode == "check"' in text.split("name: Checks")[1].split("name: Failures")[0]
    assert text.count("direction: DESC") == 4 and "property: started" in text
    assert "hosts.contains(this.host)" not in text


def test_the_per_host_base_filters_on_the_host():
    assert "hosts.contains(this.host)" in VIEWS[RUNS_HERE_BASE_PATH]
    assert "hosts.contains(this.host)" in VIEWS[RUNS_BOARD_HERE_PATH]


def test_the_board_groups_by_status_using_one_constant():
    text = VIEWS[RUNS_BOARD_PATH]
    assert f"type: {BOARD_VIEW_TYPE}" in text and "name: Board" in text
    assert "formulas:\n  outcome: note.status\n" in text
    assert "groupBy:\n      property: formula.outcome\n      direction: ASC\n" in text and "property: status" not in text
```

Add (in `tests/core/test_render.py`, using its `repo`/`inv` fixtures) tests that the dashboard contains `![[runs.base]]` and `![[runs-board.base]]`, a host's facts note body contains `![[runs-here.base]]` and `![[runs-board-here.base]]`, a hardware facts note contains neither, and a second `generated_changes` after `write_changes` is empty.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/core/test_runs_views.py tests/core/test_render.py -q`
Expected: import errors for the new names; the render tests fail.

- [ ] **Step 3: Implement**

Extend `core/views.py`:

```python
def _view_text(view_type, name, columns, *, group_by=None, filters=None, sort=None) -> str:
    text = f"  - type: {view_type}\n    name: {name}\n"
    if filters:
        key, exprs = ("or", filters) if isinstance(filters, tuple) else ("and", filters)
        text += f"    filters:\n      {key}:\n" + "".join(f"        - {e}\n" for e in exprs)
    if group_by:
        text += f"    groupBy:\n      property: {group_by}\n      direction: ASC\n"
    text += "    order:\n" + _yaml_list(columns)
    if sort:
        text += f"    sort:\n      - property: {sort[0]}\n        direction: {sort[1]}\n"
    return text
```
Have `_base` build its views with it (a view tuple stays `(type, name, columns)`, or becomes a `dict` with `filters` and `sort` for the new ones), define the four Bases with the constants above, add them to `VIEWS`, and add `RUNS_SECTION` after the "Recent changes" block in `dashboard()` and `RUNS_HERE_SECTION` at the end of `host_summary()`. The existing secrets Base keeps `group_by="role"`, which now renders as the map.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/core/test_runs_views.py tests/core/test_render.py tests/core/test_views.py tests/core/test_docs.py -q`
Expected: all pass. If an existing test compares a whole dashboard or host summary body, or the old `groupBy: role` text, update only that comparison, and say which test in the commit message.

- [ ] **Step 5: Commit**

```bash
git add src/bastet/core/views.py src/bastet/core/render.py tests/core/test_runs_views.py tests/core/test_render.py
git commit -m "views: a Runs Base (Changes, Checks, Failures, All runs) and a status board, embedded in the dashboard and each host's facts note; groupBy as the documented map"
```

---

### Task 5: `init` and `doctor --fix` enable the Bases core plugin

**Files:**
- Modify: `src/bastet/core/initialize.py` (the `core-plugins.json` step), `src/bastet/core/doctor.py` (a problem with a fix)
- Test: `tests/core/test_initialize.py`, `tests/core/test_doctor.py`

**Behaviour:**
- **`init`** enables Obsidian's Bases core plugin the way it already enables Templates, in whichever format the vault's `.obsidian/core-plugins.json` uses (a map of id to true, or a list of ids). The core plugin id is `bases`; confirm it against Obsidian's documentation or a vault's own `core-plugins.json`, and use the documented id if it differs. Only when the inventory has a `.obsidian` folder (or `init` creates one), exactly as for Templates. A vault that already has it enabled is left alone, and the action line says "kept".
- **`doctor`** reports, for a vault that has a `.obsidian` folder where Bases is not enabled, a problem "Obsidian's Bases core plugin isn't enabled; Bastet's tables and boards need it" with a fix `Change` for `core-plugins.json`. `doctor --fix` applies it in its one diff and one commit, as for every other fix.
- No `.obsidian` folder: no problem.

- [ ] **Step 1: Write the failing tests.** In `tests/core/test_initialize.py`: `init` writes `bases` into a new `core-plugins.json` (map form); adds it to an existing map that has other plugins and keeps them; adds it to a list-form file; leaves an already-enabled one alone. In `tests/core/test_doctor.py`: a vault with `core-plugins.json` lacking `bases` yields the problem with a fix; applying the fix enables it and keeps other keys; a vault with it enabled, or with no `.obsidian`, yields none.
- [ ] **Step 2: Run to verify they fail:** `uv run pytest tests/core/test_initialize.py tests/core/test_doctor.py -q`.
- [ ] **Step 3: Implement** by extending the existing `core-plugins.json` handling in `initialize.py` (it already has the dict and list branches for `templates`) and adding one `Problem` to `diagnose` in `core/doctor.py` whose `fix` is the changed file text.
- [ ] **Step 4: Run to verify they pass:** `uv run pytest tests/core/test_initialize.py tests/core/test_doctor.py tests/cli/test_init.py tests/cli/test_doctor_cli.py -q`.
- [ ] **Step 5: Commit**

```bash
git add src/bastet/core/initialize.py src/bastet/core/doctor.py tests/core/test_initialize.py tests/core/test_doctor.py
git commit -m "init and doctor --fix enable Obsidian's Bases core plugin"
```

---

### Task 6: Docs, roadmap, spec check, and your Obsidian check

**Files:** `src/bastet/data/docs/commands.md`, `src/bastet/data/docs/hosts_and_facts.md`, `src/bastet/data/docs/troubleshooting.md`, `docs/ROADMAP.md`, `docs/specs/2026-10-10-bastet-console-output-design.md`. Test: `tests/core/test_docs.py` (must stay green).

- [ ] **Step 1: Docs** (plain, short, example data only)
  - `commands.md`: `bastet log note RUN [-y]` (makes or re-renders the run's note in the vault; the detail is `runs.note_detail`, 1 to 3, default 1) and `bastet log show RUN [-v…]` (prints a run's record: changes and failures by default, `-vv` phases and items, `-vvv` commands, `-vvvv` their output). Mention `runs.note_detail` next to the retention settings.
  - `hosts_and_facts.md`: a short "Runs" paragraph: a run that changes something leaves a short note under `_bastet/runs/` in the same commit; a check that finds nothing to write leaves none; the Runs tables are on the dashboard and at the bottom of each host's facts note, with views for changes, checks and failures and a board by status.
  - `bastet_guide.md` or `commands.md` (wherever Obsidian setup is described): the Runs tables and board need Obsidian 1.14 or later with the Bases core plugin, which `bastet init` turns on.
  - `troubleshooting.md`: if a run isn't in the Runs table it left no note (nothing was written); `bastet log` lists every run, `bastet log note <run>` makes its note, and `bastet log show <run> -vvv` shows its detail.
- [ ] **Step 2: Spec.** Check "Plan 3" against what was built and fix anything that differs.
- [ ] **Step 3: Roadmap.** Mark plan 3 done, the run-logs milestone (3b) done (☑), update "Now" so roles subplan 2 is next, and keep the "Left from the plan 2 review" and "Later" items. Add a "Later" item: "A board of runs by detail, dragged to change a note's detail (the note would hold all levels as folds); decided against for now."
- [ ] **Step 4: Run** `uv run pytest tests/core/test_docs.py -q` and `scripts/privacy-check` (it must print nothing).
- [ ] **Step 5: Your check in Obsidian** (Obsidian 1.14 or later). In a sandbox inventory opened as a vault (the `run-bastet` skill sets one up), after a `bastet run -c` that finds something to report: the dashboard's Runs section shows the Changes view with that run; the Checks, Failures and All runs views switch; a host's facts note shows only that host's runs; the board shows columns by status, and dragging a card is refused or changes nothing (the status in the note must not change) (if it shows nothing or an error, the `kanban` type string is wrong: tell me what the view type is called in a Base you make by hand and I'll change `BOARD_VIEW_TYPE`); `bastet log show latest -vvv` prints the detail; and the secrets Base (if you have secrets) still groups by role.
- [ ] **Step 6: Commit**

```bash
git add src/bastet/data/docs/commands.md src/bastet/data/docs/hosts_and_facts.md src/bastet/data/docs/troubleshooting.md docs/ROADMAP.md docs/specs/2026-10-10-bastet-console-output-design.md
git commit -m "docs: run notes, bastet log note and show, and the Runs tables; roadmap and spec updated for console plan 3"
```
