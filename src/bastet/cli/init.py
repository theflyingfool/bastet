import getpass
from pathlib import Path

import typer

from bastet.cli.common import handles_errors, load_context, refresh_generated
from bastet.core.config import config_path, data_dir, inventory_dir, load_config
from bastet.core.initialize import InitOptions, initialize


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

    options = InitOptions(
        inventory=inventory_path, remote=remote_url, key=key_path, bootstrap_user=user,
        lab_name=name, domains=domains, snippet=snippet,
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
