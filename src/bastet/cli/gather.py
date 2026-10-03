import datetime as dt
import getpass
import json
import ipaddress
import os
import shlex
import subprocess
import tempfile
from pathlib import Path

import typer

from bastet.cli.common import Context, handles_errors, load_context, refresh_generated, scan_first, ssh_ports, write_with_confirmation
from bastet.core.guests import guest_drift
from bastet.core.render import lab_embed_changes
from bastet.core.scaffold import new_host
from bastet.core.tools import install_script, needed_tools
from bastet.core import hostkeys
from bastet.core.bootstrap import setup_command
from bastet.core.cabling import merge_links, propose_links
from bastet.core.networks import compare_networks, lab_networks
from bastet.core.changes import Change
from bastet.core.collect import ProbeResult, Snapshot, collect, save_snapshot
from bastet.core.config import data_dir
from bastet.core.errors import AuthFailed, BastetError
from bastet.core.facts import Extracted, extract
from bastet.core.frontmatter import Document, parse_document, set_keys
from bastet.core.unifi import device_facts, machine_item, parse_mca, redact
from bastet.core.gatherplan import Note, plan_update
from bastet.core.hardware import HardwareView, RunState, observe_hardware, plan_hardware
from bastet.core.remote import LocalRunner, SshRunner, SshTarget, run_interactive


def local_runner() -> LocalRunner:
    return LocalRunner()


def ssh_runner(target: SshTarget) -> SshRunner:
    return SshRunner(target)


def scan_keys(address: str, recorded: str | None = None, port: int = 22) -> list[hostkeys.HostKey]:
    return hostkeys.scan(address, recorded=recorded, port=port)


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


def _pin(ctx: Context, doc: Document, tmp: Path, *, yes: bool, accept: bool,
         ports: list[int] | None = None) -> tuple[str, Path, str, int]:
    """Scan, check and pin the host key (first contact asks); returns address, known_hosts path, recorded key, port."""
    ports = ports or [22]
    address = doc.data.get("address") or _fixed_ip(doc.data.get("ip"))
    if not address:
        raise BastetError("no address to connect to; set `address:` (e.g. laptop.local) or a fixed `ip:`", file=doc.path)
    recorded = doc.data.get("ssh_host_key")
    keys, port = scan_first(scan_keys, str(address), str(recorded) if recorded else None, ports)
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
    known = hostkeys.write_known_hosts(trusted, str(address), port, tmp / doc.name)
    return str(address), known, hostkey, port


def _gather_unifi(ctx: Context, doc: Document, tmp: Path, *, yes: bool, accept: bool) -> tuple[str, str]:
    """UniFi devices: one read-only `mca-dump` over the user's own SSH login (UniFi's device SSH account)."""
    address, known, hostkey, _ = _pin(ctx, doc, tmp, yes=yes, accept=accept)
    user = ctx.config.ssh.bootstrap_user or getpass.getuser()
    res = ssh_runner(SshTarget(address, user, None, known)).run("mca-dump\n", timeout=60)
    if res.returncode != 0 or not res.stdout.strip():
        raise BastetError("mca-dump failed or isn't there; is this a UniFi device, and does the device SSH login work?")
    return res.stdout, hostkey


def _group(proposals) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for p in proposals:
        out.setdefault(p.host, []).append(p.link)
    return out


def _collect(ctx: Context, doc: Document, tmp: Path, *, yes: bool, accept: bool) -> tuple[Snapshot, str | None, object]:
    if doc.data.get("connection") == "local":
        if not yes and os.geteuid() != 0:
            sudo_validate()
        runner = local_runner()
        return collect(runner, doc.name), None, runner
    address, known, hostkey, port = _pin(ctx, doc, tmp, yes=yes, accept=accept, ports=ssh_ports(ctx, doc))
    key = ctx.config.ssh.key
    if key is not None:
        try:
            runner = ssh_runner(SshTarget(str(address), "bastet", key, known, port=port))
            return collect(runner, doc.name), hostkey, runner
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
                return collect(runner, doc.name), hostkey, runner
            except AuthFailed:
                typer.secho(f"{doc.name}: bastet user set up, but its login was refused; continuing as {user}", fg="yellow")
        else:
            typer.secho(f"{doc.name}: setting up the bastet user failed; continuing as {user}", fg="yellow")
    runner = ssh_runner(own)
    return collect(runner, doc.name), hostkey, runner


