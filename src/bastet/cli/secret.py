"""`bastet secret`: the secret inventory, `set` (list, generate, fill-in) and `show` (spec 15.3)."""

from __future__ import annotations

import datetime as dt
import os
import secrets as stdsecrets
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

import typer
from rich.progress import Progress

from bastet.cli.common import Context, handles_errors, load_context
from bastet.core.errors import BastetError
from bastet.core.secrets import crypto, plaintext
from bastet.core.secrets.notes import SecretNote, SecretPath, all_notes
from bastet.roles.contract import Option, load_roles
from bastet.roles.resolve import resolve

secret_app = typer.Typer(invoke_without_command=True, help="The secret inventory, set and show (never values here).")


# --- small, patchable seams, so tests never touch a real terminal or clipboard ---


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def _stdout_is_tty() -> bool:
    return sys.stdout.isatty()


def _clipboard_tool() -> str | None:
    if os.environ.get("SSH_CONNECTION"):
        return None
    for tool in ("wl-copy", "xclip"):
        if shutil.which(tool):
            return tool
    return None


def _popen(cmd: list[str]) -> None:
    subprocess.Popen(  # noqa: S603 - a fixed, local clipboard-clearing command
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
    )


def _copy_to_clipboard(tool: str, value: str) -> None:
    if tool == "wl-copy":
        subprocess.run(["wl-copy"], input=value.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        clear = "sleep 45; wl-copy --clear"
    else:
        subprocess.run(["xclip", "-selection", "clipboard"], input=value.encode(),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        clear = "sleep 45; printf '' | xclip -selection clipboard"
    _popen(["sh", "-c", clear])


def _now() -> str:
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M")


# --- the "needed" scan: role contracts and role files reaching hosts (resolve()), via `secret:` references ---


@dataclass
class Needed:
    sp: SecretPath
    contract_opt: Option | None
    used_by: list[str] = field(default_factory=list)


def _refs_in(opt: Option, value: object, host: str, role: str):
    if isinstance(value, str) and value.startswith("secret:"):
        ref = value[len("secret:"):]
        sp = SecretPath.parse(ref) if "/" in ref else SecretPath(host, role, ref)
        yield sp, opt
        return
    if value is None:
        return
    if opt.type == "list" and isinstance(value, list):
        for item in value:
            yield from _refs_in(opt.items, item, host, role)
    elif opt.type == "map" and isinstance(value, dict):
        for v in value.values():
            yield from _refs_in(opt.items, v, host, role)
    elif opt.type == "object" and isinstance(value, dict):
        for k, v in value.items():
            if k in opt.fields:
                yield from _refs_in(opt.fields[k], v, host, role)


def _record(uses: dict[str, Needed], sp: SecretPath, opt: Option, host: str) -> None:
    existing = uses.get(sp.text)
    if existing is None:
        uses[sp.text] = Needed(sp, opt, [host])
    elif host not in existing.used_by:
        existing.used_by.append(host)


def _collect_uses(ctx: Context, hosts: list[str] | None = None) -> dict[str, Needed]:
    uses: dict[str, Needed] = {}
    roles = load_roles()
    wanted = set(hosts) if hosts is not None else None
    for doc in ctx.inventory.of_kind("host"):
        if wanted is not None and doc.name not in wanted:
            continue
        if doc.data.get("state", "present") == "destroyed":
            continue
        try:
            applied = resolve(ctx.inventory, doc, ctx.types, roles)
        except BastetError:
            continue  # a broken role file elsewhere shouldn't break the secret inventory
        for a in applied:
            for key, value in a.values.items():
                opt = a.role.options.get(key)
                if opt is None:
                    continue
                if value is None:
                    # a `secret: true` option with no value at all still needs a secret, implicitly
                    # at the host/role/option path (no explicit `secret:` reference required).
                    if opt.secret:
                        _record(uses, SecretPath(doc.name, a.role.name, key), opt, doc.name)
                    continue
                for sp, leaf in _refs_in(opt, value, doc.name, a.role.name):
                    _record(uses, sp, leaf, doc.name)
    return uses


def needed_secrets(ctx: Context, hosts: list[str] | None = None) -> list[Needed]:
    """Secrets referenced by a role option reaching a host, whose note doesn't exist yet.

    `hosts`, when given, scopes the scan to those host names only (used by `apply`/`check`, which only
    care about the hosts being run, and by `add role`, which cares about the target's hosts).
    """
    uses = _collect_uses(ctx, hosts)
    missing = [n for n in uses.values() if not (ctx.root / n.sp.rel).exists()]
    return sorted(missing, key=lambda n: n.sp.text)


def _opt_for(sp: SecretPath) -> Option | None:
    if not sp.role:
        return None
    role = load_roles().get(sp.role)
    return role.options.get(sp.name) if role else None


def secret_words(sp: SecretPath) -> str:
    """The `host role option` (or `host option`) words `bastet secret set` takes for this path."""
    return " ".join(part for part in (sp.host, sp.role, sp.name) if part)


# --- `bastet secret`: the inventory, never values ---


def _print_inventory(ctx: Context) -> None:
    uses = _collect_uses(ctx)
    notes = {n.path.text: n for n in all_notes(ctx.root)}
    texts = sorted(set(notes) | set(uses))
    if not texts:
        typer.echo("No secrets yet.")
        return
    typer.echo(f"{'secret':35} {'source':10} {'created':17} {'status':9} used by")
    for text in texts:
        note = notes.get(text)
        used_by = ", ".join(uses[text].used_by) if text in uses else ""
        if note is None:
            source, created, status = "", "", "missing"
        else:
            source, created = str(note.data.get("source") or ""), str(note.data.get("created") or "")
            status = "set" if note.is_sealed else "unlocked"
        typer.echo(f"{text:35} {source:10} {created:17} {status:9} {used_by}")


@secret_app.callback(invoke_without_command=True)
@handles_errors
def secret_main(ctx_typer: typer.Context) -> None:
    """The secret inventory: every secret, its host/role/option, whether it's set, and who uses it."""
    if ctx_typer.invoked_subcommand is not None:
        return
    _print_inventory(load_context(allow_plaintext=True))  # never shows values; shows which are unlocked


# --- `bastet secret set` ---


def _generate(gen: dict) -> str:
    kind = gen.get("kind", "password")
    length = int(gen.get("length") or 32)
    if kind == "password":
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~"
        return "".join(stdsecrets.choice(alphabet) for _ in range(length))
    if kind == "token":
        return stdsecrets.token_urlsafe(length)
    raise BastetError(f"unknown generate.kind {kind!r}")


def _write_note(ctx: Context, sp: SecretPath, value: str, source: str, exists: bool) -> None:
    now = _now()
    if exists:
        note = SecretNote.load(ctx.root, sp)
        note.data["source"] = source
        note.data["rotated"] = now
    else:
        note = SecretNote.new(sp, source=source, created=now, applies_to=sp.host)
    note.data["locked"] = True
    note.body = crypto.seal(sp.text, value, ctx.secrets.recipients)
    note.write(ctx.root)


def _write_fill_in_note(ctx: Context, sp: SecretPath, exists: bool) -> None:
    if exists:
        note = SecretNote.load(ctx.root, sp)
    else:
        note = SecretNote.new(sp, source="chosen", created=_now(), applies_to=sp.host)
    note.data["locked"] = False
    note.body = ""
    note.write(ctx.root)
    typer.echo(f"Wrote an unlocked note for {sp.text}; fill in the value, then run `bastet secret lock`.")


def _set_one(
    ctx: Context, sp: SecretPath, opt: Option | None, *, piped_value: str | None = None, allow_skip: bool = False
) -> str:
    """Returns "committed", "filled_in" (via `e`), "skipped" (via `s`, only offered when `allow_skip`), or
    "declined" (an existing secret, not replaced)."""
    exists = (ctx.root / sp.rel).exists()
    if piped_value is not None:
        if exists:
            # a confirm would read from the same, already-consumed pipe; refuse rather than guess
            raise BastetError(f"{sp.text} already exists; run without piping a value to replace it")
        value = piped_value[:-1] if piped_value.endswith("\n") else piped_value
        value = value[:-1] if value.endswith("\r") else value
        if not value:
            raise BastetError(f"{sp.text}: empty value from stdin")
        source = opt.source if opt and opt.source else "chosen"
    else:
        if exists:
            if not typer.confirm(f"Replace {sp.text}? The old value stays only in encrypted git history", default=False):
                typer.echo("Not replaced.")
                return "declined"
        value = None
        source = "chosen"
        while value is None:
            prompt = ("Enter value, Enter to generate, or e to fill it in yourself"
                      if opt and opt.generate else "Enter value, or e to fill it in yourself")
            if allow_skip:
                prompt += ", or s to skip"
            first = typer.prompt(prompt, hide_input=True, default="", show_default=False)
            if allow_skip and first.strip().lower() == "s":
                return "skipped"
            if first == "":
                if opt and opt.generate:
                    value, source = _generate(opt.generate), "generated"
                else:
                    typer.echo("Enter a value, or e to fill it in yourself.")
                    continue
            elif first.strip().lower() == "e":
                _write_fill_in_note(ctx, sp, exists)
                return "filled_in"
            else:
                second = typer.prompt("Confirm", hide_input=True)
                if second != first:
                    typer.echo("Values didn't match; try again.")
                    continue
                value, source = first, (opt.source if opt and opt.source else "chosen")
    _write_note(ctx, sp, value, source, exists)
    ctx.secrets.redactor.add(value)
    typer.echo(f"Set {sp.text} ({source}, {len(value)} characters).")
    ctx.repo.commit([ctx.root / sp.rel], f"secret: set {sp.text}")
    return "committed"


def _set_walk(ctx: Context) -> None:
    base = ctx.repo.head() if ctx.repo.is_repo() else None
    committed: list[SecretPath] = []
    while True:
        needed = needed_secrets(ctx)
        if not needed:
            if not committed:
                typer.echo("Nothing to set.")
            break
        typer.echo("Secrets that need a value:")
        for i, n in enumerate(needed, 1):
            typer.echo(f"  {i}. {n.sp.text} (used by {', '.join(n.used_by)})")
        choice = typer.prompt(f"Choice [1-{len(needed)}, 0=all, q=quit]").strip().lower()
        if choice == "q":
            break
        if choice == "0":
            for n in needed:
                if _set_one(ctx, n.sp, n.contract_opt) == "committed":
                    committed.append(n.sp)
            break
        if choice.isdigit() and 1 <= int(choice) <= len(needed):
            n = needed[int(choice) - 1]
            if _set_one(ctx, n.sp, n.contract_opt) == "committed":
                committed.append(n.sp)
            continue
        typer.echo(f"'{choice}' isn't a choice.")
    if ctx.repo.is_repo() and committed:
        if len(committed) > 1 and base is not None:
            words = ", ".join(sp.text for sp in committed)
            ctx.repo.squash_since(base, f"secret: set {len(committed)} secrets ({words})")
        if not ctx.repo.push():
            typer.secho("warning: push failed; the commit(s) are kept locally", fg="yellow", err=True)


def _pull_quietly(ctx: Context) -> None:
    if not ctx.repo.is_repo():
        return
    try:
        ctx.repo.pull()
    except BastetError as exc:
        typer.secho(f"warning: {exc}; continuing on the last pulled state", fg="yellow", err=True)


@secret_app.command("set")
@handles_errors
def secret_set(
    words: list[str] | None = typer.Argument(None, help="host role option, or host name (lab allowed as host)."),
) -> None:
    """Set one secret (named), or walk the list of secrets that need a value."""
    ctx = load_context(allow_plaintext=True)
    _pull_quietly(ctx)
    if words:
        sp = SecretPath.from_cli(words)
        opt = _opt_for(sp)
        if not _stdin_is_tty():
            result = _set_one(ctx, sp, opt, piped_value=sys.stdin.read())
        else:
            result = _set_one(ctx, sp, opt)
        if result == "committed" and ctx.repo.is_repo() and not ctx.repo.push():
            typer.secho("warning: push failed; the commit is kept locally", fg="yellow", err=True)
        return
    if not _stdin_is_tty():
        raise BastetError("the secret list only works at a terminal; name a secret to pipe a value into it")
    _set_walk(ctx)


# --- `bastet secret show` ---


@secret_app.command("show")
@handles_errors
def secret_show(words: list[str] = typer.Argument(..., help="host role option, or host name.")) -> None:
    """The one deliberate way to see a value: display it, or copy it to the clipboard."""
    if not _stdout_is_tty():
        raise BastetError("refuses to show a secret when output isn't a terminal")
    ctx = load_context(allow_plaintext=True)
    sp = SecretPath.from_cli(words)
    value = ctx.secrets.get(sp)
    tool = _clipboard_tool()
    menu = "1) display  2) clipboard  q) cancel" if tool else "1) display  q) cancel"
    choice = typer.prompt(menu, default="q", show_default=False).strip().lower()
    if choice == "1":
        typer.echo(value)
    elif choice == "2" and tool:
        _copy_to_clipboard(tool, value)
        typer.echo("Copied to the clipboard; it clears in 45s.")
    else:
        typer.echo("Cancelled.")


# --- `bastet secret unlock` / `bastet secret lock` (spec 15.4) ---


def _read_key(timeout: float) -> str | None:
    """Read one key from the terminal within `timeout` seconds: ENTER, q, ESC, CTRL_C, or None."""
    import select
    import termios
    import tty

    if not sys.stdin.isatty():
        return None
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        ready, _, _ = select.select([fd], [], [], max(timeout, 0))
        if not ready:
            return None
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if ch in ("\r", "\n"):
        return "ENTER"
    if ch == "\x03":
        return "CTRL_C"
    if ch == "\x1b":
        # a lone Esc vs. the start of an arrow-key escape sequence: a short follow-up read tells them apart
        old2 = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            ready2, _, _ = select.select([fd], [], [], 0.05)
            if not ready2:
                return "ESC"
            sys.stdin.read(1)  # swallow the rest of the escape sequence; not a key we act on
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old2)
    if ch.lower() == "q":
        return "q"
    return None


def _format_remaining(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _render_countdown(remaining: float) -> None:
    text = f"Unlocked. Locks in {_format_remaining(remaining)} — Enter: +15m, q/Esc: lock now"
    colour = "red" if remaining <= 60 else "yellow"
    typer.secho(f"\r{text}   ", fg=colour, nl=False, err=True)


def _interactive_countdown() -> None:
    import time

    typer.echo(err=True)  # keep the countdown line from overwriting the progress bar's own line
    plaintext.run_countdown(_read_key, time.monotonic, _render_countdown)
    typer.echo(err=True)


_BACKUP_WARNING = (
    "warning: backups taken while secrets are unlocked keep the plain text, "
    "and Obsidian's own search index may too"
)


@secret_app.command("unlock")
@handles_errors
def secret_unlock(words: list[str] | None = typer.Argument(None, help="host role option, or host name.")) -> None:
    """Plain text in place, for one secret or all; locks itself after a countdown (or run `secret lock`)."""
    ctx = load_context(allow_plaintext=True)
    reason = plaintext.preflight_block(ctx.root)
    if reason:
        raise BastetError(reason)
    which = [SecretPath.from_cli(words)] if words else None
    on_tty = _stdout_is_tty()
    if on_tty:
        typer.secho(_BACKUP_WARNING, fg="yellow", err=True)
    with Progress(disable=not on_tty) as progress:
        task = progress.add_task("Decrypting", total=None)
        unlocked = plaintext.unlock(ctx.root, ctx.secrets, which)
        progress.update(task, completed=1)
    if not on_tty:
        typer.echo("Unlocked. Run `bastet secret lock` when done.")
        return
    if not unlocked:
        typer.echo("Nothing to unlock.")
        return
    _interactive_countdown()
    result = plaintext.lock(ctx.root, ctx.secrets)
    _print_lock_summary(result)


def _print_lock_summary(result: plaintext.LockResult) -> None:
    if result.locked == 0:
        typer.echo("Nothing to lock.")
        return
    summary = f"{result.locked} locked · {result.changed} changed"
    if result.changed:
        summary += " · committed"
    typer.echo(summary)


@secret_app.command("lock")
@handles_errors
def secret_lock() -> None:
    """Encrypt every plain-text secret note and commit what changed."""
    ctx = load_context(allow_plaintext=True)
    with Progress(disable=not _stdout_is_tty()) as progress:
        task = progress.add_task("Locking", total=None)
        result = plaintext.lock(ctx.root, ctx.secrets)
        progress.update(task, completed=1)
    _print_lock_summary(result)
