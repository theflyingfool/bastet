"""bastet check / bastet apply: make hosts match the desired state their roles describe."""

import datetime as dt
import select
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import typer

import bastet.cli.secret as secret_mod
from bastet.cli.common import (
    confirm_upstream_secrets,
    Context,
    find_named_host,
    guard_prompts,
    handles_errors,
    load_context,
    print_problems,
    refresh_generated,
    resolve_jobs,
    scan_first,
    ssh_ports,
)
from bastet.core.secrets import health as secret_health
from bastet.cli.gather import _resolve_address, _scan_pinned, scan_keys, ssh_runner
from bastet.core import hostkeys
from bastet.core.errors import BastetError
from bastet.core.frontmatter import Document
from bastet.core.links import link_target
from bastet.core.parallel import HostFailed, HostLog, Outcome, run_parallel, stopping
from bastet.core.remote import SshTarget, close_master, control_path
from bastet.cli.reboot import RebootPlan, perform_reboot, reboot_decision
from bastet.engine.packages import Reboot
from bastet.core.changes import Change, write_changes
from bastet.core.secrets.redact import ACTIVE
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
    """Run a lynis audit during apply (check only reads the last report); a failure is a warning, never fatal.

    Doesn't print: this can run in a worker thread, so the caller logs through the host's buffered log.
    """
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


@dataclass
class _Ready:
    """A host that passed the serial prepare phase: what the (parallel) check and apply phases need."""

    doc: Document
    batches: list[Batch]
    reboots: list[Reboot]


def _with_where(exc: BastetError) -> BastetError:
    """Fold a BastetError's file/key into its message, the way the old serial loop reported it --
    `run_parallel` only keeps `.message` from a worker's exception."""
    where = f" ({exc.file.name}{':' + exc.key if exc.key else ''})" if exc.file else ""
    return BastetError(f"{exc.message}{where}")


def _node_of_map(by_name: dict[str, _Ready], subset: set[str], inv) -> dict[str, str]:
    """guest host -> node host, for guests whose node is also in `subset` (the run in question)."""
    out: dict[str, str] = {}
    for name in subset:
        link = link_target(by_name[name].doc.data.get("runs_on"))
        if not link:
            continue
        node_doc = inv.get(link)
        if node_doc is not None and node_doc.name in subset:
            out[name] = node_doc.name
    return out


def _parse_choice(answer: str, n: int) -> list[int] | None:
    try:
        idxs = sorted({int(x) for x in answer.split(",") if x.strip()})
    except ValueError:
        return None
    if not idxs or any(i < 1 or i > n for i in idxs):
        return None
    return idxs


def _choose_hosts(pending: list[str], checks: dict, *, yes: bool) -> list[str]:
    """The one question for apply: which pending hosts to apply to. `-y` means all, no question."""
    if not pending or yes:
        return list(pending)
    typer.echo("Changes to apply:")
    width = max(len(h) for h in pending)
    for i, h in enumerate(pending, 1):
        n = checks[h].count("would-change")
        typer.echo(f"  {i}) {h:<{width}}  {n} change{'s' if n != 1 else ''}")
    question = f"Apply to all {len(pending)}? [y]es / [n]o / numbers (e.g. 1,3): "
    for _ in range(3):
        answer = typer.prompt(question, default="", show_default=False).strip().lower()
        if answer in ("y", "yes"):
            return list(pending)
        if answer in ("", "n", "no"):
            return []
        idxs = _parse_choice(answer, len(pending))
        if idxs is not None:
            return [pending[i - 1] for i in idxs]
    return []


def _print_outcome_log(outcome: Outcome) -> None:
    for text, fg in outcome.log.lines:
        typer.secho(ACTIVE.mask(text), fg=fg)


