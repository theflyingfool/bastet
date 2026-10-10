import datetime as dt
import getpass
import subprocess
import sys
import tempfile
from pathlib import Path

import typer

from bastet.cli.common import Context, handles_errors, load_context, push_or_warn, refresh_only, next_hint
from bastet.core import hostkeys
from bastet.core.changes import Change, render_diff, write_changes
from bastet.core.config import config_path, data_dir, inventory_dir, load_config
from bastet.core.errors import BastetError
from bastet.core.factsnote import facts_change
from bastet.core.frontmatter import set_keys
from bastet.core.hostview import host_data
from bastet.core.initialize import (
    InitOptions, ProcResult, existing_recipients, generate_recovery_key, initialize, local_user_setup,
    real_runner, sshd_inactive_unit, sshd_ready,
)
from bastet.ui import out

_RECOVERY_WARNING = (
    "Recovery key: keep this offline. It's the only way back if this laptop is lost. It won't be shown again."
)


def _stdout_is_tty() -> bool:
    return sys.stdout.isatty()


def _runner(argv: list[str]) -> ProcResult:
    return real_runner(argv)


def _scan_local(address: str = "127.0.0.1", port: int = 22) -> list[hostkeys.HostKey]:
    return hostkeys.scan(address, port=port)


def _sudo_validate() -> bool:
    try:
        return subprocess.run(["sudo", "-v"]).returncode == 0
    except FileNotFoundError:
        return False


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _confirm_local_hostkey(ctx: Context, *, yes: bool) -> None:
    hosts = [d for d in ctx.inventory.of_kind("host") if d.data.get("connection") == "local"]
    if not hosts:
        out.echo("No local host in the inventory yet; `bastet gather` will pin its key once you add one.")
        return
    try:
        keys = _scan_local()
    except BastetError as exc:
        out.secho(f"Could not scan this machine's host key: {exc}", fg="yellow")
        return
    offered = hostkeys.record(hostkeys.preferred(keys))
    for doc in hosts:
        recorded = host_data(ctx.inventory, doc, ctx.types).get("ssh_host_key")
        status = hostkeys.check(recorded, keys)
        if status == "match":
            out.echo(f"{doc.name}: host key already set up")
            continue
        if recorded:
            out.secho(
                f"{doc.name}: a different host key is already recorded; run `bastet gather "
                "--accept-new-hostkey` if this machine was reinstalled", fg="yellow",
            )
            continue
        out.echo(f"{doc.name}: host key {offered}")
        if yes:
            out.echo(f"{doc.name}: run without -y to confirm the host key")
            continue
        if not typer.confirm("Trust this key?", default=False):
            out.echo(f"{doc.name}: host key not recorded")
            continue
        # The pin lives in the facts note, never the host note -- it isn't a gather, so the note's
        # own `gathered:` is kept as-is when there is one.
        existing_facts = ctx.inventory.facts_for(doc.name)
        facts_doc = ctx.inventory.facts.get(doc.name.lower())
        gathered = str(facts_doc.data.get("gathered")) if facts_doc is not None and facts_doc.data.get("gathered") else _now()
        change = facts_change(ctx.root, doc.name, {**existing_facts, "ssh_host_key": offered}, gathered)
        if change is not None:
            write_changes([change])
            if ctx.repo.is_repo():
                if ctx.repo.commit([change.path], f"init: pin {doc.name}'s host key"):
                    push_or_warn(ctx)
        out.echo(f"{doc.name}: host key recorded")


