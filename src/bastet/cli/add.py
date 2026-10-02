import socket

import typer

from bastet.cli.common import handles_errors, load_context, refresh_generated, write_with_confirmation
from bastet.core.render import lab_embed_changes
from bastet.core.changes import Change
from bastet.core.errors import BastetError
from bastet.core.frontmatter import new_document
from bastet.core.links import make_link
from bastet.core.views import ROLES_SECTION, has_roles_section
from bastet.roles.contract import load_roles
from bastet.core.inventory import HARDWARE_STATUSES
from bastet.core.scaffold import new_hardware, new_host, suggested_ip

add_app = typer.Typer(no_args_is_help=True, help="Add a host or hardware to the inventory. Asks for anything not given.")

HARDWARE_CATEGORIES = ("drive", "nic", "gpu", "hba", "transceiver", "cpu", "memory", "psu", "usb", "server", "other")


def _choose(label: str, options: list[tuple[str, str]], *, default: str | None = None, allow_blank: bool = False) -> str | None:
    """Numbered list; accepts a number or the value itself (any case)."""
    typer.echo(f"{label}:")
    for i, (value, description) in enumerate(options, 1):
        typer.echo(f"  {i}. {value}" + (f"  - {description}" if description else ""))
    prompt_default = default if default is not None else ("" if allow_blank else None)
    while True:
        answer = typer.prompt(
            "Choice" + (" (blank to skip)" if allow_blank else ""),
            default=prompt_default,
            show_default=bool(default),
        ).strip()
        if not answer and allow_blank:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        for value, _ in options:
            if value.lower() == answer.lower():
                return value
        typer.echo(f"  '{answer}' isn't one of the choices.")


def _optional(prompt: str) -> str | None:
    return typer.prompt(f"{prompt} (blank to skip)", default="", show_default=False).strip() or None


