import typer

from bastet.cli.common import handles_errors, load_context, refresh_generated
from bastet.core.render import MAPS_DIR


@handles_errors
def map_() -> None:
    """Regenerate the cabling and network maps in _bastet/maps/ (refresh does this too, along with everything else)."""
    ctx = load_context()
    refresh_generated(ctx)
    maps = sorted((ctx.root / MAPS_DIR).glob("*.md")) if (ctx.root / MAPS_DIR).is_dir() else []
    if not maps:
        typer.echo("No maps yet: add links: to hosts (cabling) or networks: to the lab file (networks).")
    for path in maps:
        typer.echo(f"  {path.relative_to(ctx.root)}")
