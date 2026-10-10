"""`bastet doctor`: problems the inventory doesn't block on, listed and (with `--fix`) fixed."""

from pathlib import Path

import typer

from bastet.cli.common import finish, handles_errors, load_context, write_with_confirmation
from bastet.core.doctor import Problem, diagnose, merged_changes
from bastet.core.errors import BastetError
from bastet.ui import out


def _print_problem(p: Problem) -> None:
    fg = "red" if p.severity == "error" else "yellow"
    where = f"{p.where}: " if p.where else ""
    out.secho(f"{where}{p.message}", fg=fg)


def _check_role_dir(path: Path) -> None:
    from bastet.roles.contract import load_roles

    if not (path / "role.yml").is_file():
        raise BastetError(f"no role.yml in {path}")
    roles = load_roles(path.parent)
    if path.resolve().name not in roles:
        raise BastetError(f"no role.yml in {path}")
    out.echo(f"{path}: parses as a role definition.")


@handles_errors
def doctor(
    role_dir: str | None = typer.Argument(None, help="Lint a role folder instead of the inventory."),
    fix: bool = typer.Option(False, "--fix", help="Apply every problem that has a fix, as one diff and one commit."),
    yes: bool = typer.Option(False, "--yes", "-y", help="With --fix, don't ask; go ahead."),
) -> None:
    """Problems the inventory doesn't block on, found and (with `--fix`) fixed.

    Stale gathered keys, pages embedding a retired note, why generated notes last fell behind,
    and a pending push. Given a folder instead, lints it as a role definition."""
    if role_dir is not None:
        if fix:
            raise BastetError("--fix doesn't apply to a role folder")
        _check_role_dir(Path(role_dir))
        return
    ctx = load_context()
    problems = diagnose(ctx)
    if not fix:
        if not problems:
            out.echo("No problems found.")
        for p in problems:
            _print_problem(p)
        return
    changes = merged_changes(problems)
    if not changes:
        out.echo("Nothing to fix.")
        for p in problems:
            _print_problem(p)
        return
    if not write_with_confirmation(ctx, changes, yes):
        return
    for p in problems:
        if p.fix_note:
            out.echo(p.fix_note)
    finish(ctx, "doctor: fix")