@add_app.command("host")
@handles_errors
def add_host(
    name: str | None = typer.Argument(None, help="Host name (asked if not given)."),
    type_: str | None = typer.Option(None, "--type", help="Host type, e.g. vps, proxmox-node, lxc, laptop."),
    ip: str | None = typer.Option(None, "--ip", help="Fixed address, or 'dhcp'."),
    on: str | None = typer.Option(None, "--on", help="Parent host for an LXC or VM."),
    network: str | None = typer.Option(None, "--network", help="Lab network; suggests the next free address."),
    location: str | None = typer.Option(None, "--location"),
    provider: str | None = typer.Option(None, "--provider"),
    address: str | None = typer.Option(None, "--address", help="Name to connect to when the IP isn't fixed (e.g. laptop.local)."),
    local: bool | None = typer.Option(None, "--local/--not-local", help="This is the computer Bastet runs on."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask; write and commit."),
) -> None:
    """Write a minimal host file, asking for anything not given."""
    ctx = load_context()
    inv = ctx.inventory
    asking = not yes
    if name is None:
        if not asking:
            raise BastetError("a host name is required with --yes")
        name = typer.prompt("Host name").strip()
    if type_ is None:
        if not asking:
            raise BastetError("--type is required with --yes")
        types = sorted(ctx.types.values(), key=lambda t: t.name)
        type_ = _choose("Host type", [(t.name, t.description) for t in types])
    minimal = ctx.types[type_].minimal if type_ in ctx.types else []

    if asking:
        if "provider" in minimal and provider is None:
            provider = typer.prompt("Provider (e.g. linode)").strip()
        if "runs_on" in minimal and on is None:
            hosts = [(d.name, str(d.data.get("type", ""))) for d in inv.of_kind("host")]
            if not hosts:
                raise BastetError(f"a {type_} runs on another host; add that host first")
            on = _choose("Runs on", hosts)
        networks = (inv.lab.data.get("networks") or {}) if inv.lab else {}
        if type_ in ("lxc", "vm") and network is None and ip is None and networks:
            network = _choose("Network", [(n, str((v or {}).get("cidr", ""))) for n, v in networks.items()], allow_blank=True)
        if ip is None and type_ != "unknown":
            default = suggested_ip(inv, network) if network else None
            if "ip" in minimal:
                ip = typer.prompt("IP address", default=default, show_default=bool(default)).strip()
            else:
                ip = typer.prompt("IP (fixed address, 'dhcp', or blank)", default="", show_default=False).strip() or None
        if ip and ip.lower() == "dhcp" and address is None:
            address = typer.prompt("Name to reach it by", default=f"{name}.local").strip()
        if type_ == "laptop" and local is None:
            here = socket.gethostname().split(".")[0].lower() == name.lower()
            local = typer.confirm("Is this the computer you're running Bastet on?", default=here)
        if location is None:
            locations = [(d.name, "") for d in inv.of_kind("location")]
            if locations:
                location = _choose("Location", locations, allow_blank=True)

    draft = new_host(
        inv, ctx.types, name, type_, ip=ip, on=on, network=network, location=location,
        provider=provider, address=address, connection="local" if local else None,
    )
    if draft.suggested_ip:
        typer.echo(f"Suggested address: {draft.suggested_ip} (next free in {network})")
    if write_with_confirmation(ctx, [draft.change, *lab_embed_changes(inv)], f"add host {name}", yes):
        refresh_generated(ctx)


@add_app.command("hardware")
@handles_errors
def add_hardware(
    name: str | None = typer.Argument(None, help="Hardware name (asked if not given)."),
    category: str | None = typer.Option(None, "--category", help="drive, nic, gpu, hba, server, psu, ..."),
    model: str | None = typer.Option(None, "--model"),
    serial: str | None = typer.Option(None, "--serial"),
    size: str | None = typer.Option(None, "--size"),
    installed_in: str | None = typer.Option(None, "--in", help="Host it's installed in."),
    location: str | None = typer.Option(None, "--location"),
    status: str | None = typer.Option(None, "--status"),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Write a hardware file (e.g. a spare drive), asking for anything not given."""
    ctx = load_context()
    inv = ctx.inventory
    asking = not yes
    if name is None:
        if not asking:
            raise BastetError("a hardware name is required with --yes")
        name = typer.prompt("Hardware name (e.g. 'WD Red 4TB WX12…')").strip()
    if category is None:
        if not asking:
            raise BastetError("--category is required with --yes")
        category = _choose("Category", [(c, "") for c in HARDWARE_CATEGORIES])
    if asking:
        model = model if model is not None else _optional("Model")
        serial = serial if serial is not None else _optional("Serial")
        size = size if size is not None else _optional("Size (e.g. 4 TB)")
        if installed_in is None and location is None:
            hosts = [(d.name, str(d.data.get("type", ""))) for d in inv.of_kind("host")]
            if hosts:
                installed_in = _choose("Installed in (blank if not installed)", hosts, allow_blank=True)
            if installed_in is None:
                locations = [(d.name, "") for d in inv.of_kind("location")]
                if locations:
                    location = _choose("Location", locations, allow_blank=True)
        if status is None:
            status = _choose(
                "Status", [(s, "") for s in HARDWARE_STATUSES], default="in-service" if installed_in else "spare"
            )
    change = new_hardware(
        inv, name, category, model=model, serial=serial, size=size,
        installed_in=installed_in, location=location, status=status,
    )
    if write_with_confirmation(ctx, [change, *lab_embed_changes(inv)], f"add hardware {name}", yes):
        refresh_generated(ctx)


def _choose_many(label: str, options: list[tuple[str, str]]) -> list[str]:
    """Numbered list; several picks by number or name, comma- or space-separated."""
    typer.echo(f"{label}:")
    for i, (value, description) in enumerate(options, 1):
        typer.echo(f"  {i}. {value}" + (f"  - {description}" if description else ""))
    values = {v.lower(): v for v, _ in options}
    while True:
        answer = typer.prompt("Choice (one or more, e.g. 1,3)").strip()
        picked, bad = [], []
        for word in answer.replace(",", " ").split():
            if word.isdigit() and 1 <= int(word) <= len(options):
                picked.append(options[int(word) - 1][0])
            elif word.lower() in values:
                picked.append(values[word.lower()])
            else:
                bad.append(word)
        if picked and not bad:
            return list(dict.fromkeys(picked))
        typer.echo(f"  '{' '.join(bad) or answer}' isn't one of the choices.")


def _role_targets(inv) -> list[tuple[str, str]]:
    out = [("lab", "every host")]
    for g in inv.of_kind("group"):
        rule = g.data.get("match") if isinstance(g.data.get("match"), dict) else {}
        out.append((g.name, f"every {rule['os']} host" if rule.get("os") else "group"))
    out += [(h.name, str(h.data.get("type") or "host")) for h in inv.of_kind("host")]
    return out


@add_app.command("role")
@handles_errors
def add_role(
    roles: list[str] | None = typer.Argument(None, help="Roles to add (offered as a list if not given)."),
    to: str | None = typer.Option(None, "--to", help="A host, a group, or `lab` for every host (asked if not given)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Don't ask; write and commit."),
) -> None:
    """Write role files for a host, a group or the whole lab, after showing the diff."""
    ctx = load_context()
    known = load_roles()
    names = list(roles or [])
    targets = {name.lower() for name, _ in _role_targets(ctx.inventory)}
    if to is None and len(names) >= 2 and names[-1].lower() in targets:
        if names[-1] in known:
            typer.secho(f"'{names[-1]}' is both a role and a target; treating it as a role (use --to for the target)",
                        fg="yellow")
        else:
            to = names.pop()  # the old form: bastet add role <role> <target>
    if yes and (not names or to is None):
        raise BastetError("name the roles and --to when using -y (e.g. bastet add role base --to lab -y)")
    if not names:
        names = _choose_many("Roles", [(n, r.description.split(". ")[0].rstrip(".")) for n, r in sorted(known.items())])
    for role in names:
        if role not in known:
            raise BastetError(f"unknown role {role!r} (roles: {', '.join(sorted(known))})")
    if to is None:
        to = _choose("Add to", _role_targets(ctx.inventory))
    if to == "lab":
        doc = ctx.inventory.lab
        if doc is None:
            raise BastetError("no lab file yet; run `bastet init`")
        folder = ctx.root / "_roles" / "lab"
    else:
        doc = ctx.inventory.get(to)
        if doc is None or doc.data.get("bastet") not in ("host", "group"):
            raise BastetError(f"no host or group named '{to}'")
        folder = ctx.root / "_roles" / ("hosts" if doc.data["bastet"] == "host" else "groups") / doc.name
    changes, added = [], []
    for role in names:
        path = folder / f"{role}.md"
        if path.exists():
            typer.secho(f"{doc.name} already has the {role} role ({path.relative_to(ctx.root)}); edit it in Obsidian",
                        fg="yellow")
            continue
        body = (f"# {role} for {doc.name}\n\nValues go in this note's properties (the frontmatter at the top), "
                f"not in the page text below.\n\n## Examples\n\n![[{role} role#Examples]]\n\n"
                f"## Options\n\n![[{role} role#Options]]\n")
        data = {"bastet": "role", "role": role, "applies_to": make_link(doc.name)}
        changes.append(Change(path, None, new_document(data, body)))
        added.append(role)
    if not changes:
        raise BastetError(f"{doc.name} already has {'that role' if len(names) == 1 else 'those roles'}; "
                          "it already exists, so edit it in Obsidian")
    if doc.data.get("bastet") in ("host", "group") and not has_roles_section(doc.body):
        text = doc.path.read_text(encoding="utf-8")
        changes.append(Change(doc.path, text, text.rstrip("\n") + "\n" + ROLES_SECTION))
    if write_with_confirmation(ctx, changes, f"add role {', '.join(added)} to {doc.name}", yes):
        refresh_generated(ctx)
