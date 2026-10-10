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
| Run notes | Every run gets a short note in the vault, so the Runs Base lists every run by name. `bastet log note <run> [-v…]` re-renders any run's note from the JSONL at more detail, and `--remove` deletes it. There is no log-level setting: the JSONL always has everything |
| The command | `bastet log` lists past runs, `bastet log export <run>` prints one, `bastet log note <run>` makes its note (not `runs`, which is too close to `run`) |
| Retention | The JSONL is kept forever by default. `runs.keep_runs` and `runs.keep_days` in `bastet.yml` limit it; `bastet init` asks and Enter keeps everything |
| Git | Each run's note is committed in the command's own commit (apply, gather and check alike), so a check also makes a small commit. The JSONL is never committed |

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
- **Display verbosity (`-v`)**, a terminal setting only (run notes don't follow it):
  - default: the per-host summary as a finished block;
  - `-v`: compliant items too;
  - `-vv`: live events as they arrive (phases, checks);
  - `-vvv`: commands with exit code and timing;
  - `-vvvv`: command output.
- **Parallel runs:** each host prints as a finished block in completion order. From `-vv`, live lines are prefixed
  with the host name.

## Plan 2: events and JSONL (`bastet/events/`)

- **Events** are one small frozen `Event` dataclass: `kind`, `run_id`, a timestamp, seconds elapsed, `host` (none
  for run-level events) and a `data` dict. A table says which keys each kind must carry. Kinds: `run_started`
  (with the schema version), `run_finished`, `host_started`, `host_finished`, `host_skipped`, `phase_started`,
  `phase_finished`, `item_checked` (item, status, phase), `command_run` (command, exit code, duration, output),
  `trigger_fired`, `note` (warnings). `hook_ran` and `reboot_step` are added with hooks and the reboot plan.
- **Emission points:** the phases in `engine/run.py` and its command helpers, which record commands, exit codes and timings.
  Phase start/finish pairs exist for collect, read, compare, apply and verify; `on_change` is a value of the
  `phase` field on command and trigger events, not a pair. `gather` emits only host-level events, and `refresh`
  emits nothing yet. `emit(event)` is a module-level
  function, so phase functions and resource classes keep their signatures.
- **Parallel runs:** workers put events on a thread-safe queue; one consumer feeds the renderers, so JSONL lines
  never interleave and the terminal gets whole host blocks.
- **Masking:** the consumer masks every string field before any renderer sees it. One place, not three.
- **Normal display** still renders from the `HostRun` that `run_host` returns; the same code produces the events,
  and a test checks the two agree. Below `-vv` the output is unchanged. The live view is a renderer over the events.
- **`-v` counts:** `-v` shows compliant items, `-vv` live events, `-vvv` commands with exit code and timing,
  `-vvvv` their output.
- **What is recorded:** a read script's output is never recorded (it carries file contents); fix and trigger output
  is, except for a command with a resource marked `secret`, whose command text and output are hidden. The runs
  folder is mode `0700` and each file `0600`. The record is masked but holds command output: treat it like logs.
- **JSONL:** `~/.local/share/bastet/runs/<run-id>.jsonl`, one file per run, every event at full detail (the
  equivalent of level 4), flushed per event so an interrupted run leaves a usable log. Retention is a setting
  (`runs.keep_runs` and/or `runs.keep_days` in `bastet.yml`), unset by default so every run is kept forever; when
  set, pruned at the start of a run. `bastet init` asks once for the number of days (Enter keeps everything).
  `bastet log` lists the runs and `bastet log export <run> [--out FILE]` prints or writes one run's events.
  Old runs are only ever deleted, never compressed.
- **Event levels** (what the run note and `-v` use to filter): 1 changes and failures, with why; 2 every item
  checked, with before/after; 3 every command, with exit code and timing; 4 full command output.

## Plan 3: run notes and Obsidian views

- **Every run gets a run note:** `_bastet/runs/<date time> <command> <id suffix>.md`. Obsidian note names must be
  unique, so the name ends with the run id's random part; that also lets a re-render find the same file. Flat
  frontmatter (`run`, `command`, `mode` (`check`, `apply` or `gather`), `started`, `hosts`, `changed`, `failed`,
  `status`, `detail`) so Bases can list and filter it. Body: a summary (command, who ran it, hosts, changed/failed/skipped/stopped counts, duration), then, at the
  default detail, only the changes and failures with why.
- **More detail on demand:** `bastet log note <run> [-v…]` renders the run's note from its JSONL at the detail
  you ask for, using the same `-v` scale as the terminal: every item checked (`-v`, `-vv`), commands with exit
  code and timing (`-vvv`), output (`-vvvv`, truncated per step; the complete output stays in the JSONL). It
  replaces the existing note for that run. `bastet log note <run> --remove` deletes the note. Each is a normal
  command: one diff, one commit. A run whose JSONL has been pruned can't be re-rendered ("that run's record is
  gone"); notes already written are unaffected. The JSONL lives on the controller that made the run, so
  re-rendering works only there; notes travel through git as usual.
- **Views:** a Runs Base on `Homelab.md`, newest first, each row linking to its note, and a per-host runs Base on
  each host page. Each Base has several views over the same notes: **Changes** (the default: `apply` and `gather`
  runs, plus any run that failed), **Checks** (`check` runs), **Failures**, and **All runs**. Directly below the
  table each note shows a kanban board over the same runs grouped by `status` (ok, failed, interrupted), as a
  further Base view embedded under the table. The views only decide what is shown; every run still has a note.
- **Git:** each run's note is written and committed in the command's own single commit, whatever the command
  (apply, gather or check). The JSONL is never committed. This replaces the earlier "rolling last-check note per
  host" idea: one small note per run is what lets the Base list every run, and it keeps the history.

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
  masking, retention. Run note: golden notes at each detail, and `log note` re-render, replace and remove.
- Tests that assert on printed text move to the plain-text output, which should be nearly identical.
- Container (contract) tests are unchanged and run only on request.

## Left for later

- A SQLite index over the JSONL files, for cross-run queries and the ARA replacement.
- Every command (not only runs) emitting events.
