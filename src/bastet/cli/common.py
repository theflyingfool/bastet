import functools
from dataclasses import dataclass
from pathlib import Path

import typer

from bastet.core.changes import Change, render_diff, write_changes
from bastet.core.config import Config, config_path, data_dir, inventory_dir, load_config
from bastet.core.errors import BastetError
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import HostType, load_host_types
from bastet.core.inventory import Inventory, load_inventory


def handles_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except BastetError as exc:
            typer.secho(f"error: {exc}", fg="red", err=True)
            raise typer.Exit(1) from None

    return wrapper


@dataclass
class Context:
    config: Config
    root: Path
    repo: GitRepo
    types: dict[str, HostType]
    inventory: Inventory


def load_context() -> Context:
    config = load_config(config_path())
    root = inventory_dir(config, data_dir())
    if not root.is_dir():
        raise BastetError("inventory directory does not exist; run `bastet init`", file=root)
    types = load_host_types()
    return Context(config=config, root=root, repo=GitRepo(root), types=types, inventory=load_inventory(root, types))


def write_with_confirmation(ctx: Context, changes: list[Change], message: str, yes: bool) -> bool:
    if not ctx.repo.is_repo():
        raise BastetError("the inventory is not a git repository; run `bastet init`", file=ctx.root)
    try:
        ctx.repo.pull()
    except BastetError as exc:
        typer.secho(f"warning: {exc}; continuing on the last pulled state", fg="yellow", err=True)
    targets = {c.path for c in changes}
    bastet_files = {d.path.resolve() for d in ctx.inventory.objects.values()} | {t.resolve() for t in targets}
    pending = [p for p in ctx.repo.dirty() if p.suffix == ".md" and p.resolve() in bastet_files]
    if pending:
        typer.echo("Uncommitted edits to Bastet files:")
        for path in pending:
            typer.echo(f"  {path.relative_to(ctx.root)}")
        if yes or typer.confirm("Commit them as you before Bastet writes?", default=True):
            ctx.repo.commit(pending, "Edits committed before a Bastet change", as_bastet=False)
        else:
            clash = sorted(targets & set(pending))
            if clash:
                raise BastetError("has uncommitted edits; commit them first", file=clash[0])
    for change in changes:
        typer.echo(render_diff(change, ctx.root))
    if not yes and not typer.confirm("Write?", default=True):
        typer.echo("Nothing written.")
        return False
    write_changes(changes)
    ctx.repo.commit(sorted(targets), message)
    if not ctx.repo.push():
        typer.secho("warning: push failed; the commit is kept locally", fg="yellow", err=True)
    return True
