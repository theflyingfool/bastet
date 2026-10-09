from collections import Counter
from pathlib import Path

import typer

from bastet.cli.common import handles_errors, load_context, problem_line
from bastet.core.errors import BastetError
from bastet.core.factsnote import facts_path
from bastet.core.hosttypes import HostType
from bastet.core.hostview import host_data
from bastet.core.inventory import Inventory
from bastet.core.selectors import is_selector, select_hosts
from bastet.core.yamlstyle import dump_frontmatter


def _table(rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return ["  " + "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]


def _host_rows(inv: Inventory, types: dict[str, HostType], hosts: list) -> list[list[str]]:
    return [[d.name, str(d.data.get("type", "?")), str(d.data.get("ip", "")), str(host_data(inv, d, types).get("os", ""))]
            for d in hosts]


def _show_hosts(inv: Inventory, types: dict[str, HostType], hosts: list) -> None:
    typer.echo(f"Hosts ({len(hosts)})")
    if hosts:
        for line in _table(_host_rows(inv, types, hosts)):
            typer.echo(line)


def _show_all(inv: Inventory, types: dict[str, HostType]) -> None:
    _show_hosts(inv, types, inv.of_kind("host"))
    hardware = inv.of_kind("hardware")
    counts = Counter(str(d.data.get("status", "in-service")) for d in hardware)
    summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
    typer.echo(f"Hardware ({len(hardware)})" + (f": {summary}" if summary else ""))
    for kind, label in (("location", "Locations"), ("group", "Groups")):
        docs = inv.of_kind(kind)
        if docs:
            typer.echo(f"{label}: " + ", ".join(d.name for d in docs))


def _show_one(inv: Inventory, root: Path, name: str) -> None:
    doc = inv.get(name)
    if doc is None:
        raise BastetError(f"no object named '{name}' in the inventory")
    typer.echo(f"{doc.name} ({doc.data['bastet']}) · {doc.path.relative_to(inv.root)}")
    for line in dump_frontmatter(doc.data).splitlines():
        typer.echo(f"  {line}")
    links = inv.linking_to(doc.name)
    if links:
        typer.echo("Linked from:")
        for other, key in links:
            typer.echo(f"  {other.name} ({key})")
    if doc.data.get("bastet") == "host":
        path = facts_path(inv.root, doc.name)
        rel = path.relative_to(inv.root)
        facts_doc = inv.facts.get(doc.name.lower())
        if facts_doc is None:
            typer.echo(f"\nGathered facts ({rel}): not gathered yet")
        else:
            typer.echo(f"\nGathered facts ({rel}):")
            for line in dump_frontmatter(inv.facts_for(doc.name)).splitlines():
                typer.echo(f"  {line}")
        for problem in inv.problems:
            if problem.error.file == doc.path:
                text, fg = problem_line(root, problem)
                typer.secho(text, fg=fg)


@handles_errors
def show(
    names: list[str] | None = typer.Argument(
        None, help="A name (shows that object), or selectors ('@type', '@group', '@lab', a glob) to list matching hosts."
    ),
) -> None:
    """List the inventory and any problems, or show one object, or a table of hosts matching a selector."""
    ctx = load_context()
    inv = ctx.inventory
    if names and len(names) == 1 and not is_selector(names[0]):
        _show_one(inv, ctx.root, names[0])
    elif names:
        _show_hosts(inv, ctx.types, select_hosts(inv, ctx.types, names, []))
    else:
        _show_all(inv, ctx.types)
    if inv.problems:
        typer.echo("\nProblems")
        for problem in inv.problems:
            typer.echo(f"  {problem}")
    if inv.errors:
        raise typer.Exit(1)