def _setup_this_machine(ctx: Context, public_key: Path, *, yes: bool) -> None:
    """Set up this computer as a Bastet host: the `bastet` user, passwordless sudo, its
    authorized_keys, an sshd check, and (once confirmed) its host key. Tty only, like the recovery
    key -- every step is idempotent, and nothing here ever edits sshd config."""
    if not _stdout_is_tty():
        out.echo("Not a terminal: run this in a terminal to set up this machine as a Bastet host.")
        return
    out.echo(
        "Setting up this machine as a Bastet host: a local 'bastet' user with passwordless sudo "
        "(root-equivalent; only Bastet's SSH key can log in as it). sudo will ask for your password."
    )
    if not _sudo_validate():
        out.secho("Could not get sudo; this machine was not set up as a Bastet host.", fg="yellow")
        return
    key = public_key.read_text(encoding="utf-8").strip()
    with tempfile.TemporaryDirectory(prefix="bastet-init-") as tmp:
        try:
            for action in local_user_setup(_runner, Path(tmp), key):
                out.echo(action)
        except BastetError as exc:
            out.secho(f"Setting up this machine failed: {exc}", fg="yellow")
            return
    ok, hint = sshd_ready(_runner, _scan_local)
    if not ok and not yes:
        unit = sshd_inactive_unit(_runner)
        if unit and typer.confirm(f"Start sshd now (systemctl enable --now {unit})?", default=False):
            res = _runner(["sudo", "-n", "systemctl", "enable", "--now", unit])
            if res.returncode != 0:
                out.secho(f"systemctl enable --now {unit} failed: {(res.stderr or res.stdout).strip()}", fg="yellow")
                return
            ok, hint = sshd_ready(_runner, _scan_local)
    if not ok:
        out.secho(hint, fg="yellow")
        return
    _confirm_local_hostkey(ctx, yes=yes)


def _your_pub_text(yes: bool) -> str | None:
    """The person's own SSH public key, to add as a recipient: `~/.ssh/id_ed25519.pub` if it exists, else asked
    for (skipped under `-y`)."""
    default_pub = Path.home() / ".ssh" / "id_ed25519.pub"
    if default_pub.is_file():
        return default_pub.read_text(encoding="utf-8").strip()
    if yes:
        return None
    answer = typer.prompt(
        "Path to your SSH public key, to add as a recipient (blank to skip)", default="", show_default=False
    )
    if not answer:
        return None
    path = Path(answer).expanduser()
    if not path.is_file():
        raise BastetError("SSH public key not found", file=path)
    return path.read_text(encoding="utf-8").strip()


def _plan_recipients(inventory_path: Path, yes: bool) -> tuple[list[str] | None, str | None]:
    """What `secrets.recipients` to add this run (`None` when they're already set), and the recovery
    private key to print once, if a diff was offered (or there was nothing to confirm) and accepted.

    The recovery key is the *only* copy of that identity; it's shown once, here, and never written to
    disk. Printing it anywhere other than an actual terminal (a log file, a CI pipe, a redirected
    output) would leave the only copy of a lab-recovery credential sitting in a file or a log forever,
    so when stdout isn't a terminal, no recipient (and so no recovery key) is created at all this run.
    """
    homelab_path = inventory_path / "Homelab.md"
    if existing_recipients(homelab_path):
        return None, None
    if not _stdout_is_tty():
        out.echo("Not a terminal: run `bastet init` in a terminal to create the recovery key.")
        return None, None
    recovery_private, recovery_public = generate_recovery_key()
    your_pub = _your_pub_text(yes)
    recipients = [recovery_public] + ([your_pub] if your_pub else [])
    if not homelab_path.is_file():
        return recipients, recovery_private
    before = homelab_path.read_text(encoding="utf-8")
    after = set_keys(before, {"secrets": {"recipients": recipients}}, homelab_path)
    out.echo("\nBastet will add to Homelab.md:")
    out.diff(render_diff(Change(homelab_path, before, after), inventory_path))
    if yes or typer.confirm("Add a recovery key and your SSH key as secrets.recipients?", default=True):
        return recipients, recovery_private
    return None, None


