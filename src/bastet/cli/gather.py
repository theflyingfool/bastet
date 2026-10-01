import getpass
import ipaddress
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

import typer

from bastet.cli.common import Context, handles_errors, load_context, refresh_generated, write_with_confirmation
from bastet.core.render import lab_embed_changes
from bastet.core.scaffold import new_host
from bastet.core import hostkeys
from bastet.core.bootstrap import setup_command
from bastet.core.collect import Snapshot, collect, save_snapshot
from bastet.core.config import data_dir
from bastet.core.errors import AuthFailed, BastetError
from bastet.core.facts import extract
from bastet.core.frontmatter import Document
from bastet.core.gatherplan import Note, plan_update
from bastet.core.hardware import RunState, observe_hardware, plan_hardware
from bastet.core.remote import LocalRunner, SshRunner, SshTarget, run_interactive


def local_runner() -> LocalRunner:
    return LocalRunner()


def ssh_runner(target: SshTarget) -> SshRunner:
    return SshRunner(target)


def scan_keys(address: str, recorded: str | None = None) -> list[hostkeys.HostKey]:
    return hostkeys.scan(address, recorded=recorded)


def sudo_validate() -> bool:
    """Ask for the user's sudo password once, so local root-only probes can use `sudo -n`."""
    try:
        return subprocess.run(["sudo", "-v"]).returncode == 0
    except FileNotFoundError:
        return False


def interactive(target: SshTarget, command: str) -> int:
    return run_interactive(target, command)


def _fixed_ip(value: object) -> str | None:
    text = str(value or "").split("/", 1)[0].strip()
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return None
    return text


def _collect(ctx: Context, doc: Document, tmp: Path, *, yes: bool, accept: bool) -> tuple[Snapshot, str | None]:
    if doc.data.get("connection") == "local":
        if not yes and os.geteuid() != 0:
            sudo_validate()
        return collect(local_runner(), doc.name), None
    address = doc.data.get("address") or _fixed_ip(doc.data.get("ip"))
    if not address:
        raise BastetError("no address to connect to; set `address:` (e.g. laptop.local) or a fixed `ip:`", file=doc.path)
    recorded = doc.data.get("ssh_host_key")
    keys = scan_keys(str(address), recorded=str(recorded) if recorded else None)
    best = hostkeys.preferred(keys)
    offered = hostkeys.record(best)
    status = hostkeys.check(recorded, keys)
    if status == "changed" and not accept:
        raise BastetError(
            f"host key changed: file has {recorded}, host offers {offered}. "
            "If the host was reinstalled, rerun with --accept-new-hostkey",
            file=doc.path, line=doc.key_lines.get("ssh_host_key"), key="ssh_host_key",
        )
    if status == "new" and not accept:
        if yes:
            raise BastetError("first contact: run without -y to confirm the host key, or pass --accept-new-hostkey")
        typer.echo(f"{doc.name}: first contact, host key {offered}")
        if not typer.confirm("Trust this key?", default=False):
            raise BastetError("host key not trusted; nothing gathered")
    if status == "match":
        trusted, hostkey = hostkeys.pinned(str(recorded), keys), str(recorded)
    else:
        trusted, hostkey = [best], offered
    known = hostkeys.write_known_hosts(trusted, str(address), 22, tmp / doc.name)
    key = ctx.config.ssh.key
    if key is not None:
        try:
            return collect(ssh_runner(SshTarget(str(address), "bastet", key, known)), doc.name), hostkey
        except AuthFailed:
            pass
    user = ctx.config.ssh.bootstrap_user or getpass.getuser()
    own = SshTarget(str(address), user, None, known)
    typer.echo(f"{doc.name}: the bastet user is not set up; using {user}@{address}")
    if key is not None and not yes and typer.confirm(
        f"Set up the bastet user on {doc.name} now (key login only, passwordless sudo)?", default=True
    ):
        pub = Path(str(key) + ".pub")
        if not pub.is_file():
            raise BastetError("Bastet's public key is missing; run `bastet init` or fix ssh.key in bastet.yml", file=pub)
        public_key = pub.read_text(encoding="utf-8")
        if interactive(own, setup_command(public_key)) == 0:
            try:
                return collect(ssh_runner(SshTarget(str(address), "bastet", key, known)), doc.name), hostkey
            except AuthFailed:
                typer.secho(f"{doc.name}: bastet user set up, but its login was refused; continuing as {user}", fg="yellow")
        else:
            typer.secho(f"{doc.name}: setting up the bastet user failed; continuing as {user}", fg="yellow")
    return collect(ssh_runner(own), doc.name), hostkey


def _guest_command(node: str, guest: dict) -> str:
    kind = "lxc" if guest.get("type") == "lxc" else "vm"
    return f"bastet add host {shlex.quote(str(guest['name']))} --type {kind} --on {shlex.quote(node)}"


