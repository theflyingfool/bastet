"""`bastet log`: the record of past runs on this computer."""

import json
import os
import sys
from pathlib import Path

import typer

from bastet.cli.common import finish, handles_errors, load_context, write_with_confirmation
from bastet.core.changes import Change
from bastet.core.config import data_dir
from bastet.core.errors import BastetError
from bastet.events.jsonl import _files, resolve_run, runs_dir, summarize
from bastet.events.model import Event
from bastet.events.runnote import RUNS_DIR, find_notes, note_name, render_run_note
from bastet.events.runnote import summarize as summarize_events
from bastet.events.terminal import TerminalSink
from bastet.ui import out

log_app = typer.Typer(invoke_without_command=True, help="The record of past runs on this computer.")


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
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # output may hold command output
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        return
    sys.stdout.write(text)  # the record was masked when written; print it exactly


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
    s = summarize_events(events)
    existing = find_notes(ctx.root, s.run_id)
    target = existing[0] if existing else ctx.root / RUNS_DIR / f"{note_name(s.started, s.mode, s.run_id)}.md"
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
    s = summarize_events(events)
    out.echo(f"{s.run_id}  {s.command}  {s.status}")
    sink = TerminalSink(1 if verbose < 2 else min(verbose, 4))
    for d in events:
        sink.handle(Event.from_dict(d))
