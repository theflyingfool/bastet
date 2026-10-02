"""bastet check / bastet apply: make hosts match the desired state their roles describe (spec 9.2)."""

import datetime as dt
import os
import tempfile
from pathlib import Path

import typer

from bastet.cli.common import Context, handles_errors, load_context, refresh_generated, ssh_port
from bastet.cli.gather import _fixed_ip, local_runner, scan_keys, ssh_runner, sudo_validate
from bastet.core import hostkeys
from bastet.core.errors import BastetError
from bastet.core.frontmatter import Document
from bastet.core.remote import SshTarget, close_master, control_path
from bastet.cli.reboot import handle_reboot
from bastet.engine.packages import Reboot
from bastet.core.changes import Change, write_changes
from bastet.core.security_note import security_items, security_note, security_path
from bastet.engine.report import render_host
from bastet.engine.script import exec_script, new_mark
from bastet.engine.security import LYNIS_AUDIT, LynisReport
from bastet.engine.run import Batch, run_host
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import RoleDef, load_roles
from bastet.roles.pages import options_in_body
from bastet.roles.resolve import Applied, resolve


def host_info(ctx: Context, doc: Document, updates: bool = False) -> HostInfo:
    lab = ctx.inventory.lab
    host_type = ctx.types.get(str(doc.data.get("type")))
    return HostInfo(name=doc.name, type=str(doc.data.get("type", "")), data=dict(doc.data), root=ctx.root,
                    lab=dict(lab.data) if lab else {}, apply_updates=updates,
                    physical=bool(host_type and host_type.physical))


def plan_for(ctx: Context, doc: Document, roles: dict[str, RoleDef], updates: bool = False) -> tuple[list[Applied], list[Batch]]:
    applied = resolve(ctx.inventory, doc, ctx.types, roles)
    return applied, batches_for(applied, host_info(ctx, doc, updates=updates))


def connect(ctx: Context, doc: Document, tmp: Path, *, yes: bool):
    if doc.data.get("connection") == "local":
        if not yes and os.geteuid() != 0:
            sudo_validate()
        return local_runner(), None
    address = doc.data.get("address") or _fixed_ip(doc.data.get("ip"))
    if not address:
        raise BastetError("no address to connect to; set `address:` or a fixed `ip:`", file=doc.path)
    recorded = doc.data.get("ssh_host_key")
    if not recorded:
        raise BastetError("no confirmed host key yet; run `bastet gather` on this host first", file=doc.path)
    port = ssh_port(ctx, doc)
    keys = scan_keys(str(address), recorded=str(recorded), port=port)
    if hostkeys.check(str(recorded), keys) != "match":
        raise BastetError("the host's key doesn't match ssh_host_key; run `bastet gather` "
                          "(with --accept-new-hostkey after a reinstall)", file=doc.path, key="ssh_host_key")
    key = ctx.config.ssh.key
    if key is None:
        raise BastetError("no Bastet SSH key configured; run `bastet init`")
    known = hostkeys.write_known_hosts(hostkeys.pinned(str(recorded), keys), str(address), port, tmp / doc.name)
    target = SshTarget(str(address), "bastet", key, known, port=port, control_path=control_path())
    return ssh_runner(target), target


AUDIT_TIMEOUT = 600