def _maybe_install_tools(ctx: Context, doc: Document, host_type, snapshot: Snapshot, runner, yes: bool):
    """Install useful gather tools the host is missing (per config and host), then collect again."""
    installed: list[str] = []
    mode = ctx.config.gather.install_tools
    if mode == "never" or doc.data.get("install_tools") is False or (mode == "ask" and yes):
        return snapshot, installed
    for _ in range(2):  # a second round catches tools only found to be useful after the first (e.g. a BMC)
        tools = [t for t in needed_tools(snapshot.results, host_type) if t not in installed]
        if not tools:
            break
        manager = (snapshot.results.get("pkg_mgr").output.strip() if snapshot.results.get("pkg_mgr") else "") or None
        script = install_script(manager, tools)
        if script is None:
            typer.secho(f"{doc.name}: missing {', '.join(tools)}, but no supported package manager was found", fg="yellow")
            break
        if mode == "ask" and not typer.confirm(
            f"{doc.name}: install {', '.join(tools)} for fuller hardware info?", default=True
        ):
            break
        result = runner.run(script, timeout=600)
        if result.returncode != 0:
            tail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
            typer.secho(f"{doc.name}: installing {', '.join(tools)} failed: {tail[0]}", fg="yellow")
            break
        installed += tools
        typer.echo(f"{doc.name}: installed {', '.join(tools)}")
        snapshot = collect(runner, doc.name)
    return snapshot, installed


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
        docs = []
        for doc in inv.of_kind("host"):
            if doc.data.get("gather") is False:
                typer.echo(f"{doc.name}: skipped (gather: false)")
            else:
                docs.append(doc)
    if not docs:
        typer.echo("No hosts yet. Add one with `bastet add host`.")
        return

    take_fields = set(take) | ({"ssh_host_key"} if accept_new_hostkey else set())
    changes, notes, gathered = [], [], []
    host_warnings: dict[str, list[str]] = {}
    found_guests: list[tuple[str, dict]] = []
    guest_drift_by_host: dict[str, list[str]] = {}
    run_state = RunState()
    unifi_devices: dict = {}
    with tempfile.TemporaryDirectory(prefix="bastet-") as tmp:
        for doc in docs:
            typer.echo(f"{doc.name}: gathering…")
            network_notes: list[tuple[str, str]] = []
            try:
                host_type = ctx.types.get(str(doc.data.get("type")), ctx.types["unknown"])
                if host_type.name.startswith("unifi-"):
                    raw, hostkey = _gather_unifi(ctx, doc, Path(tmp), yes=yes, accept=accept_new_hostkey)
                    device = parse_mca(raw)
                    taken = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                    snapshot = Snapshot(doc.name, "ssh", taken,
                                        {"mca_dump": ProbeResult(0, json.dumps(redact(json.loads(raw)), indent=1))})
                    save_snapshot(snapshot, data_dir())
                    unifi_devices[doc.name] = (host_type.name, device)
                    extracted = Extracted(facts=device_facts(device))
                    view = HardwareView(items=[machine_item(doc.name, host_type.name, device)])
                    if host_type.name == "unifi-gateway" and (nets := lab_networks(inv)):
                        network_notes = compare_networks(nets, device.networks)
                else:
                    snapshot, hostkey, runner = _collect(ctx, doc, Path(tmp), yes=yes, accept=accept_new_hostkey)
                    snapshot, installed = _maybe_install_tools(ctx, doc, host_type, snapshot, runner, yes)
                    save_snapshot(snapshot, data_dir())
                    extracted = extract(snapshot.results)
                    tools = sorted(set(doc.data.get("bastet_tools") or []) | set(installed))
                    if tools:
                        extracted.facts["bastet_tools"] = tools
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
            notes.extend(Note(doc.name, severity, message) for severity, message in network_notes)
            notes.extend(hw_notes)
            privilege = snapshot.results.get("privilege")
            if privilege is not None and privilege.output.strip() == "none":
                notes.append(Note(doc.name, "warn", "root-only facts skipped (no sudo): machine serial, DIMMs, BIOS, drive health, BMC, guests"))
            node_names = {doc.name.lower(), str(extracted.facts.get("hostname", "")).lower()}
            here = [g for g in (view.guests if view else []) if str(g.get("node", "")).lower() in node_names]
            drift, vmid_changes = guest_drift(inv, doc, here)
            for guest_name, items in drift.items():
                guest_drift_by_host[guest_name] = items
                notes.extend(Note(guest_name, "warn", f"drift — {item}") for item in items)
            changes.extend(vmid_changes)
            for guest in view.guests if view else []:
                if str(guest.get("node", "")).lower() not in node_names:
                    continue
                known_vmid = str(guest.get("vmid")) in {str(d.data.get("vmid")) for d in inv.of_kind("host")}
                if guest.get("name") and inv.get(str(guest["name"])) is None and not known_vmid:
                    found_guests.append((doc.name, guest))
            host_warnings[doc.name] = [n.message for n in notes if n.host == doc.name and n.severity == "warn"]
            host_changes = ([update.change] if update.change else []) + hw_changes
            if not host_changes:
                typer.echo(f"{doc.name}: up to date")
            else:
                changes.extend(host_changes)
                gathered.append(doc.name)

    linked: list[str] = []
    if unifi_devices:
        by_path = {c.path: c for c in changes}
        proposals, cable_notes = propose_links(inv, unifi_devices)
        notes.extend(Note(host, "warn", message) for host, message in cable_notes)
        for proposal_host, links in _group(proposals).items():
            try:
                target = inv.get(proposal_host)
                if target is None:
                    continue
                pending = by_path.get(target.path)
                text = pending.after if pending is not None else target.path.read_text(encoding="utf-8")
                existing = parse_document(text, target.path).data.get("links")
                merged, conflicts = merge_links(existing, links)
                notes.extend(Note(target.name, "warn", f"link {c}; left as written") for c in conflicts)
                if merged is None:
                    continue
                after = set_keys(text, {"links": merged}, target.path)
            except Exception as exc:  # one host's links must not lose the rest of the run
                typer.secho(f"{proposal_host}: links not updated: {exc.__class__.__name__}: {exc}", fg="yellow")
                continue
            if pending is not None:
                pending.after = after
            else:
                by_path[target.path] = Change(target.path, text, after)
                changes.append(by_path[target.path])
                linked.append(target.name)
            before = existing if isinstance(existing, list) else []
            notes.extend(Note(target.name, "info", f"link {link['port']} → {link['to']} port {link['to_port']}")
                         for link in merged[len(before):])

    for note in notes:
        mark = "⚠" if note.severity == "warn" else "·"
        typer.secho(f"{mark} {note.host}: {note.message}", fg="yellow" if note.severity == "warn" else None)
    added = _offer_guests(ctx, found_guests, yes) if found_guests else []
    changes.extend(added)
    if changes:
        message = f"gather: {', '.join(gathered)}" if gathered else "gather"
        if linked:
            message += f"; links: {', '.join(linked)}"
        if added:
            message += f"; add {len(added)} guest{'s' if len(added) != 1 else ''}"
        if not write_with_confirmation(ctx, [*changes, *lab_embed_changes(inv)], message, yes):
            return
    refresh_generated(ctx, warnings=host_warnings, drift=guest_drift_by_host)
