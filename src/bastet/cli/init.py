import getpass
from pathlib import Path

import typer

from bastet.cli.common import handles_errors, load_context, refresh_generated
from bastet.core.changes import Change, render_diff
from bastet.core.config import config_path, data_dir, inventory_dir, load_config
from bastet.core.errors import BastetError
from bastet.core.frontmatter import set_keys
from bastet.core.initialize import InitOptions, existing_recipients, generate_recovery_key, initialize

_RECOVERY_WARNING = (
    "Recovery key: keep this offline. It's the only way back if this laptop is lost. It won't be shown again."
)


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
    private key to print once, if a diff was offered (or there was nothing to confirm) and accepted."""
    homelab_path = inventory_path / "Homelab.md"
    if existing_recipients(homelab_path):
        return None, None
    recovery_private, recovery_public = generate_recovery_key()
    your_pub = _your_pub_text(yes)
    recipients = [recovery_public] + ([your_pub] if your_pub else [])
    if not homelab_path.is_file():
        return recipients, recovery_private
    before = homelab_path.read_text(encoding="utf-8")
    after = set_keys(before, {"secrets": {"recipients": recipients}}, homelab_path)
    typer.echo("\nBastet will add to Homelab.md:")
    typer.echo(render_diff(Change(homelab_path, before, after), inventory_path))
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
        typer.echo(f"Using {cfg_file} (edit it to change the inventory, remote, key or login).")
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

    options = InitOptions(
        inventory=inventory_path, remote=remote_url, key=key_path, bootstrap_user=user,
        lab_name=name, domains=domains, snippet=snippet, recipients=recipients,
    )
    typer.echo("\nBastet will set up:")
    typer.echo(f"  config      {cfg_file}")
    typer.echo(f"  inventory   {options.inventory}" + (f"  (remote {options.remote})" if options.remote else ""))
    typer.echo(f"  SSH key     {options.key or cfg_file.parent / 'ssh' / 'id_ed25519 (new)'}")
    typer.echo(f"  login       {options.bootstrap_user} (to set up the bastet user on existing hosts)")
    typer.echo(f"  lab         {options.lab_name}" + (f"  {domains}" if domains else ""))
    typer.echo(f"  stylesheet  {'yes' if options.snippet else 'no'}")
    if not yes and not typer.confirm("Go ahead?", default=True):
        typer.echo("Nothing written.")
        return

    result = initialize(cfg_file, options, keys_dir=cfg_file.parent / "ssh")
    for action in result.actions:
        typer.echo(action)
    refresh_generated(load_context())
    typer.echo(f"\nBastet's public key ({result.public_key}):")
    typer.echo(result.public_key.read_text(encoding="utf-8").strip())
    if recovery_private:
        typer.echo()
        typer.secho(_RECOVERY_WARNING, fg="yellow")
        typer.echo(recovery_private)
