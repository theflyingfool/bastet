import contextlib
import functools
from dataclasses import dataclass, field
from pathlib import Path

import typer

from bastet.core.changes import Change, render_diff, write_changes
from bastet.core.config import Config, config_path, data_dir, inventory_dir, load_config
from bastet.core.errors import BastetError
from bastet.core.frontmatter import Document
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import HostType, load_host_types
from bastet.core.inventory import Inventory, load_inventory
from bastet.core.parallel import in_worker
from bastet.core.render import generated_changes
from bastet.core.secrets import confirm as secrets_confirm
from bastet.core.secrets.notes import SecretNote, SecretPath
from bastet.core.secrets.redact import ACTIVE
from bastet.core.secrets.refs import MissingSecret
from bastet.core.secrets.store import AgeStore, for_note


def _refuse_while_in_worker(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if in_worker():
            raise BastetError("internal: tried to ask a question while running in parallel")
        return fn(*args, **kwargs)

    return wrapper


@contextlib.contextmanager
def guard_prompts():
    """Entered once by a command that may run hosts in parallel: `typer.confirm`/`typer.prompt`
    called from a worker thread raise instead of blocking on a terminal only one host can use.
    """
    original_confirm, original_prompt = typer.confirm, typer.prompt
    typer.confirm = _refuse_while_in_worker(original_confirm)
    typer.prompt = _refuse_while_in_worker(original_prompt)
    try:
        yield
    finally:
        typer.confirm = original_confirm
        typer.prompt = original_prompt


def resolve_jobs(option: int | None, config: Config) -> int:
    """The `--jobs`/`-j` value to use: the option when given, else the configured default."""
    return option if option is not None else config.parallel.jobs


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
        self.redactor.protect(sp.text)
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
    upstream_secrets: list[str] = field(default_factory=list)  # `_secrets/` paths a pull just changed
    written: set[Path] = field(default_factory=set, repr=False)  # paths written but not yet committed this command
    pull_error: str | None = field(default=None, repr=False)  # the last pull's failure message, if any
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


def confirm_upstream_secrets(ctx: "Context") -> None:
    """The person accepted the pending secret changes (in `apply`), or Bastet just made its own
    secret commit: stop alerting about everything up to the current HEAD."""
    secrets_confirm.confirm(ctx.repo, ctx.root)


def alert_upstream_secrets(repo: GitRepo, root: Path) -> list[str]:
    """Secret notes changed since the last confirmed commit, however that happened -- a red alert
    naming who, from where, and when. They stay unconfirmed across commands until an
    `apply` confirms them (or Bastet made the change itself), because the confirmed-commit baseline
    only ever moves forward on those two events, not on being alerted about."""
    secret_paths = secrets_confirm.changed_since_confirmed(repo, root)
    if not secret_paths:
        return []
    typer.secho("ALERT: secrets changed upstream:", fg="red", err=True, bold=True)
    for rel in secret_paths:
        info = repo.last_author(root / rel) if (root / rel).exists() else None
        if info is None:
            typer.secho(f"  {rel}", fg="red", err=True)
            continue
        name, email, date = info
        machine = email.split("@", 1)[1] if "@" in email else email
        typer.secho(f"  {rel} — {name} on {machine}, {date}", fg="red", err=True)
    return secret_paths


def load_context(*, allow_plaintext: bool = False) -> Context:
    config = load_config(config_path())
    root = inventory_dir(config, data_dir())
    if not root.is_dir():
        raise BastetError("inventory directory does not exist; run `bastet init`", file=root)
    repo = GitRepo(root)
    upstream_secrets: list[str] = []
    pull_error: str | None = None
    if repo.is_repo():
        repo.ensure_hook()
        # Before pulling: a fresh confirmed-commit baseline is today's HEAD, not tomorrow's -- so a
        # secret change this very pull is about to bring in still gets caught below, while nothing
        # already in history before Bastet ever ran here gets alerted on retroactively.
        secrets_confirm.ensure_baseline(repo, root)
        try:
            repo.pull()
        except BastetError as exc:
            typer.secho(f"warning: {exc}; continuing on the last pulled state", fg="yellow", err=True)
            pull_error = exc.message
        upstream_secrets = alert_upstream_secrets(repo, root)
    if not allow_plaintext:
        _refuse_if_plaintext(root)
    types = load_host_types()
    return Context(config=config, root=root, repo=repo, types=types, inventory=load_inventory(root, types),
                   upstream_secrets=upstream_secrets, pull_error=pull_error)


def problem_line(root: Path, problem) -> tuple[str, str]:
    """A problem's one-line text (file, line, message) and its colour -- shared by `print_problems`
    and `show`'s per-host hint."""
    error = problem.error
    where = ""
    if error.file is not None:
        try:
            rel = error.file.relative_to(root)
        except ValueError:
            rel = error.file
        where = f"{rel}:{error.line}: " if error.line is not None else f"{rel}: "
    fg = "red" if problem.severity == "error" else "yellow"
    return f"{where}{error.message}", fg


def print_problems(ctx: Context) -> None:
    """Print every inventory problem once: errors in red, warnings in yellow, each with its file
    (relative to the inventory root) and line."""
    for problem in ctx.inventory.problems:
        text, fg = problem_line(ctx.root, problem)
        typer.secho(text, fg=fg)


def find_named_host(ctx: Context, name: str) -> Document:
    """A host named on the command line: resolved normally, or, if its file failed to parse (so
    it never made it into the inventory at all), explained via that parse problem instead of a
    bare "no such host"."""
    doc = ctx.inventory.get(name)
    if doc is not None and doc.data.get("bastet") == "host":
        return doc
    for problem in ctx.inventory.problems:
        f = problem.error.file
        if f is not None and f.stem.lower() == name.lower():
            raise BastetError(f"no host named '{name}' (its file has an error: {problem.error.message})")
    raise BastetError(f"no host named '{name}' in the inventory")


PUSH_FAILED_LINE = "committed locally; push failed (offline?); it'll be pushed next time"


def push_or_warn(ctx: Context) -> None:
    """The one push-failure line, everywhere: never changes the exit code; the next command pushes what's pending."""
    if not ctx.repo.push():
        typer.secho(PUSH_FAILED_LINE, fg="yellow", err=True)


def pull_or_warn(ctx: Context) -> None:
    """Pull, recording the failure (if any) on `ctx.pull_error` so a later `refresh_generated` in the same
    command can report it without pulling again over what this command has since written."""
    try:
        ctx.repo.pull()
        ctx.pull_error = None
    except BastetError as exc:
        typer.secho(f"warning: {exc}; continuing on the last pulled state", fg="yellow", err=True)
        ctx.pull_error = exc.message


def write_with_confirmation(ctx: Context, changes: list[Change], yes: bool) -> bool:
    """Show the diff, ask (unless `yes`), and write `changes` to disk -- but don't commit: the files
    are recorded on `ctx.written`, and `finish` commits them (with any regenerated notes) once."""
    if not ctx.repo.is_repo():
        raise BastetError("the inventory is not a git repository; run `bastet init`", file=ctx.root)
    _refuse_if_plaintext(ctx.root)
    pull_or_warn(ctx)
    ctx.upstream_secrets = alert_upstream_secrets(ctx.repo, ctx.root)
    targets = {c.path for c in changes}
    bastet_files = {d.path.resolve() for d in ctx.inventory.objects.values()} | {t.resolve() for t in targets}
    pending = [
        p for p in ctx.repo.dirty()
        if p.suffix == ".md" and p.resolve() in bastet_files and p.resolve() not in ctx.written
    ]
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
    ctx.written |= targets
    return True


def _refresh_skip(reason: str) -> None:
    """A refresh that can't run says why, as a normal line -- never red, never an error."""
    typer.echo(f"refresh skipped: {reason}")


def refresh_generated(
    ctx: Context, *, warnings: dict[str, list[str]] | None = None, drift: dict[str, list[str]] | None = None
) -> list[Change]:
    """Compute and write Bastet's generated notes (summaries, dashboard, views) from the files.

    Doesn't pull, commit or push: it trusts `ctx.pull_error` from this command's own pull, and
    `finish` folds the changes it writes into the command's one commit. Only files under _bastet/
    are touched, so no confirmation is needed.
    """
    if not ctx.repo.is_repo():
        return []
    try:
        if ctx.repo.busy():
            _refresh_skip("a git merge or rebase is in progress in the inventory")
            return []
        from bastet.core.secrets.plaintext import any_plain

        plain = any_plain(ctx.root)
        if plain:
            _refresh_skip(f"{len(plain)} secret(s) are plain text; run `bastet secret lock`")
            return []
        if ctx.pull_error is not None:
            _refresh_skip(f"couldn't sync with the remote ({ctx.pull_error})")
            return []
        ctx.inventory = load_inventory(ctx.root, ctx.types)
        from bastet.core.secrets import health as secret_health

        secrets_summary = (
            secret_health.summary_lines(secret_health.findings(ctx)) if secret_health.relevant_secrets(ctx) else None
        )
        changes = generated_changes(ctx.inventory, ctx.types, ctx.repo, warnings=warnings, drift=drift,
                                    secrets_summary=secrets_summary)
        if not changes:
            return []
        write_changes(changes)
    except Exception as exc:  # refreshing generated notes must never break the command that triggered it
        _refresh_skip(f"{exc.__class__.__name__}: {exc}")
        return []
    typer.echo(f"Refreshed {len(changes)} generated note{'s' if len(changes) != 1 else ''} in _bastet/.")
    return changes


def refresh_only(ctx: Context) -> list[Change]:
    """Regenerate and commit on its own (`refresh: N generated notes`) -- for a command with nothing
    of its own to fold the regenerated notes into."""
    changes = refresh_generated(ctx)
    if changes:
        committed = ctx.repo.commit(
            [c.path for c in changes], f"refresh: {len(changes)} generated note{'s' if len(changes) != 1 else ''}"
        )
        if committed:
            push_or_warn(ctx)
    return changes


def finish(
    ctx: Context, message: str, *, warnings: dict[str, list[str]] | None = None, drift: dict[str, list[str]] | None = None
) -> bool:
    """Commit this command's own writes (`ctx.written`) together with any regenerated notes, as one
    commit, and push once. A command with nothing to write makes no commit."""
    generated = refresh_generated(ctx, warnings=warnings, drift=drift)
    paths = ctx.written | {c.path for c in generated}
    ctx.written = set()
    if not paths:
        return False
    full_message = f"{message} (+{len(generated)} generated)" if generated else message
    if not ctx.repo.commit(sorted(paths), full_message):
        return False
    # The dashboard's "Recent changes" can only show this commit once it exists; catch it up now,
    # folding that into the same commit rather than making a second one.
    caught_up = refresh_generated(ctx)
    if caught_up:
        ctx.repo.amend([c.path for c in caught_up])
    push_or_warn(ctx)
    return True


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
