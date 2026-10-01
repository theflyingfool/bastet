import typer

from bastet import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"bastet {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_print_version,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Bastet: a human-readable homelab inventory."""


from bastet.cli.add import add_app  # noqa: E402
from bastet.cli.show import show  # noqa: E402

app.command()(show)
app.add_typer(add_app, name="add")
from bastet.cli.init import init  # noqa: E402

app.command()(init)