@handles_errors
def init(
    inventory: Path | None = typer.Option(None, "--inventory", help="Inventory directory."),
    remote: str | None = typer.Option(None, "--remote", help="Git remote URL for the inventory."),
    key: str | None = typer.Option(None, "--key", help="'new', or the path of an existing private key."),
    bootstrap_user: str | None = typer.Option(None, "--bootstrap-user", help="Your SSH login for setting up existing hosts."),
    lab_name: str | None = typer.Option(None, "--lab-name"),
    public_domain: str | None = typer.Option(None, "--public-domain"),
    internal_domain: str | None = typer.Option(None, "--internal-domain"),
    snippet: bool | None = typer.Option(None, "--snippet/--no-snippet", help="Install Bastet's Obsidian stylesheet."),
    manage_this_machine: bool | None = typer.Option(
        None, "--manage-this-machine/--no-manage-this-machine",
        help="Also manage this computer with Bastet (a local 'bastet' user with passwordless sudo; needs sshd).",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Take defaults for anything not given; don't ask."),
) -> None:
    """Set up config, Bastet's SSH key and the inventory. Safe to run again."""
    cfg_file = config_path()
    existing = load_config(cfg_file) if cfg_file.exists() else None

    def ask(value, prompt: str, default: str) -> str:
        if value is not None:
            return str(value)
        if yes:
            return default
        return typer.prompt(prompt, default=default, show_default=bool(default))

    if existing is not None:
        out.echo(f"Using {cfg_file} (edit it to change the inventory, remote, key or login).")
        inventory_path = inventory_dir(existing, data_dir())
        remote_url = existing.inventory.remote
        key_path = existing.ssh.key
        user = existing.ssh.bootstrap_user or getpass.getuser()
    else:
        inventory_path = Path(ask(inventory, "Where should the inventory live?", str(Path.home() / "Homelab"))).expanduser()
        remote_url = ask(remote, "Git remote for the inventory (blank for none)", "") or None
        key_answer = ask(key, "SSH key for Bastet ('new' to generate, or a private key path)", "new")
        key_path = None if key_answer == "new" else Path(key_answer).expanduser()
        user = ask(bootstrap_user, "Your SSH login for setting up existing hosts", getpass.getuser())

    name = ask(lab_name, "Lab name", "Homelab")
    domains = {}
    public = ask(public_domain, "Public domain (blank for none)", "")
    internal = ask(internal_domain, "Internal domain (same as public for split DNS; '-' for none)", public)
    internal = "" if internal == "-" else internal
    if public:
        domains["public"] = public
    if internal:
        domains["internal"] = internal
    if snippet is None:
        snippet = True if yes else typer.confirm("Install and enable Bastet's Obsidian stylesheet?", default=True)

    recipients, recovery_private = _plan_recipients(inventory_path, yes)
    if manage_this_machine is None:
        manage_this_machine = False if yes or not _stdout_is_tty() else typer.confirm(
            "Also manage this computer with Bastet? (creates a local 'bastet' user with passwordless sudo; needs sshd)",
            default=False,
        )

    options = InitOptions(
        inventory=inventory_path, remote=remote_url, key=key_path, bootstrap_user=user,
        lab_name=name, domains=domains, snippet=snippet, recipients=recipients,
    )
    out.echo("\nBastet will set up:")
    out.echo(f"  config      {cfg_file}")
    out.echo(f"  inventory   {options.inventory}" + (f"  (remote {options.remote})" if options.remote else ""))
    out.echo(f"  SSH key     {options.key or cfg_file.parent / 'ssh' / 'id_ed25519 (new)'}")
    out.echo(f"  login       {options.bootstrap_user} (to set up the bastet user on existing hosts)")
    out.echo(f"  lab         {options.lab_name}" + (f"  {domains}" if domains else ""))
    out.echo(f"  stylesheet  {'yes' if options.snippet else 'no'}")
    if manage_this_machine:
        out.echo(
            "  this machine  a local 'bastet' user with passwordless sudo (root-equivalent; only "
            "Bastet's SSH key can log in as it)"
        )
    else:
        out.echo("  this machine  not managed")
    if not yes and not typer.confirm("Go ahead?", default=True):
        out.echo("Nothing written.")
        return

    result = initialize(cfg_file, options, keys_dir=cfg_file.parent / "ssh")
    for action in result.actions:
        out.echo(action)
    ctx = load_context()
    refresh_only(ctx)
    out.echo(f"\nBastet's public key ({result.public_key}):")
    out.echo(result.public_key.read_text(encoding="utf-8").strip())
    if recovery_private:
        out.echo()
        out.secho(_RECOVERY_WARNING, fg="yellow")
        out.reveal(recovery_private)
    out.echo()
    if manage_this_machine:
        _setup_this_machine(ctx, result.public_key, yes=yes)
    else:
        out.echo("This computer isn't managed by Bastet. To manage it later: bastet add host <name> --local")
    next_hint("bastet add host", yes=yes)
