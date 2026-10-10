# Console output, event stream and run logs

Design for milestone 3b ("Run logs") in `docs/ROADMAP.md`, widened to start with the console. It is built as
three plans, in order, so the colour and width handling don't wait for the run logs.

## Why

- Output is plain `typer.echo` (about 180 call sites) with no colour, so a run is hard to scan.
- Rich is used only for one progress bar. Nothing adapts to the terminal width.
- Diffs (`Write?` previews, per-item diffs in reports) are uncoloured.
- A run leaves no record of what it did, in order. The Proxmox and ZFS roles need one.

## Decisions

| Decision | Choice |
|---|---|
| Scope | All three outputs (terminal, run note, JSONL), one design, three plans |
| How runs produce output | An event stream; renderers consume it. Not post-hoc rendering from `HostRun` |
| Which commands emit events | `run` (gather, check, apply) and `refresh`. Other commands use the console primitives only |
| Record | JSONL per run, always at full detail, masked. SQLite is deferred and, when wanted, a derived index rebuilt from the JSONL |
| Log level | `--log-level` / `log_level:` shapes the vault run note only. The JSONL always has everything |
| Git | Commit run notes for `apply` and `gather`; one rolling "last check" note per host for `check`; JSONL never committed |

## Plan 1: console primitives (`bastet/ui/`)

One `Console` wrapper around `rich.console.Console`, created once per command, replacing `typer.echo` and
`typer.secho` everywhere.

- **Colour and width:** from Rich's detection. Piped output, `NO_COLOR` or a dumb terminal gives plain text, no colour
  and no boxes, at width 80 when the width can't be detected. Tests use a fixed width, with a forced-colour variant.
- **Plain mode is byte-compatible with today's output** so the existing tests keep passing through the migration:
  no ANSI escapes, no boxes, and no re-wrapping (`soft_wrap`, so long lines are never broken); tables degrade to
  the current aligned-column text. `CliRunner` has no TTY, so tests get this mode by default. Only the
  forced-colour and width-snapshot tests opt into Rich's wrapping and boxes.
- **Streams:** errors and warnings to stderr, results to stdout, as today.
- **Secret masking** is applied inside the console, so no command has to remember it.
- **Primitives:**
  - host header: a rule with the host name and `check` or `applied` at the right;
  - status marks: ✓ green (compliant, changed), ⚠ yellow (needs attention), ✗ red (failed), – dim (skipped);
  - tables that shrink or wrap to the width (`Changes to apply`, `show`);
  - key/value lists (`show`, `doctor`, gather summaries);
  - unified diffs: green `+`, red `-`, cyan `@@` hunk headers (the `Write?` previews and per-item diffs).
- **Run reports:** `render_host` in `engine/report.py` is rebuilt on the primitives, keeping its structure
  (families, collapsed compliant items, summary line).
- **Display verbosity (`-v`)**, separate from the log level:
  - default: the per-host summary as a finished block;
  - `-v`: compliant items too;
  - `-vv`: live events as they arrive (phases, checks);
  - `-vvv`: commands with exit code and timing;
  - `-vvvv`: command output.
- **Parallel runs:** each host prints as a finished block in completion order. From `-vv`, live lines are prefixed
  with the host name.

## Plan 2: events and JSONL (`bastet/events/`)

- **Events** are small frozen dataclasses. Every event carries `run_id`, a timestamp, `host` (none for run-level
  events) and `kind`. Kinds: `run_started`, `run_finished`, `host_started`, `host_finished`, `host_skipped`,
  `phase_started`, `phase_finished`, `item_checked` (before/after values and status), `command_run` (command,
  exit code, duration, output), `trigger_fired`, `hook_ran`, `reboot_step`, `note` (warnings).
- **Emission points:** the six phases in `engine/run.py` (collect, read, compare, apply, on change, verify), and
  the runner's `run()` in `core/remote.py` for commands, exit codes and timings. `emit(event)` is a module-level
  function, so phase functions and resource classes keep their signatures.
- **Parallel runs:** workers put events on a thread-safe queue; one consumer feeds the renderers, so JSONL lines
  never interleave and the terminal gets whole host blocks.
- **Masking:** the consumer masks every string field before any renderer sees it. One place, not three.
- **Normal display** is the events folded into the existing `HostRun` summary, so there is a single source of truth.
- **JSONL:** `~/.local/share/bastet/runs/<run-id>.jsonl`, one file per run, every event at full detail (the
  equivalent of level 4), flushed per event so an interrupted run leaves a usable log. Retention is a setting
  (`keep_runs` and/or `keep_days` in `bastet.yml`), pruned at the start of a run; old files may be gzipped.
  `bastet runs export <run-id>` copies a run's events out.
- **Event levels** (what the run note and `-v` use to filter): 1 changes and failures, with why; 2 every item
  checked, with before/after; 3 every command, with exit code and timing; 4 full command output.

## Plan 3: run notes and Obsidian views

- **Run note:** `_bastet/runs/<date time> <command>.md`, rendered from the run's JSONL at the chosen log level
  (default 1). Flat frontmatter (`command`, `started`, `hosts`, `changed`, `failed`, `status`) so Bases can list
  it. Body: a summary on top (command, who ran it, hosts, changed/failed/skipped/stopped counts, duration), then a
  per-host timeline grouped by phase in execution order. Level-4 output is truncated per step in the note and
  complete in the JSONL.
- **Views:** a Runs Base on `Homelab.md`, newest first, each row linking to its note; a per-host runs Base on each
  host page. Each of those notes shows, directly below the table, a kanban board over the same runs grouped by
  `status` (ok, failed, interrupted), as a second Base view embedded under the table.
- **Git:** run notes for `apply` and `gather` are committed; `check` writes one rolling "last check" note per
  host instead of a new note each time. JSONL is never committed.

## Failure handling

- Rendering never fails a run. Each renderer's `emit` is wrapped; an error is reported once to stderr and that
  renderer is switched off (the terminal last), while the run continues.
- If the JSONL can't be opened, the run proceeds with a warning; the record is a convenience, not a gate.
  Ctrl-C emits `run_finished` with status `interrupted` where it can.
- If the masker fails on an event, the event is replaced by a "masking failed" note. Unmasked content is never
  written.
- A failed run-note write is reported and does not change the exit code. A killed run has no note; its JSONL
  remains.
- A failure to delete a file while pruning warns and continues.

## Testing

- **Console primitives:** snapshots at widths 60, 80 and 120, in plain and forced-colour modes, plus diff colouring.
- **Events:** the emitted sequence for check and apply with a fake runner, covering parallel hosts, a failing item,
  a stopped host, triggers and reboot steps.
- **Reporters:** the terminal renderer against recorded event streams. JSONL: schema, flush on a killed run,
  masking, retention. Run note: golden notes at levels 1–4.
- Tests that assert on printed text move to the plain-text output, which should be nearly identical.
- Container (contract) tests are unchanged and run only on request.

## Left for later

- A SQLite index over the JSONL files, for cross-run queries and the ARA replacement.
- Every command (not only runs) emitting events.
