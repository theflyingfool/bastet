"""`bastet log`: the record of past runs on this computer."""

import sys
from pathlib import Path

import typer

from bastet.cli.common import handles_errors
from bastet.core.config import data_dir
from bastet.events.jsonl import _files, resolve_run, runs_dir, summarize
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
        out_path.write_text(text, encoding="utf-8")
        return
    sys.stdout.write(text)  # the record was masked when written; print it exactly
