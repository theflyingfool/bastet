"""bastet check / bastet apply: make hosts match the desired state their roles describe (spec 9.2)."""

import datetime as dt
import select
import sys
import tempfile
from pathlib import Path

import typer

import bastet.cli.secret as secret_mod
from bastet.cli.common import (
    confirm_upstream_secrets,
    Context,
    find_named_host,
    handles_errors,
    load_context,
    print_problems,
    refresh_generated,
    scan_first,
    ssh_ports,
)
from bastet.core.secrets import health as secret_health
from bastet.cli.gather import _resolve_address, _scan_pinned, scan_keys, ssh_runner
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
from bastet.core.secrets.refs import MissingSecret, resolve_refs
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
    for a in applied:
        a.values, became_secret = resolve_refs(a.values, host=doc.name, role=a.role.name, options=a.role.options, sctx=ctx.secrets)
        a.secret = bool(became_secret)
    return applied, batches_for(applied, host_info(ctx, doc, updates=updates))


def connect(ctx: Context, doc: Document, tmp: Path, *, yes: bool):
    address = _resolve_address(doc)
    if not address:
        raise BastetError("no address to connect to; set `address:` or a fixed `ip:`", file=doc.path)
    recorded = doc.data.get("ssh_host_key")
    if not recorded:
        raise BastetError("no confirmed host key yet; run `bastet gather` on this host first", file=doc.path)
    keys, port = _scan_pinned(doc, str(address), str(recorded), ssh_ports(ctx, doc), scan_keys)
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
    try:
        if ctx.repo.busy():
            typer.secho(f"{doc.name}: security note not written: a git merge or rebase is in progress", fg="yellow")
            return False
        path = security_path(ctx.root, doc.name)
        text = security_note(doc.name, items, dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if before is not None and _without_checked(before) == _without_checked(text):
            return False  # nothing new but the time: no commit on every check
        write_changes([Change(path, before, text)])
        return ctx.repo.commit([path], ctx.secrets.redactor.mask(f"refresh: security note {doc.name}"))
    except Exception as exc:  # a note must never stop a check or an apply
        typer.secho(ctx.secrets.redactor.mask(f"{doc.name}: security note not written: {exc.__class__.__name__}: {exc}"),
                    fg="yellow")
        return False


def _without_checked(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("checked:"))


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


def _generate_missing(ctx: Context, needed: list) -> None:
    """Generate every missing secret the contract can generate, in one commit, before any host is touched."""
    if not needed:
        return
    paths: list[Path] = []
    texts: list[str] = []
    for n in needed:
        value = secret_mod._generate(n.contract_opt.generate)
        secret_mod._write_note(ctx, n.sp, value, "generated", exists=False)
        ctx.secrets.redactor.add(value)
        paths.append(ctx.root / n.sp.rel)
        texts.append(n.sp.text)
        typer.echo(f"Generated {n.sp.text}.")
    if ctx.repo.is_repo():
        from bastet.core.secrets import confirm as secrets_confirm

        was_pending = secrets_confirm.pending(ctx.repo, ctx.root)
        message = f"secret: generate {len(texts)} secrets ({', '.join(texts)})"
        ctx.repo.commit(paths, message)
        secrets_confirm.confirm_own_commit(ctx.repo, ctx.root, was_pending)
        if not ctx.repo.push():
            typer.secho("warning: push failed; the commit is kept locally", fg="yellow", err=True)


def _ask_missing(ctx: Context, needed: list, *, yes: bool) -> None:
    """Ask, through the same per-secret prompt `secret set` uses, for missing secrets the contract can't
    generate. Only when interactive: with `-y` or no terminal, these are left missing, so the host that
    needs them fails (and is reported) when its role is resolved, same as any other missing secret.
    """
    if not needed or yes or not secret_mod._stdin_is_tty():
        return
    for n in needed:
        secret_mod._set_one(ctx, n.sp, n.contract_opt)
    if ctx.repo.is_repo() and not ctx.repo.push():
        typer.secho("warning: push failed; the commit(s) are kept locally", fg="yellow", err=True)


UPSTREAM_SECRETS_TIMEOUT = 60


def _wait_answer(prompt: str, timeout: float) -> str | None:
    """Reads one line from stdin, waiting up to `timeout` seconds; None on timeout. Patchable for tests."""
    typer.echo(prompt, nl=False)
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    return sys.stdin.readline()


def _confirm_upstream_secrets(ctx: Context) -> bool:
    """Spec 15.8: a pull that changed a secret note asks before `apply` goes on, even with `-y`; no terminal,
    no answer within 60s, or "no" stops the whole run (no host is touched)."""
    if not secret_mod._stdin_is_tty():
        typer.secho("Secrets changed upstream and no terminal is attached; stopping.", fg="red", err=True)
        return False
    answer = _wait_answer("Use these? [y/N] ", UPSTREAM_SECRETS_TIMEOUT)
    if answer is None:
        typer.secho(f"No answer within {UPSTREAM_SECRETS_TIMEOUT}s; stopping.", fg="red", err=True)
        return False
    return answer.strip().lower() in ("y", "yes")


def _prepare_secrets(ctx: Context, docs: list[Document], *, yes: bool) -> None:
    """Before any host is touched: generate every missing, generatable secret, then ask for the rest."""
    needed = secret_mod.needed_secrets(ctx, hosts=[d.name for d in docs])
    generatable = [n for n in needed if n.contract_opt and n.contract_opt.generate]
    others = [n for n in needed if n not in generatable]
    _generate_missing(ctx, generatable)
    _ask_missing(ctx, others, yes=yes)


def _hosts(ctx: Context, names: list[str] | None) -> list[Document]:
    if names:
        return [find_named_host(ctx, name) for name in names]
    return [d for d in ctx.inventory.of_kind("host") if d.data.get("state", "present") != "destroyed"]


def _run(names: list[str] | None, *, apply_changes: bool, yes: bool, verbose: bool, updates: bool = False) -> None:
    ctx = load_context()
    print_problems(ctx)
    if apply_changes and ctx.upstream_secrets:
        if not _confirm_upstream_secrets(ctx):
            raise typer.Exit(1)
        confirm_upstream_secrets(ctx)
    roles = load_roles()
    docs = _hosts(ctx, names)
    if apply_changes:
        _prepare_secrets(ctx, docs, yes=yes)
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
                typer.echo(ctx.secrets.redactor.mask(render_host(check, full=full)))
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
                    typer.echo(ctx.secrets.redactor.mask(render_host(done, full=full)))
                    failed |= not done.ok
                    apply_failed = not done.ok
                if any(isinstance(res, LynisReport) for b in batches for res in b.resources):
                    warning = run_audit(runner, doc)
                    if warning:
                        typer.secho(ctx.secrets.redactor.mask(warning), fg="yellow")
                    else:  # the fresh audit replaces the report the check read
                        fresh = run_host(runner, doc.name, [Batch("lynis", [LynisReport()])], apply=False).items
                        notes_written |= _write_security_note(
                            ctx, doc, [i for i in check.items if not isinstance(i.resource, LynisReport)] + fresh)
                note = handle_reboot(runner, target, doc, reboots, yes=yes, apply_failed=apply_failed,
                                     connect_again=lambda doc=doc: connect(ctx, doc, Path(tmp), yes=yes)[0])
                if note:
                    typer.echo(ctx.secrets.redactor.mask(note))
            except BastetError as exc:
                if not apply_changes and isinstance(exc, MissingSecret):
                    opt = secret_mod._opt_for(exc.sp)
                    if opt and opt.generate:
                        typer.echo(f"{doc.name}: would generate {exc.sp.text}")
                        continue
                where = f" ({exc.file.name}{':' + exc.key if exc.key else ''})" if exc.file else ""
                typer.secho(ctx.secrets.redactor.mask(f"{doc.name}: {exc.message}{where}"), fg="red")
                failed = True
            finally:
                if target is not None:
                    close_master(target)
    if notes_written and not ctx.repo.push():
        typer.secho("warning: push failed; the security notes are committed locally", fg="yellow", err=True)
    scope = [d.name for d in docs]
    if secret_health.relevant_secrets(ctx, scope):
        for line in secret_health.summary_lines(secret_health.findings(ctx, scope_hosts=scope)):
            typer.echo(ctx.secrets.redactor.mask(line))
    refresh_generated(ctx)
    if failed:
        raise typer.Exit(1)


@handles_errors
def check(
    hosts: list[str] | None = typer.Argument(None, help="Hosts to check (default: all hosts)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show compliant items for every host."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask to confirm a new host key."),
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