def _write_security_note(ctx: Context, doc: Document, items) -> bool:
    """Write the host's security note from this run's reports (a Bastet-owned file: no confirmation)."""
    if not security_items(items) or not ctx.repo.is_repo():
        return False
    path = security_path(ctx.root, doc.name)
    text = security_note(doc.name, items, dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    before = path.read_text(encoding="utf-8") if path.exists() else None
    write_changes([Change(path, before, text)])
    return ctx.repo.commit([path], f"refresh: security note {doc.name}")


def run_audit(runner, doc: Document) -> str | None:
    """Run a lynis audit during apply (check only reads the last report); a failure is a warning, never fatal."""
    typer.echo(f"{doc.name}: running a lynis audit (1–3 minutes)…")
    try:
        res = runner.run(exec_script([LYNIS_AUDIT], root=True, mark=new_mark()), timeout=AUDIT_TIMEOUT)
    except BastetError as exc:
        return f"{doc.name}: lynis audit failed: {exc.message}; the security note keeps the previous report"
    if res.returncode != 0:
        tail = (res.stderr.strip().splitlines() or [f"exit status {res.returncode}"])[-1]
        return f"{doc.name}: lynis audit failed: {tail}; the security note keeps the previous report"
    return None


def _hosts(ctx: Context, names: list[str] | None) -> list[Document]:
    if names:
        docs = []
        for name in names:
            doc = ctx.inventory.get(name)
            if doc is None or doc.data.get("bastet") != "host":
                raise BastetError(f"no host named '{name}' in the inventory")
            docs.append(doc)
        return docs
    return [d for d in ctx.inventory.of_kind("host") if d.data.get("state", "present") != "destroyed"]


def _run(names: list[str] | None, *, apply_changes: bool, yes: bool, verbose: bool, updates: bool = False) -> None:
    ctx = load_context()
    roles = load_roles()
    docs = _hosts(ctx, names)
    for problem in ctx.inventory.problems:  # a role file that applies nowhere would otherwise be silently ignored
        f = problem.error.file
        if f is not None and "_roles" in Path(f).parts:
            typer.secho(f"{Path(f).relative_to(ctx.root)}: {problem}", fg="yellow")
    full = verbose or len(docs) == 1
    failed = False
    notes_written = False
    with tempfile.TemporaryDirectory(prefix="bastet-") as tmp:
        for doc in docs:
            target = None
            host_type = ctx.types.get(str(doc.data.get("type")))
            if host_type is not None and not host_type.managed:
                typer.echo(f"{doc.name}: configured through {host_type.managed_by or 'something else'}; Bastet doesn't apply roles to it")
                continue
            try:
                applied, batches = plan_for(ctx, doc, roles, updates)
                reboots = [r for b in batches for r in b.resources if isinstance(r, Reboot)]
                names = ", ".join(f"{a.role.name} ({', '.join(sorted({s.label for s in a.sources}))})" for a in applied)
                if not applied:
                    typer.echo(f"{doc.name}: no roles")
                    continue
                for a in applied:
                    for s in a.sources:
                        found = options_in_body(a.role, s.doc.body) if s.doc is not None else []
                        if found:
                            typer.secho(f"{doc.name}: {s.doc.path.relative_to(ctx.root)} has "
                                        f"{', '.join(k + ':' for k in found)} in the page text; Bastet only reads "
                                        "the properties at the top", fg="yellow")
                if not any(b.resources for b in batches):
                    typer.echo(f"{doc.name}: {names}: nothing to manage yet")
                    continue
                typer.echo(f"roles: {names}")
                runner, target = connect(ctx, doc, Path(tmp), yes=yes)
                check = run_host(runner, doc.name, batches, apply=False)
                typer.echo(render_host(check, full=full))
                notes_written |= _write_security_note(ctx, doc, check.items)
                pending = check.count("would-change")
                if not apply_changes:
                    failed |= check.count("failed") > 0
                    continue
                apply_failed = False
                if not pending:
                    failed |= check.count("failed") > 0
                    apply_failed = check.count("failed") > 0
                elif not yes and not typer.confirm(f"Apply {pending} change(s) to {doc.name}?", default=False):
                    typer.echo(f"{doc.name}: nothing applied")
                    continue
                else:
                    done = run_host(runner, doc.name, batches, apply=True)
                    typer.echo(render_host(done, full=full))
                    failed |= not done.ok
                    apply_failed = not done.ok
                if any(isinstance(res, LynisReport) for b in batches for res in b.resources):
                    warning = run_audit(runner, doc)
                    if warning:
                        typer.secho(warning, fg="yellow")
                    else:  # the fresh audit replaces the report the check read
                        fresh = run_host(runner, doc.name, [Batch("lynis", [LynisReport()])], apply=False).items
                        notes_written |= _write_security_note(
                            ctx, doc, [i for i in check.items if not isinstance(i.resource, LynisReport)] + fresh)
                note = handle_reboot(runner, target, doc, reboots, yes=yes, apply_failed=apply_failed,
                                     connect_again=lambda doc=doc: connect(ctx, doc, Path(tmp), yes=yes)[0])
                if note:
                    typer.echo(note)
            except BastetError as exc:
                where = f" ({exc.file.name}{':' + exc.key if exc.key else ''})" if exc.file else ""
                typer.secho(f"{doc.name}: {exc.message}{where}", fg="red")
                failed = True
            finally:
                if target is not None:
                    close_master(target)
    if notes_written and not ctx.repo.push():
        typer.secho("warning: push failed; the security notes are committed locally", fg="yellow", err=True)
    refresh_generated(ctx)
    if failed:
        raise typer.Exit(1)


@handles_errors
def check(
    hosts: list[str] | None = typer.Argument(None, help="Hosts to check (default: all hosts)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show compliant items for every host."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask for the local sudo password."),
) -> None:
    """Show what differs between each host and the desired state its roles describe. Changes nothing."""
    _run(hosts, apply_changes=False, yes=yes, verbose=verbose)


@handles_errors
def apply(
    hosts: list[str] | None = typer.Argument(None, help="Hosts to apply to (default: all hosts)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask; apply every change."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show compliant items for every host."),
    updates: bool = typer.Option(False, "--updates", help="Also install pending updates on hosts whose policy is manual."),
) -> None:
    """Make each host match its roles: shows the check first, asks, applies, and verifies."""
    _run(hosts, apply_changes=True, yes=yes, verbose=verbose, updates=updates)
