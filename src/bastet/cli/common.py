import functools
from dataclasses import dataclass, field
from pathlib import Path

import typer

from bastet.core.changes import Change, render_diff, write_changes
from bastet.core.config import Config, config_path, data_dir, inventory_dir, load_config
from bastet.core.errors import BastetError
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import HostType, load_host_types
from bastet.core.inventory import Inventory, load_inventory
from bastet.core.render import generated_changes
from bastet.core.secrets.notes import SecretNote, SecretPath
from bastet.core.secrets.redact import ACTIVE
from bastet.core.secrets.refs import MissingSecret
from bastet.core.secrets.store import AgeStore, for_note


def handles_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except BastetError as exc:
            typer.secho(ACTIVE.mask(f"error: {exc}"), fg="red", err=True)
            raise typer.Exit(1) from None

    return wrapper


class SecretsContext:
    """Recipients, the decrypting identity, and the redactor: built lazily, so a run with no secrets needs no keys."""

    def __init__(self, root: Path, recipients: list[str], identity_path: Path | None) -> None:
        self.root = root
        self.recipients = recipients
        self.identity_path = identity_path
        self.redactor = ACTIVE  # one per process, so the top-level error handler masks too
        self._identities: list | None = None

    def _ensure_identities(self) -> list:
        if self._identities is None:
            if self.identity_path is None:
                raise BastetError("no Bastet SSH key or secrets.age_identity configured; run `bastet init`")
            from bastet.core.secrets.crypto import identity  # lazy: only touched when a secret is actually read

            self._identities = [identity(self.identity_path)]
        return self._identities

    def get(self, sp: SecretPath) -> str:
        if not (self.root / sp.rel).exists():
            raise MissingSecret(sp)
        note = SecretNote.load(self.root, sp)
        store = for_note(note, {"age": AgeStore(self.recipients, self._ensure_identities())})
        value = store.get(note)
        self.redactor.add(value)
        return value

    def identities(self) -> list:
        """The decrypting identities, built lazily: used by plaintext.unlock/lock to open arbitrary notes."""
        return self._ensure_identities()


def _own_recipients(ctx: "Context") -> list[str]:
    lab = ctx.inventory.lab
    recipients = list((lab.data.get("secrets") or {}).get("recipients") or []) if lab is not None else []
    key = ctx.config.ssh.key
    if key is not None:
        pub = Path(str(key) + ".pub")
        if pub.is_file():
            recipients.append(pub.read_text(encoding="utf-8").strip())
    return recipients


@dataclass
class Context:
    config: Config
    root: Path
    repo: GitRepo
    types: dict[str, HostType]
    inventory: Inventory
    _secrets: SecretsContext | None = field(default=None, init=False, repr=False)

    @property
    def secrets(self) -> SecretsContext:
        if self._secrets is None:
            identity_path = self.config.secrets.age_identity or self.config.ssh.key
            self._secrets = SecretsContext(self.root, _own_recipients(self), identity_path)
        return self._secrets


def _refuse_if_plaintext(root: Path) -> None:
    from bastet.core.secrets.plaintext import any_plain

    plain = any_plain(root)
    if plain:
        n = len(plain)
        raise BastetError(f"{n} secret(s) are plain text: finish them and run `bastet secret lock`")


def load_context(*, allow_plaintext: bool = False) -> Context:
    config = load_config(config_path())
    root = inventory_dir(config, data_dir())
    if not root.is_dir():
        raise BastetError("inventory directory does not exist; run `bastet init`", file=root)
    repo = GitRepo(root)
    if repo.is_repo():
        repo.ensure_hook()
    if not allow_plaintext:
        _refuse_if_plaintext(root)
    types = load_host_types()
    return Context(config=config, root=root, repo=repo, types=types, inventory=load_inventory(root, types))


