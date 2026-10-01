import typer

from bastet.cli.common import handles_errors, load_context, refresh_generated
from bastet.core.errors import BastetError


@handles_errors
def refresh() -> None:
    """Regenerate page summaries and the dashboard from your files (no hosts contacted)."""
    ctx = load_context()
    try:
        ctx.repo.pull()
    except BastetError as exc:
        typer.secho(f"warning: {exc}; continuing on the last pulled state", fg="yellow", err=True)
    if not refresh_generated(ctx):
        typer.echo("Generated notes are up to date.")
