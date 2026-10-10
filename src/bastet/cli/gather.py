import datetime as dt
import getpass
import json
import ipaddress
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

import typer

from bastet.cli.common import (
    Context,
    finish,
    load_context,
    next_hint,
    print_problems,
    resolve_jobs,
    scan_first,
    ssh_ports,
    write_with_confirmation,
)
from bastet.core.guests import guest_drift
from bastet.core.hostview import host_data
from bastet.core.links import link_target
from bastet.core.render import lab_embed_changes
from bastet.core.scaffold import new_host
from bastet.core.selectors import select_hosts
from bastet.core.tools import install_script, needed_tools
from bastet.core import hostkeys
from bastet.core.bootstrap import setup_command
from bastet.core.cabling import merge_links, propose_links
from bastet.core.networks import compare_networks, lab_networks
from bastet.core.collect import Snapshot, collect, save_snapshot
from bastet.core.config import data_dir
from bastet.core.errors import AuthFailed, BastetError, Unreachable
from bastet.core.facts import Extracted, extract
from bastet.core.factsnote import facts_change, hardware_facts_change
from bastet.core.frontmatter import Document
from bastet.core.unifi import device_facts, machine_item, parse_mca, redact
from bastet.core.gatherplan import Note, plan_facts
from bastet.core.hardware import (
    HardwareView, RunState, hw_baseline, missing_hardware, observe_hardware, plan_hardware, set_hw_facts,
)
from bastet.core.inventory import Inventory
from bastet.core.parallel import HostLog, Outcome, run_parallel
from bastet.core.remote import SshRunner, SshTarget, run_interactive
from bastet.core.secrets.redact import ACTIVE
from bastet.core.shell import ProbeResult

LOCAL_ADDRESS = "127.0.0.1"


def ssh_runner(target: SshTarget) -> SshRunner:
    return SshRunner(target)


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def scan_keys(address: str, recorded: str | None = None, port: int = 22) -> list[hostkeys.HostKey]:
    return hostkeys.scan(address, recorded=recorded, port=port)


def _resolve_address(doc: Document) -> str | None:
    """`connection: local` means this machine, reached over SSH at 127.0.0.1 unless `address:` says otherwise
    -- its `ip:` (e.g. a LAN address) never overrides that, since sshd only needs to listen on 127.0.0.1."""
    if doc.data.get("connection") == "local":
        return doc.data.get("address") or LOCAL_ADDRESS
    return doc.data.get("address") or _fixed_ip(doc.data.get("ip"))


def _scan_pinned(doc: Document, address: str, recorded: str | None, ports: list[int], scan):
    """Scan for the host's key; a local host that never answers gets a hint about sshd, not a generic one."""
    try:
        return scan_first(scan, address, recorded, ports)
    except Unreachable:
        if doc.data.get("connection") == "local":
            raise BastetError(
                f"{doc.name}: nothing answered on {address}:{ports[0]}; start sshd (ListenAddress 127.0.0.1 is enough)"
            ) from None
        raise


def interactive(target: SshTarget, command: str) -> int:
    return run_interactive(target, command)


def _fixed_ip(value: object) -> str | None:
    text = str(value or "").split("/", 1)[0].strip()
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return None
    return text


