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
from bastet.core.render import generated_changes


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


def refresh_generated(
    ctx: Context, *, warnings: dict[str, list[str]] | None = None, drift: dict[str, list[str]] | None = None
) -> int:
    """Rewrite Bastet's generated notes (summaries, dashboard, views) from the files; commit them as `refresh:`.

    Only files under _bastet/ are touched, so no confirmation is needed.
    """
    if not ctx.repo.is_repo():
        return 0
    try:
        if ctx.repo.busy():
            typer.secho("refresh skipped: a git merge or rebase is in progress in the inventory", fg="yellow", err=True)
            return 0
        try:
            ctx.repo.pull()
        except BastetError as exc:
            typer.secho(f"refresh skipped: couldn't sync with the remote ({exc.message})", fg="yellow", err=True)
            return 0
        ctx.inventory = load_inventory(ctx.root, ctx.types)
        changes = generated_changes(ctx.inventory, ctx.types, ctx.repo, warnings=warnings, drift=drift)
        if not changes:
            return 0
        write_changes(changes)
        ctx.repo.commit([c.path for c in changes], f"refresh: {len(changes)} generated note{'s' if len(changes) != 1 else ''}")
        if not ctx.repo.push():
            typer.secho("warning: push failed; the commit is kept locally", fg="yellow", err=True)
    except Exception as exc:  # refreshing generated notes must never break the command that triggered it
        typer.secho(f"refresh skipped: {exc.__class__.__name__}: {exc}", fg="yellow", err=True)
        return 0
    typer.echo(f"Refreshed {len(changes)} generated note{'s' if len(changes) != 1 else ''} in _bastet/.")
    return len(changes)


def ssh_port(ctx: Context, doc) -> int:
    """The port Bastet connects on: the host's ssh role `port` (first listed), else 22."""
    from bastet.roles.contract import load_roles  # lazy: roles builds on core
    from bastet.roles.resolve import resolve

    try:
        applied = {a.role.name: a for a in resolve(ctx.inventory, doc, ctx.types, load_roles())}
    except BastetError as exc:
        typer.secho(f"{doc.name}: roles couldn't be read ({exc.message}); connecting on port 22", fg="yellow", err=True)
        return 22
    ports = (applied["ssh"].values.get("port") if "ssh" in applied else None) or [22]
    return int(ports[0])
