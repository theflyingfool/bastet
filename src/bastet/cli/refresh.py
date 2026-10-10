from bastet.cli.common import handles_errors, load_context, pull_or_warn, refresh_only
from bastet.ui import out


@handles_errors
def refresh() -> None:
    """Regenerate page summaries and the dashboard from your files (no hosts contacted)."""
    ctx = load_context()
    pull_or_warn(ctx)
    if not refresh_only(ctx):
        out.echo("Generated notes are up to date.")