def _pin(ctx: Context, doc: Document, tmp: Path, *, yes: bool, accept: bool,
         ports: list[int] | None = None) -> tuple[str, Path, str, int]:
    """Scan, check and pin the host key (first contact asks); returns address, known_hosts path, recorded key, port."""
    ports = ports or [22]
    address = _resolve_address(doc)
    if not address:
        raise BastetError("no address to connect to; set `address:` (e.g. laptop.local) or a fixed `ip:`", file=doc.path)
    recorded = host_data(ctx.inventory, doc, ctx.types).get("ssh_host_key")
    facts_doc = ctx.inventory.facts.get(doc.name.lower())
    if facts_doc is not None and "ssh_host_key" in facts_doc.data:
        key_file, key_line = facts_doc.path, facts_doc.key_lines.get("ssh_host_key")
    else:
        # A key recorded only on the (old) host note, from before the facts note existed: still
        # honoured as a fallback, but reported there -- never silently re-trusted as Bastet's own.
        key_file, key_line = doc.path, doc.key_lines.get("ssh_host_key")
    keys, port = _scan_pinned(doc, str(address), str(recorded) if recorded else None, ports, scan_keys)
    best = hostkeys.preferred(keys)
    offered = hostkeys.record(best)
    status = hostkeys.check(recorded, keys)
    if status == "changed" and not accept:
        raise BastetError(
            f"host key changed: file has {recorded}, host offers {offered}. "
            "If the host was reinstalled, rerun with --accept-new-hostkey",
            file=key_file, line=key_line, key="ssh_host_key",
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
    known = hostkeys.write_known_hosts(trusted, str(address), port, tmp / doc.name)
    return str(address), known, hostkey, port


def _group(proposals) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in proposals:
        out.setdefault(p.host, []).append(p.link)
    return out


# One accumulator per facts note per gather run: every source (a host's own gather, a node observing
# a guest's vmid, a UniFi device observing a link, the guests offer) merges into the same entry here,
# keyed by host name (lowercase) -> (the host's own-cased name, its accumulated facts dict). Changes are
# built from this, once per note, only at the very end -- so order between sources never loses data.
FactsAcc = dict[str, tuple[str, dict]]


def _facts_baseline(inv: Inventory, facts_acc: FactsAcc, name: str) -> dict:
    """What this run has accumulated for `name`'s facts note so far, or the note as last written."""
    entry = facts_acc.get(name.lower())
    return dict(entry[1]) if entry is not None else dict(inv.facts_for(name))


def _set_facts(facts_acc: FactsAcc, name: str, facts: dict) -> None:
    """A host's own gather is authoritative for the whole note (besides what it pulled from the
    baseline for OBSERVED_BY_OTHERS keys), so this replaces the accumulated dict outright."""
    facts_acc[name.lower()] = (name, facts)


def _merge_facts(facts_acc: FactsAcc, inv: Inventory, name: str, updates: dict) -> None:
    """A secondary source (a node's vmid, a switch's link) adds a few keys to whatever is accumulated."""
    merged = _facts_baseline(inv, facts_acc, name)
    merged.update(updates)
    _set_facts(facts_acc, name, merged)


def _seen_by(link: dict) -> str:
    seen = link.get("seen_by")
    return str(seen if seen is not None else link_target(link.get("to")) or "").lower()


def _prune_seen_by(links: list, devices: set[str]) -> list:
    """Drop entries this run's gathered devices used to see but no longer report (unplugged)."""
    return [e for e in links if isinstance(e, dict) and _seen_by(e) not in devices]


@dataclass
class Prepared:
    """A host ready for its (parallel) collection: its pinned key, and a runner already logged in."""

    hostkey: str | None
    runner: object
    is_unifi: bool


def _prepare(ctx: Context, doc: Document, host_type, tmp: Path, *, yes: bool, accept: bool) -> Prepared:
    """Pin the host key and log in (asking as needed); the collection itself happens later, in parallel."""
    if host_type.name.startswith("unifi-"):
        address, known, hostkey, _ = _pin(ctx, doc, tmp, yes=yes, accept=accept)
        user = ctx.config.ssh.bootstrap_user or getpass.getuser()
        return Prepared(hostkey, ssh_runner(SshTarget(address, user, None, known)), True)
    address, known, hostkey, port = _pin(ctx, doc, tmp, yes=yes, accept=accept, ports=ssh_ports(ctx, doc))
    key = ctx.config.ssh.key
    if key is not None:
        try:
            runner = ssh_runner(SshTarget(str(address), "bastet", key, known, port=port))
            runner.run("true\n")  # cheap: just prove the login works before committing to it
            return Prepared(hostkey, runner, False)
        except AuthFailed:
            pass
    user = ctx.config.ssh.bootstrap_user or getpass.getuser()
    own = SshTarget(str(address), user, None, known, port=port)
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
                runner = ssh_runner(SshTarget(str(address), "bastet", key, known, port=port))
                runner.run("true\n")
                return Prepared(hostkey, runner, False)
            except AuthFailed:
                typer.secho(f"{doc.name}: bastet user set up, but its login was refused; continuing as {user}", fg="yellow")
        else:
            typer.secho(f"{doc.name}: setting up the bastet user failed; continuing as {user}", fg="yellow")
    return Prepared(hostkey, ssh_runner(own), False)


def _collect_one(prepared: Prepared, host: str):
    """The actual collection, run in a worker: `collect()`, or a UniFi `mca-dump`."""
    if prepared.is_unifi:
        res = prepared.runner.run("mca-dump\n", timeout=60)
        if res.returncode != 0 or not res.stdout.strip():
            raise BastetError("mca-dump failed or isn't there; is this a UniFi device, and does the device SSH login work?")
        return res.stdout
    return collect(prepared.runner, host)


def _echo_outcome(outcome: Outcome, done: str) -> None:
    """Print a finished parallel host's buffered lines, then its own result line."""
    for text, fg in outcome.log.lines:
        typer.secho(ACTIVE.mask(text), fg=fg)
    if outcome.status == "done":
        typer.echo(ACTIVE.mask(f"{outcome.host}: {done}"))
    elif outcome.status == "error":
        typer.secho(ACTIVE.mask(f"{outcome.host}: {outcome.error}"), fg="yellow")
    # "not-started" (e.g. after Ctrl-C): nothing to report, this host never ran.


def _tools_ask(ctx: Context, doc: Document, host_type, snapshot: Snapshot, installed: list[str], yes: bool):
    """Decide (asking if needed) whether to install missing tools on this host; None skips it."""
    mode = ctx.config.gather.install_tools
    if mode == "never" or doc.data.get("install_tools") is False or (mode == "ask" and yes):
        return None
    tools = [t for t in needed_tools(snapshot.results, host_type) if t not in installed]
    if not tools:
        return None
    manager = (snapshot.results.get("pkg_mgr").output.strip() if snapshot.results.get("pkg_mgr") else "") or None
    script = install_script(manager, tools)
    if script is None:
        typer.secho(f"{doc.name}: missing {', '.join(tools)}, but no supported package manager was found", fg="yellow")
        return None
    if mode == "ask" and not typer.confirm(
        f"{doc.name}: install {', '.join(tools)} for fuller hardware info?", default=True
    ):
        return None
    return script, tools


def _tools_round(
    ctx: Context, docs: list[Document], host_types: dict[str, object], prepared: dict[str, Prepared],
    collected: dict[str, Snapshot], installed: dict[str, list[str]], *, yes: bool, jobs: int,
) -> set[str]:
    """One ask-then-install round over `docs` (serial asks, then parallel installs + re-collects).

    Returns the hosts whose install and re-collect both succeeded -- the only ones worth asking again.
    """
    to_run: dict[str, tuple[str, list[str]]] = {}
    for doc in docs:
        host = doc.name
        if host not in collected or host_types[host].name.startswith("unifi-"):
            continue
        decision = _tools_ask(ctx, doc, host_types[host], collected[host], installed[host], yes)
        if decision is not None:
            to_run[host] = decision
    if not to_run:
        return set()

    def work(host: str, log: HostLog):
        script, tools = to_run[host]
        result = prepared[host].runner.run(script, timeout=600)
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
            return ("failed", tail[0])
        return ("ok", collect(prepared[host].runner, host), tools)

    succeeded: set[str] = set()

    def on_done(outcome: Outcome) -> None:
        for text, fg in outcome.log.lines:
            typer.secho(ACTIVE.mask(text), fg=fg)
        if outcome.status == "error":
            typer.secho(ACTIVE.mask(f"{outcome.host}: {outcome.error}"), fg="yellow")
            collected.pop(outcome.host, None)  # a real failure here drops the host, same as any other phase
            return
        if outcome.status == "not-started":
            collected.pop(outcome.host, None)
            return
        kind = outcome.value[0]
        if kind == "failed":
            tools = to_run[outcome.host][1]
            typer.secho(
                ACTIVE.mask(f"{outcome.host}: installing {', '.join(tools)} failed: {outcome.value[1]}"), fg="yellow"
            )
            return
        _, new_snapshot, tools = outcome.value
        collected[outcome.host] = new_snapshot
        installed[outcome.host] += tools
        succeeded.add(outcome.host)
        typer.echo(ACTIVE.mask(f"{outcome.host}: installed {', '.join(tools)}"))

    run_parallel(list(to_run), work, jobs=jobs, on_done=on_done)
    return succeeded


def _guest_command(node: str, guest: dict) -> str:
    kind = "lxc" if guest.get("type") == "lxc" else "vm"
    return f"bastet add host {shlex.quote(str(guest['name']))} --type {kind} --on {shlex.quote(node)}"


def _offer_guests(ctx: Context, found: list[tuple[str, dict]], yes: bool, facts_acc: FactsAcc) -> list:
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
            draft = new_host(ctx.inventory, ctx.types, name, kind, on=node, ip=ip, address=address)
        except BastetError as exc:
            typer.secho(f"  skipped {name}: {exc}", fg="yellow")
            continue
        drafts.append(draft.change)
        # vmid is a fact, not something to set on the host note: it goes into the new guest's facts
        # note, via the same accumulator as every other facts-note source this run.
        _merge_facts(facts_acc, ctx.inventory, name, {"vmid": g["vmid"]})
        if not address and ip == "dhcp":
            typer.secho(f"  {name}: no address known; set address: (a DNS name or IP) before gathering it", fg="yellow")
    return drafts


def _gather(
    hosts: list[str] | None, accept_new_hostkey: bool, yes: bool, jobs: int | None,
    exclude: list[str] | None = None, *, ctx: Context | None = None, finish_now: bool = True,
) -> tuple[Context, str, dict[str, list[str]], dict[str, list[str]]] | None:
    """Gather facts and write them, after showing the diff.

    With `finish_now` (the default), commits and pushes this gather's own changes together with the
    regenerated notes, in one commit, and returns None. With `finish_now=False` (used by `run -g -a`/
    `-g -c`), writes but doesn't commit -- the caller folds this gather's context, commit message and
    warnings/drift into its own `finish`, so the whole run becomes one commit.
    """
    ctx = ctx or load_context()
    run_jobs = resolve_jobs(jobs, ctx.config)
    print_problems(ctx)
    inv = ctx.inventory
    docs = select_hosts(inv, ctx.types, hosts or [], exclude or [])
    if not hosts:
        kept = []
        for doc in docs:
            if doc.data.get("gather") is False:
                typer.echo(f"{doc.name}: skipped (gather: false)")
            else:
                kept.append(doc)
        docs = kept
    if not docs:
        typer.echo("No hosts yet. Add one with `bastet add host`.")
        return

    first_gather = {doc.name for doc in docs if inv.facts.get(doc.name.lower()) is None}
    gathered_at = _now()
    changes, notes, gathered = [], [], []
    host_warnings: dict[str, list[str]] = {}
    found_guests: list[tuple[str, dict]] = []
    guest_drift_by_host: dict[str, list[str]] = {}
    run_state = RunState()
    unifi_devices: dict = {}
    facts_acc: FactsAcc = {}  # one accumulator per facts note this run; see FactsAcc
    with tempfile.TemporaryDirectory(prefix="bastet-") as tmp:
        tmp_path = Path(tmp)

        # Connect, serially, in inventory order -- pinning keys and logging in may ask.
        host_types: dict[str, object] = {}
        prepared: dict[str, Prepared] = {}
        live_docs: list[Document] = []
        for doc in docs:
            typer.echo(f"{doc.name}: gathering…")
            host_type = ctx.types.get(str(doc.data.get("type")), ctx.types["unknown"])
            host_types[doc.name] = host_type
            try:
                prepared[doc.name] = _prepare(ctx, doc, host_type, tmp_path, yes=yes, accept=accept_new_hostkey)
                live_docs.append(doc)
            except BastetError as exc:
                typer.secho(f"{doc.name}: {exc}", fg="yellow")
            except Exception as exc:  # one host's surprise must not lose the others' results
                typer.secho(f"{doc.name}: unexpected error: {exc.__class__.__name__}: {exc}", fg="yellow")

        # Collect, in parallel.
        collected: dict[str, object] = {}
        installed: dict[str, list[str]] = {}

        def collect_work(host: str, log: HostLog):
            return _collect_one(prepared[host], host)

        def on_collect_done(outcome: Outcome) -> None:
            _echo_outcome(outcome, "collected")

        outcomes = run_parallel(
            [d.name for d in live_docs], collect_work, jobs=run_jobs, on_done=on_collect_done
        )
        for outcome in outcomes:
            if outcome.status == "done":
                collected[outcome.host] = outcome.value
                installed[outcome.host] = []

        # Tools: ask serially (inventory order), then install + re-collect in parallel.
        # A second round only revisits hosts whose round-1 install and re-collect both succeeded.
        round1 = _tools_round(
            ctx, live_docs, host_types, prepared, collected, installed, yes=yes, jobs=run_jobs
        )
        if round1:
            _tools_round(
                ctx, [d for d in live_docs if d.name in round1], host_types, prepared, collected, installed,
                yes=yes, jobs=run_jobs,
            )

        # Plan and write, serially, in inventory order -- not thread-safe.
        for doc in live_docs:
            if doc.name not in collected:
                continue  # already reported, in phase 2 or 3
            host_type = host_types[doc.name]
            network_notes: list[tuple[str, str]] = []
            hostkey = prepared[doc.name].hostkey
            try:
                if host_type.name.startswith("unifi-"):
                    raw = collected[doc.name]
                    device = parse_mca(raw)
                    taken = gathered_at
                    snapshot = Snapshot(doc.name, "ssh", taken,
                                        {"mca_dump": ProbeResult(0, json.dumps(redact(json.loads(raw)), indent=1))})
                    save_snapshot(snapshot, data_dir())
                    unifi_devices[doc.name] = (host_type.name, device)
                    extracted = Extracted(facts=device_facts(device))
                    view = HardwareView(items=[machine_item(doc.name, host_type.name, device)])
                    if host_type.name == "unifi-gateway" and (nets := lab_networks(inv)):
                        network_notes = compare_networks(nets, device.networks)
                else:
                    snapshot = collected[doc.name]
                    save_snapshot(snapshot, data_dir())
                    extracted = extract(snapshot.results)
                    tools = sorted(set(host_data(ctx.inventory, doc, ctx.types).get("bastet_tools") or []) | set(installed[doc.name]))
                    if tools:
                        extracted.facts["bastet_tools"] = tools
                    view = observe_hardware(doc.name, snapshot.results, extracted) if host_type.physical else None
                    if view is not None and view.pools:
                        extracted.facts["pools"] = view.pools
                update = plan_facts(
                    doc, extracted, host_type, ctx.inventory, hostkey=hostkey, gathered=gathered_at, types=ctx.types,
                    existing=_facts_baseline(ctx.inventory, facts_acc, doc.name),
                )
                _set_facts(facts_acc, doc.name, update.facts)
                hw_changes, hw_notes, hw_touched = (
                    plan_hardware(inv, doc, view, run=run_state, gathered=gathered_at) if view else ([], [], False)
                )
            except BastetError as exc:
                typer.secho(f"{doc.name}: {exc}", fg="yellow")
                continue
            except Exception as exc:  # one host's surprise must not lose the others' results
                typer.secho(f"{doc.name}: unexpected error: {exc.__class__.__name__}: {exc}", fg="yellow")
                continue
            for probe in extracted.missing_required:
                notes.append(Note(doc.name, "warn", f"required probe '{probe}' failed or its tool is missing"))
            notes.extend(update.notes)
            notes.extend(Note(doc.name, severity, message) for severity, message in network_notes)
            notes.extend(hw_notes)
            privilege = snapshot.results.get("privilege")
            if privilege is not None and privilege.output.strip() == "none":
                notes.append(Note(doc.name, "warn", "root-only facts skipped (no sudo): machine serial, DIMMs, BIOS, drive health, BMC, guests"))
            node_names = {doc.name.lower(), str(extracted.facts.get("hostname", "")).lower()}
            here = [g for g in (view.guests if view else []) if str(g.get("node", "")).lower() in node_names]
            drift, vmid_updates = guest_drift(
                inv, doc, here, ctx.types, facts_for=lambda name: _facts_baseline(ctx.inventory, facts_acc, name)
            )
            for guest_name, items in drift.items():
                guest_drift_by_host[guest_name] = items
                notes.extend(Note(guest_name, "warn", f"drift — {item}") for item in items)
                # Drift is stored in the guest's own facts note, cleared the moment the node that
                # observes it agrees again -- so this guest needs an accumulator entry (even an
                # unchanged one) whether or not it was directly gathered this run.
                _merge_facts(facts_acc, ctx.inventory, guest_name, {})
            for guest_name, vmid in vmid_updates.items():
                _merge_facts(facts_acc, ctx.inventory, guest_name, {"vmid": vmid})
            known_vmids = {
                str(v) for d in inv.of_kind("host") if (v := host_data(ctx.inventory, d, ctx.types).get("vmid")) is not None
            }
            for guest in view.guests if view else []:
                if str(guest.get("node", "")).lower() not in node_names:
                    continue
                if guest.get("name") and inv.get(str(guest["name"])) is None and str(guest.get("vmid")) not in known_vmids:
                    found_guests.append((doc.name, guest))
            host_warnings[doc.name] = [n.message for n in notes if n.host == doc.name and n.severity == "warn"]
            if update.change is None and not hw_changes and not hw_touched:
                typer.echo(f"{doc.name}: up to date")
            else:
                changes.extend(hw_changes)
                gathered.append(doc.name)

    linked: list[str] = []
    if unifi_devices:
        proposals, cable_notes = propose_links(inv, ctx.types, unifi_devices)
        notes.extend(Note(host, "warn", message) for host, message in cable_notes)
        gathered_device_names = {d.lower() for d in unifi_devices}
        proposed_hosts = _group(proposals)
        proposed_host_names = {h.lower() for h in proposed_hosts}
        for proposal_host, links in proposed_hosts.items():
            try:
                target = inv.get(proposal_host)
                if target is None:
                    continue
                # Observed links go to the facts note (the host's, or -- for a BMC -- the machine's own
                # hardware note), tagged with which device saw them, so regathering that device replaces
                # only its own entries (declared `links` on the host/hardware note still wins for the
                # same port -- host_data/hardware_data merge that in for readers).
                is_hardware = target.data.get("bastet") == "hardware"
                baseline = (
                    hw_baseline(inv, run_state, target.name) if is_hardware
                    else _facts_baseline(ctx.inventory, facts_acc, target.name)
                )
                _, conflicts = merge_links(target.data.get("links"), links)
                notes.extend(Note(target.name, "warn", f"link {c}; left as written") for c in conflicts)
                prior_links = baseline.get("links") if isinstance(baseline.get("links"), list) else []
                prior_ports = {str(e.get("port")) for e in prior_links if isinstance(e, dict)}
                tagged = [{**link, "seen_by": link_target(link["to"]) or str(link["to"])} for link in links]
                new_links = _prune_seen_by(prior_links, gathered_device_names) + tagged
                if new_links != prior_links:
                    linked.append(target.name)
                if is_hardware:
                    set_hw_facts(run_state, target.name, {**baseline, "links": new_links})
                else:
                    _merge_facts(facts_acc, ctx.inventory, target.name, {"links": new_links})
                notes.extend(Note(target.name, "info", f"link {link['port']} → {link['to']} port {link['to_port']}")
                             for link in links if str(link["port"]) not in prior_ports)
            except Exception as exc:  # one host's links must not lose the rest of the run
                typer.secho(f"{proposal_host}: links not updated: {exc.__class__.__name__}: {exc}", fg="yellow")
                continue

        # Unplugged: a host no device proposes a link for any more, but whose facts note still carries
        # one seen by a device gathered this run. That device's fresh view says nothing is there now.
        for doc in inv.of_kind("host"):
            if doc.name.lower() in proposed_host_names or str(doc.data.get("type", "")).startswith("unifi-"):
                continue
            baseline = _facts_baseline(ctx.inventory, facts_acc, doc.name)
            prior_links = baseline.get("links") if isinstance(baseline.get("links"), list) else []
            kept = _prune_seen_by(prior_links, gathered_device_names)
            if kept != prior_links:
                _merge_facts(facts_acc, ctx.inventory, doc.name, {"links": kept})
                linked.append(doc.name)

    # Hardware recorded as installed somewhere this run checked, but never seen there: now that every
    # host has been planned (and any within-run move has updated run_state.hw_facts), this can't mistake
    # a move for a disappearance.
    notes.extend(missing_hardware(inv, run_state, gathered_at))

    for note in notes:
        mark = "⚠" if note.severity == "warn" else "·"
        typer.secho(f"{mark} {note.host}: {note.message}", fg="yellow" if note.severity == "warn" else None)
    added = _offer_guests(ctx, found_guests, yes, facts_acc) if found_guests else []
    changes.extend(added)
    for name, facts in facts_acc.values():  # exactly one Change per facts note, built once everything merged
        change = facts_change(
            ctx.inventory.root, name, facts, gathered_at,
            warnings=host_warnings.get(name), drift=guest_drift_by_host.get(name),
        )
        if change is not None:
            changes.append(change)
    for name, facts in run_state.hw_facts.values():  # exactly one Change per hardware item's facts note
        change = hardware_facts_change(ctx.inventory.root, name, facts, gathered_at)
        if change is not None:
            changes.append(change)
    message = f"gather: {', '.join(gathered)}" if gathered else "gather"
    if linked:
        message += f"; links: {', '.join(linked)}"
    if added:
        message += f"; add {len(added)} guest{'s' if len(added) != 1 else ''}"
    if changes and not write_with_confirmation(ctx, [*changes, *lab_embed_changes(inv)], yes):
        if finish_now:
            return None
        return ctx, message, host_warnings, guest_drift_by_host
    if finish_now:
        finish(ctx, message, warnings=host_warnings, drift=guest_drift_by_host)
        for name in gathered:
            if name in first_gather:
                next_hint(f"bastet add role --to {name}", yes=yes)
        return None
    return ctx, message, host_warnings, guest_drift_by_host