def _offer_guests(ctx: Context, found: list[tuple[str, dict]], yes: bool) -> list:
    """List guests found on Proxmox nodes that aren't in the inventory; with confirmation, draft host files for all."""
    typer.echo(f"\n{len(found)} guest{'s' if len(found) != 1 else ''} aren't in the inventory:")
    for node, g in found:
        kind = "lxc" if g.get("type") == "lxc" else "vm"
        where = {"config": g.get("ip"), "neighbour": f"seen at {g.get('ip')}"}.get(g.get("ip_source"), "address unknown")
        typer.echo(f"  {g['name']} ({kind} {g['vmid']} on {node}, {where})")
    typer.echo("To add only some, answer N and run, for example:")
    for node, g in found[:3]:
        typer.echo(f"  {_guest_command(node, g)}")
    if yes or not typer.confirm(f"Add all {len(found)} to the inventory? (y adds every one listed)", default=False):
        return []
    drafts, names = [], set()
    for node, g in found:
        name, kind = str(g["name"]), "lxc" if g.get("type") == "lxc" else "vm"
        if name.lower() in names:
            continue
        names.add(name.lower())
        ip, address = (g["ip"], None) if g.get("ip_source") == "config" else ("dhcp", g.get("ip"))
        try:
            draft = new_host(ctx.inventory, ctx.types, name, kind, on=node, ip=ip, address=address,
                             extra={"vmid": g["vmid"]})
        except BastetError as exc:
            typer.secho(f"  skipped {name}: {exc}", fg="yellow")
            continue
        drafts.append(draft.change)
        if not address and ip == "dhcp":
            typer.secho(f"  {name}: no address known; set address: (a DNS name or IP) before gathering it", fg="yellow")
    return drafts


@handles_errors
def gather(
    hosts: list[str] | None = typer.Argument(None, help="Hosts to gather (default: all hosts)."),
    take: list[str] = typer.Option([], "--take", help="Accept the observed value of this field even if you set it. Repeatable."),
    accept_new_hostkey: bool = typer.Option(False, "--accept-new-hostkey", help="Trust a new or changed host key (e.g. after a reinstall)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask; write and commit."),
) -> None:
    """Collect facts from hosts and write them into their files, after showing the diff."""
    ctx = load_context()
    inv = ctx.inventory
    if hosts:
        docs = []
        for name in hosts:
            doc = inv.get(name)
            if doc is None or doc.data.get("bastet") != "host":
                raise BastetError(f"no host named '{name}' in the inventory")
            docs.append(doc)
    else:
        docs = inv.of_kind("host")
    if not docs:
        typer.echo("No hosts yet. Add one with `bastet add host`.")
        return

    take_fields = set(take) | ({"ssh_host_key"} if accept_new_hostkey else set())
    changes, notes, gathered = [], [], []
    host_warnings: dict[str, list[str]] = {}
    found_guests: list[tuple[str, dict]] = []
    run_state = RunState()
    with tempfile.TemporaryDirectory(prefix="bastet-") as tmp:
        for doc in docs:
            typer.echo(f"{doc.name}: gathering…")
            try:
                snapshot, hostkey = _collect(ctx, doc, Path(tmp), yes=yes, accept=accept_new_hostkey)
                save_snapshot(snapshot, data_dir())
                extracted = extract(snapshot.results)
                host_type = ctx.types.get(str(doc.data.get("type")), ctx.types["unknown"])
                view = observe_hardware(doc.name, snapshot.results, extracted) if host_type.physical else None
                if view is not None and view.pools:
                    extracted.facts["pools"] = view.pools
                update = plan_update(
                    doc, extracted, host_type, ctx.repo, take=take_fields, hostkey=hostkey, types=ctx.types
                )
                hw_changes, hw_notes = plan_hardware(inv, doc, view, ctx.repo, take=take_fields, run=run_state) if view else ([], [])
            except BastetError as exc:
                typer.secho(f"{doc.name}: {exc}", fg="yellow")
                continue
            except Exception as exc:  # one host's surprise must not lose the others' results
                typer.secho(f"{doc.name}: unexpected error: {exc.__class__.__name__}: {exc}", fg="yellow")
                continue
            for probe in extracted.missing_required:
                notes.append(Note(doc.name, "warn", f"required probe '{probe}' failed or its tool is missing"))
            notes.extend(update.notes)
            notes.extend(hw_notes)
            privilege = snapshot.results.get("privilege")
            if privilege is not None and privilege.output.strip() == "none":
                notes.append(Note(doc.name, "warn", "root-only facts skipped (no sudo): machine serial, DIMMs, BIOS, drive health, BMC, guests"))
            node_names = {doc.name.lower(), str(extracted.facts.get("hostname", "")).lower()}
            for guest in view.guests if view else []:
                if str(guest.get("node", "")).lower() not in node_names:
                    continue
                if guest.get("name") and inv.get(str(guest["name"])) is None:
                    found_guests.append((doc.name, guest))
            host_warnings[doc.name] = [n.message for n in notes if n.host == doc.name and n.severity == "warn"]
            host_changes = ([update.change] if update.change else []) + hw_changes
            if not host_changes:
                typer.echo(f"{doc.name}: up to date")
            else:
                changes.extend(host_changes)
                gathered.append(doc.name)

    for note in notes:
        mark = "⚠" if note.severity == "warn" else "·"
        typer.secho(f"{mark} {note.host}: {note.message}", fg="yellow" if note.severity == "warn" else None)
    added = _offer_guests(ctx, found_guests, yes) if found_guests else []
    changes.extend(added)
    if changes:
        message = f"gather: {', '.join(gathered)}" if gathered else "gather"
        if added:
            message += f"; add {len(added)} guest{'s' if len(added) != 1 else ''}"
        if not write_with_confirmation(ctx, [*changes, *lab_embed_changes(inv)], message, yes):
            return
    refresh_generated(ctx, warnings=host_warnings)