def write_with_confirmation(ctx: Context, changes: list[Change], message: str, yes: bool) -> bool:
    if not ctx.repo.is_repo():
        raise BastetError("the inventory is not a git repository; run `bastet init`", file=ctx.root)
    _refuse_if_plaintext(ctx.root)
    try:
        ctx.repo.pull()
    except BastetError as exc:
        typer.secho(f"warning: {exc}; continuing on the last pulled state", fg="yellow", err=True)
    targets = {c.path for c in changes}
    bastet_files = {d.path.resolve() for d in ctx.inventory.objects.values()} | {t.resolve() for t in targets}
    pending = [p for p in ctx.repo.dirty() if p.suffix == ".md" and p.resolve() in bastet_files]
    if pending:
        typer.echo("Uncommitted edits to Bastet files:")
        for path in pending:
            typer.echo(f"  {path.relative_to(ctx.root)}")
        if yes or typer.confirm("Commit them as you before Bastet writes?", default=True):
            ctx.repo.commit(pending, "Edits committed before a Bastet change", as_bastet=False)
        else:
            clash = sorted(targets & set(pending))
            if clash:
                raise BastetError("has uncommitted edits; commit them first", file=clash[0])
    for change in changes:
        typer.echo(render_diff(change, ctx.root))
    if not yes and not typer.confirm("Write?", default=True):
        typer.echo("Nothing written.")
        return False
    write_changes(changes)
    ctx.repo.commit(sorted(targets), message)
    if not ctx.repo.push():
        typer.secho("warning: push failed; the commit is kept locally", fg="yellow", err=True)
    return True


def refresh_generated(
    ctx: Context, *, warnings: dict[str, list[str]] | None = None, drift: dict[str, list[str]] | None = None
) -> int:
    """Rewrite Bastet's generated notes (summaries, dashboard, views) from the files; commit them as `refresh:`.

    Only files under _bastet/ are touched, so no confirmation is needed.
    """
    if not ctx.repo.is_repo():
        return 0
    try:
        if ctx.repo.busy():
            typer.secho("refresh skipped: a git merge or rebase is in progress in the inventory", fg="yellow", err=True)
            return 0
        from bastet.core.secrets.plaintext import any_plain

        plain = any_plain(ctx.root)
        if plain:
            typer.secho(
                f"refresh skipped: {len(plain)} secret(s) are plain text; run `bastet secret lock`",
                fg="yellow",
                err=True,
            )
            return 0
        try:
            ctx.repo.pull()
        except BastetError as exc:
            typer.secho(f"refresh skipped: couldn't sync with the remote ({exc.message})", fg="yellow", err=True)
            return 0
        ctx.inventory = load_inventory(ctx.root, ctx.types)
        changes = generated_changes(ctx.inventory, ctx.types, ctx.repo, warnings=warnings, drift=drift)
        if not changes:
            return 0
        write_changes(changes)
        ctx.repo.commit([c.path for c in changes], f"refresh: {len(changes)} generated note{'s' if len(changes) != 1 else ''}")
        if not ctx.repo.push():
            typer.secho("warning: push failed; the commit is kept locally", fg="yellow", err=True)
    except Exception as exc:  # refreshing generated notes must never break the command that triggered it
        typer.secho(f"refresh skipped: {exc.__class__.__name__}: {exc}", fg="yellow", err=True)
        return 0
    typer.echo(f"Refreshed {len(changes)} generated note{'s' if len(changes) != 1 else ''} in _bastet/.")
    return len(changes)


def ssh_ports(ctx: Context, doc) -> list[int]:
    """Ports Bastet tries, in order: the host's ssh role `port` list, then 22 (a host not moved yet, or a new one)."""
    return list(dict.fromkeys([ssh_port(ctx, doc), *_role_ports(ctx, doc), 22]))


def scan_first(scan, address: str, recorded: str | None, ports: list[int]):
    """Scan host keys on each port in turn; returns (keys, port) for the first that answers."""
    from bastet.core.errors import Unreachable

    last: Unreachable | None = None
    for port in ports:
        try:
            return scan(address, recorded=recorded, port=port), port
        except Unreachable as exc:
            last = exc
    raise last if last is not None else BastetError(f"{address}: no port to try")


def _role_ports(ctx: Context, doc) -> list[int]:
    from bastet.roles.contract import load_roles  # lazy: roles builds on core
    from bastet.roles.resolve import resolve

    try:
        applied = {a.role.name: a for a in resolve(ctx.inventory, doc, ctx.types, load_roles())}
    except BastetError:
        return []
    return [int(p) for p in (applied["ssh"].values.get("port") if "ssh" in applied else None) or []]


def ssh_port(ctx: Context, doc) -> int:
    """The first port the host's ssh role lists, else 22."""
    from bastet.roles.contract import load_roles  # lazy: roles builds on core
    from bastet.roles.resolve import resolve

    try:
        applied = {a.role.name: a for a in resolve(ctx.inventory, doc, ctx.types, load_roles())}
    except BastetError as exc:
        typer.secho(f"{doc.name}: roles couldn't be read ({exc.message}); connecting on port 22", fg="yellow", err=True)
        return 22
    ports = (applied["ssh"].values.get("port") if "ssh" in applied else None) or [22]
    return int(ports[0])