def _run(names: list[str] | None, *, apply_changes: bool, yes: bool, verbose: bool, updates: bool = False,
         jobs: int | None = None) -> None:
    ctx = load_context()
    run_jobs = resolve_jobs(jobs, ctx.config)
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
    failed_hosts: set[str] = set()
    interrupted = False

    # Phase 1: prepare, serially, in inventory order -- the per-host skips, and `plan_for`, may ask
    # (secrets), and nothing here is thread-safe.
    ready: list[_Ready] = []
    for doc in docs:
        host_type = ctx.types.get(str(doc.data.get("type")))
        if host_type is not None and not host_type.managed:
            typer.echo(f"{doc.name}: configured through {host_type.managed_by or 'something else'}; Bastet doesn't apply roles to it")
            continue
        try:
            applied, batches = plan_for(ctx, doc, roles, updates)
            reboots = [r for b in batches for r in b.resources if isinstance(r, Reboot)]
            role_names = ", ".join(f"{a.role.name} ({', '.join(sorted({s.label for s in a.sources}))})" for a in applied)
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
                typer.echo(f"{doc.name}: {role_names}: nothing to manage yet")
                continue
            typer.echo(f"roles: {role_names}")
            ready.append(_Ready(doc, batches, reboots))
        except BastetError as exc:
            if not apply_changes and isinstance(exc, MissingSecret):
                opt = secret_mod._opt_for(exc.sp)
                if opt and opt.generate:
                    typer.echo(f"{doc.name}: would generate {exc.sp.text}")
                    continue
            where = f" ({exc.file.name}{':' + exc.key if exc.key else ''})" if exc.file else ""
            typer.secho(ctx.secrets.redactor.mask(f"{doc.name}: {exc.message}{where}"), fg="red")
            failed_hosts.add(doc.name)

    by_name: dict[str, _Ready] = {r.doc.name: r for r in ready}
    targets: dict[str, object] = {}
    runners: dict[str, object] = {}
    checks: dict[str, object] = {}
    fresh_items: dict[str, list] = {}

    with tempfile.TemporaryDirectory(prefix="bastet-") as tmp:
        try:
            # Phase 2: check, in parallel. `connect` never asks here (the key was pinned at `gather`).
            if ready:
                def check_work(host: str, log: HostLog):
                    r = by_name[host]
                    try:
                        runner, target = connect(ctx, r.doc, Path(tmp), yes=yes)
                    except BastetError as exc:
                        raise _with_where(exc) from exc
                    targets[host] = target  # registered right away, so `close_master` always runs for it
                    runners[host] = runner
                    return run_host(runner, host, r.batches, apply=False)

                def on_check_done(outcome: Outcome) -> None:
                    _print_outcome_log(outcome)
                    if outcome.status == "not-started":
                        typer.echo(f"{outcome.host}: not started")
                        failed_hosts.add(outcome.host)
                        return
                    if outcome.status == "error":
                        typer.secho(ctx.secrets.redactor.mask(f"{outcome.host}: {outcome.error}"), fg="red")
                        failed_hosts.add(outcome.host)
                        return
                    check = outcome.value
                    checks[outcome.host] = check
                    typer.echo(ctx.secrets.redactor.mask(render_host(check, full=full)))
                    if check.count("failed") > 0:
                        failed_hosts.add(outcome.host)

                try:
                    run_parallel([r.doc.name for r in ready], check_work, jobs=run_jobs, on_done=on_check_done)
                except KeyboardInterrupt:
                    interrupted = True

            errored_hosts: set[str] = set(failed_hosts)  # hosts that never produced a check at all
            chosen: list[str] = []
            run_set_ordered: list[str] = []
            apply_failed_map: dict[str, bool] = {}

            if apply_changes and not interrupted:
                checked_names = [r.doc.name for r in ready if r.doc.name in checks]
                pending_hosts = [h for h in checked_names if checks[h].count("would-change") > 0]
                clean_hosts = [h for h in checked_names if checks[h].count("would-change") == 0]

                chosen = _choose_hosts(pending_hosts, checks, yes=yes)
                for h in pending_hosts:
                    if h not in chosen:
                        typer.echo(f"{h}: nothing applied")

                run_set_ordered = [h for h in checked_names if h in chosen or h in clean_hosts]

                # Phase 5: apply + the lynis audit, in parallel; a guest waits for its node.
                if run_set_ordered:
                    node_of = _node_of_map(by_name, set(run_set_ordered), ctx.inventory)
                    apply_errored: set[str] = set()

                    def apply_work(host: str, log: HostLog):
                        r = by_name[host]
                        runner = runners[host]
                        done = run_host(runner, host, r.batches, apply=True, should_stop=stopping) if host in chosen else None
                        fresh = None
                        if not stopping() and any(isinstance(res, LynisReport) for b in r.batches for res in b.resources):
                            log.echo(f"{host}: running a lynis audit (1–3 minutes)…")
                            warning = run_audit(runner, r.doc)
                            if warning:
                                log.secho(warning, fg="yellow")
                            else:
                                fresh = run_host(runner, host, [Batch("lynis", [LynisReport()])], apply=False).items
                        if done is not None and not done.ok:
                            # a failed (not merely erroring) apply still has a result worth showing --
                            # HostFailed keeps it while still failing this host for `after` dependents.
                            raise HostFailed(f"{host}: apply failed", (done, fresh))
                        return done, fresh

                    def on_apply_done(outcome: Outcome) -> None:
                        _print_outcome_log(outcome)
                        if outcome.status == "not-started":
                            typer.echo(f"{outcome.host}: not started")
                            failed_hosts.add(outcome.host)
                            apply_errored.add(outcome.host)
                            return
                        if outcome.status == "error":
                            failed_hosts.add(outcome.host)
                            if outcome.value is None:
                                typer.secho(ctx.secrets.redactor.mask(f"{outcome.host}: {outcome.error}"), fg="red")
                                apply_errored.add(outcome.host)
                                return
                            done, fresh = outcome.value
                            if done is not None:
                                typer.echo(ctx.secrets.redactor.mask(render_host(done, full=full)))
                            apply_failed_map[outcome.host] = True
                            if fresh is not None:
                                fresh_items[outcome.host] = fresh
                            return
                        done, fresh = outcome.value
                        if done is not None:
                            # `apply_work` raises `HostFailed` whenever `not done.ok`, so a "done"
                            # outcome here always had a clean apply (or no apply at all).
                            typer.echo(ctx.secrets.redactor.mask(render_host(done, full=full)))
                            apply_failed_map[outcome.host] = False
                        else:
                            apply_failed_map[outcome.host] = checks[outcome.host].count("failed") > 0
                            if apply_failed_map[outcome.host]:
                                failed_hosts.add(outcome.host)
                        if fresh is not None:
                            fresh_items[outcome.host] = fresh

                    try:
                        run_parallel(run_set_ordered, apply_work, jobs=run_jobs, on_done=on_apply_done, after=node_of)
                    except KeyboardInterrupt:
                        interrupted = True
                    errored_hosts |= apply_errored

                # Phase 6: reboots. The decision (and its one question) is serial, in inventory order;
                # the reboot itself runs in parallel, a node only after its guests in this run.
                if run_set_ordered and not interrupted:
                    plans: dict[str, RebootPlan] = {}
                    for h in run_set_ordered:
                        if h in errored_hosts:
                            continue
                        r = by_name[h]
                        result = reboot_decision(
                            runners[h], targets.get(h), r.doc, r.reboots,
                            yes=yes, apply_failed=apply_failed_map.get(h, False),
                        )
                        if result is None:
                            continue
                        if isinstance(result, str):
                            typer.echo(ctx.secrets.redactor.mask(result))
                        else:
                            plans[h] = result

                    if plans:
                        reboot_node_of = _node_of_map(by_name, set(plans), ctx.inventory)
                        nodes_with_guest = {n for n in reboot_node_of.values() if n in plans}
                        wave1 = [h for h in plans if h not in nodes_with_guest]
                        wave2 = [h for h in plans if h in nodes_with_guest]

                        def reboot_work(host: str, log: HostLog):
                            return perform_reboot(
                                plans[host],
                                lambda h=host: connect(ctx, by_name[h].doc, Path(tmp), yes=yes)[0],
                            )

                        def on_reboot_done(outcome: Outcome) -> None:
                            _print_outcome_log(outcome)
                            if outcome.status == "error":
                                typer.secho(ctx.secrets.redactor.mask(f"{outcome.host}: {outcome.error}"), fg="red")
                                failed_hosts.add(outcome.host)
                            elif outcome.status == "not-started":
                                typer.echo(f"{outcome.host}: not started")
                                failed_hosts.add(outcome.host)
                            else:
                                typer.echo(ctx.secrets.redactor.mask(outcome.value))

                        try:
                            if wave1:
                                run_parallel(wave1, reboot_work, jobs=run_jobs, on_done=on_reboot_done)
                            if wave2:
                                run_parallel(wave2, reboot_work, jobs=run_jobs, on_done=on_reboot_done)
                        except KeyboardInterrupt:
                            interrupted = True
        finally:
            for target in targets.values():
                if target is not None:
                    close_master(target)

    # Phase 7: write, serially -- security notes, push warning, secret summary, refresh.
    notes_written = False
    for r in ready:
        host = r.doc.name
        if host not in checks:
            continue
        items = checks[host].items
        if host in fresh_items:
            items = [i for i in items if not isinstance(i.resource, LynisReport)] + fresh_items[host]
        notes_written |= _write_security_note(ctx, r.doc, items)

    if notes_written and not ctx.repo.push():
        typer.secho("warning: push failed; the security notes are committed locally", fg="yellow", err=True)
    scope = [d.name for d in docs]
    if secret_health.relevant_secrets(ctx, scope):
        for line in secret_health.summary_lines(secret_health.findings(ctx, scope_hosts=scope)):
            typer.echo(ctx.secrets.redactor.mask(line))
    refresh_generated(ctx)
    if failed_hosts or interrupted:
        raise typer.Exit(1)


@handles_errors
def check(
    hosts: list[str] | None = typer.Argument(None, help="Hosts to check (default: all hosts)."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show compliant items for every host."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask to confirm a new host key."),
    jobs: int | None = typer.Option(None, "--jobs", "-j", min=1, help="How many hosts to check at once (default: the config value)."),
) -> None:
    """Show what differs between each host and the desired state its roles describe. Changes nothing."""
    with guard_prompts():
        _run(hosts, apply_changes=False, yes=yes, verbose=verbose, jobs=jobs)


@handles_errors
def apply(
    hosts: list[str] | None = typer.Argument(None, help="Hosts to apply to (default: all hosts)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask; apply every change."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show compliant items for every host."),
    updates: bool = typer.Option(False, "--updates", help="Also install pending updates on hosts whose policy is manual."),
    jobs: int | None = typer.Option(None, "--jobs", "-j", min=1, help="How many hosts to apply to at once (default: the config value)."),
) -> None:
    """Make each host match its roles: shows the check first, asks, applies, and verifies."""
    with guard_prompts():
        _run(hosts, apply_changes=True, yes=yes, verbose=verbose, updates=updates, jobs=jobs)
