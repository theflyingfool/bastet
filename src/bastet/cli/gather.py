import getpass
import ipaddress
import tempfile
from pathlib import Path

import typer

from bastet.cli.common import Context, handles_errors, load_context, write_with_confirmation
from bastet.core import hostkeys
from bastet.core.bootstrap import setup_command
from bastet.core.collect import Snapshot, collect, save_snapshot
from bastet.core.config import data_dir
from bastet.core.errors import AuthFailed, BastetError
from bastet.core.facts import extract
from bastet.core.frontmatter import Document
from bastet.core.gatherplan import Note, plan_update
from bastet.core.remote import LocalRunner, SshRunner, SshTarget, run_interactive
from bastet.core.views import ensure_views


def local_runner() -> LocalRunner:
    return LocalRunner()


def ssh_runner(target: SshTarget) -> SshRunner:
    return SshRunner(target)


def scan_keys(address: str) -> list[hostkeys.HostKey]:
    return hostkeys.scan(address)


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
        return collect(local_runner(), doc.name), None
    address = doc.data.get("address") or _fixed_ip(doc.data.get("ip"))
    if not address:
        raise BastetError("no address to connect to; set `address:` (e.g. laptop.local) or a fixed `ip:`", file=doc.path)
    keys = scan_keys(str(address))
    best = hostkeys.preferred(keys)
    offered = hostkeys.record(best)
    recorded = doc.data.get("ssh_host_key")
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
    known = hostkeys.write_known_hosts(keys, str(address), 22, tmp / doc.name)
    key = ctx.config.ssh.key
    if key is not None:
        try:
            return collect(ssh_runner(SshTarget(str(address), "bastet", key, known)), doc.name), offered
        except AuthFailed:
            pass
    user = ctx.config.ssh.bootstrap_user or getpass.getuser()
    own = SshTarget(str(address), user, None, known)
    typer.echo(f"{doc.name}: the bastet user is not set up; using {user}@{address}")
    if key is not None and not yes and typer.confirm(
        f"Set up the bastet user on {doc.name} now (key login only, passwordless sudo)?", default=True
    ):
        public_key = Path(str(key) + ".pub").read_text(encoding="utf-8")
        if interactive(own, setup_command(public_key)) == 0:
            try:
                return collect(ssh_runner(SshTarget(str(address), "bastet", key, known)), doc.name), offered
            except AuthFailed:
                typer.secho(f"{doc.name}: bastet user set up, but its login was refused; continuing as {user}", fg="yellow")
        else:
            typer.secho(f"{doc.name}: setting up the bastet user failed; continuing as {user}", fg="yellow")
    return collect(ssh_runner(own), doc.name), offered


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

    changes, notes, gathered = [], [], []
    with tempfile.TemporaryDirectory(prefix="bastet-") as tmp:
        for doc in docs:
            typer.echo(f"{doc.name}: gathering…")
            try:
                snapshot, hostkey = _collect(ctx, doc, Path(tmp), yes=yes, accept=accept_new_hostkey)
            except BastetError as exc:
                typer.secho(f"{doc.name}: {exc}", fg="yellow")
                continue
            save_snapshot(snapshot, data_dir())
            extracted = extract(snapshot.results)
            for probe in extracted.missing_required:
                notes.append(Note(doc.name, "warn", f"required probe '{probe}' failed or its tool is missing"))
            host_type = ctx.types.get(str(doc.data.get("type")), ctx.types["unknown"])
            update = plan_update(doc, extracted, host_type, ctx.repo, take=set(take), hostkey=hostkey)
            notes.extend(update.notes)
            if update.change is None:
                typer.echo(f"{doc.name}: up to date")
            else:
                changes.append(update.change)
                gathered.append(doc.name)

    for note in notes:
        mark = "⚠" if note.severity == "warn" else "·"
        typer.secho(f"{mark} {note.host}: {note.message}", fg="yellow" if note.severity == "warn" else None)
    if changes:
        write_with_confirmation(ctx, [*changes, *ensure_views(ctx.root)], f"gather: {', '.join(gathered)}", yes)
