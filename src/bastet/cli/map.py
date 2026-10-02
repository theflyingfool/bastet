import typer

from bastet.cli.common import handles_errors, load_context
from bastet.core.errors import BastetError
from bastet.core.maps import cabling_map, networks_map

VIEWS = ("cabling", "networks")


@handles_errors
def map_(
    view: str = typer.Argument("cabling", help="cabling or networks"),
    around: str = typer.Option(None, "--around", help="Only this host and what's cabled to it (cabling)."),
) -> None:
    """Print a map as Mermaid (nothing is written; `refresh` keeps _bastet/maps/ current)."""
    if view not in VIEWS:
        raise BastetError(f"unknown map '{view}' (known: {', '.join(VIEWS)})")
    inv = load_context().inventory
    text = cabling_map(inv, around) if view == "cabling" else networks_map(inv)
    typer.echo(text or f"Nothing to draw for {view} yet.")
