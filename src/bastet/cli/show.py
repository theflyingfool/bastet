from collections import Counter

import typer

from bastet.cli.common import handles_errors, load_context
from bastet.core.errors import BastetError
from bastet.core.inventory import Inventory
from bastet.core.yamlstyle import dump_frontmatter


def _table(rows: list[list[str]]) -> list[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return ["  " + "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]


def _show_all(inv: Inventory) -> None:
    hosts = inv.of_kind("host")
    typer.echo(f"Hosts ({len(hosts)})")
    if hosts:
        rows = [[d.name, str(d.data.get("type", "?")), str(d.data.get("ip", "")), str(d.data.get("os", ""))] for d in hosts]
        for line in _table(rows):
            typer.echo(line)
    hardware = inv.of_kind("hardware")
    counts = Counter(str(d.data.get("status", "in-service")) for d in hardware)
    summary = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
    typer.echo(f"Hardware ({len(hardware)})" + (f": {summary}" if summary else ""))
    for kind, label in (("location", "Locations"), ("group", "Groups")):
        docs = inv.of_kind(kind)
        if docs:
            typer.echo(f"{label}: " + ", ".join(d.name for d in docs))


def _show_one(inv: Inventory, name: str) -> None:
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


@handles_errors
def show(name: str | None = typer.Argument(None, help="Show one host, hardware item, group or location.")) -> None:
    """List the inventory and any problems, or show one object."""
    inv = load_context().inventory
    if name:
        _show_one(inv, name)
    else:
        _show_all(inv)
    if inv.problems:
        typer.echo("\nProblems")
        for problem in inv.problems:
            typer.echo(f"  {problem}")
    if inv.errors:
        raise typer.Exit(1)
