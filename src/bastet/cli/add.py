import typer

from bastet.cli.common import handles_errors, load_context, write_with_confirmation
from bastet.core.scaffold import new_hardware, new_host

add_app = typer.Typer(no_args_is_help=True, help="Add a host or hardware to the inventory.")


@add_app.command("host")
@handles_errors
def add_host(
    name: str,
    type_: str = typer.Option(..., "--type", help="Host type, e.g. vps, proxmox-node, lxc, laptop."),
    ip: str | None = typer.Option(None, "--ip"),
    on: str | None = typer.Option(None, "--on", help="Parent host for an LXC or VM."),
    network: str | None = typer.Option(None, "--network", help="Lab network; suggests the next free address."),
    location: str | None = typer.Option(None, "--location"),
    provider: str | None = typer.Option(None, "--provider"),
    address: str | None = typer.Option(None, "--address", help="Name to connect to when the IP isn't fixed (e.g. laptop.local)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask; write and commit."),
) -> None:
    """Write a minimal host file."""
    ctx = load_context()
    draft = new_host(ctx.inventory, ctx.types, name, type_, ip=ip, on=on, network=network, location=location, provider=provider, address=address)
    if draft.suggested_ip:
        typer.echo(f"Suggested address: {draft.suggested_ip} (next free in {network})")
    write_with_confirmation(ctx, [draft.change], f"add host {name}", yes)


@add_app.command("hardware")
@handles_errors
def add_hardware(
    name: str,
    category: str = typer.Option(..., "--category", help="drive, nic, gpu, hba, server, psu, ..."),
    model: str | None = typer.Option(None, "--model"),
    serial: str | None = typer.Option(None, "--serial"),
    size: str | None = typer.Option(None, "--size"),
    installed_in: str | None = typer.Option(None, "--in", help="Host it's installed in."),
    location: str | None = typer.Option(None, "--location"),
    status: str | None = typer.Option(None, "--status"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Write a hardware file (e.g. a spare drive)."""
    ctx = load_context()
    change = new_hardware(
        ctx.inventory, name, category, model=model, serial=serial, size=size,
        installed_in=installed_in, location=location, status=status,
    )
    write_with_confirmation(ctx, [change], f"add hardware {name}", yes)
