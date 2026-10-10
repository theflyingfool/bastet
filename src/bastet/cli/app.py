import typer

from bastet import __version__
from bastet.ui import out

app = typer.Typer(invoke_without_command=True, add_completion=True, pretty_exceptions_show_locals=False)  # never print a decrypted secret


def _print_version(value: bool) -> None:
    if value:
        out.echo(f"bastet {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_print_version,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Bastet: a human-readable homelab inventory."""
    if ctx.invoked_subcommand is None:  # bare `bastet` is a request for help, not a mistake
        out.echo(ctx.get_help())
        raise typer.Exit()


@app.command(name="help")
def help_(ctx: typer.Context, command: list[str] = typer.Argument(None, help="The command to explain, e.g. `secret set`.")) -> None:
    """Show help for Bastet or one of its commands (the same as --help)."""
    parent = ctx.parent
    target = parent.command
    for word in command or []:
        sub = target.get_command(parent, word) if hasattr(target, "get_command") else None
        if sub is None:
            raise typer.BadParameter(f"no command named {' '.join(command)!r}", param_hint="COMMAND")
        parent = typer.Context(sub, info_name=word, parent=parent)
        target = sub
    out.echo(parent.get_help())


from bastet.cli.add import add_app  # noqa: E402
from bastet.cli.show import show  # noqa: E402

app.command()(show)
app.add_typer(add_app, name="add")
from bastet.cli.init import init  # noqa: E402

app.command()(init)
from bastet.cli.refresh import refresh  # noqa: E402

app.command(hidden=True)(refresh)
from bastet.cli.run import run  # noqa: E402

app.command()(run)
from bastet.cli.secret import secret_app  # noqa: E402

app.add_typer(secret_app, name="secret")
from bastet.cli.doctor import doctor  # noqa: E402

app.command()(doctor)
from bastet.cli.log import log_app  # noqa: E402

app.add_typer(log_app, name="log")
