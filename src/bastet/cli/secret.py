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

from bastet.cli.common import Context, handles_errors, load_context
from bastet.core.errors import BastetError
from bastet.core.secrets import crypto
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
    opt: Option | None
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


def _collect_uses(ctx: Context) -> dict[str, Needed]:
    uses: dict[str, Needed] = {}
    roles = load_roles()
    for doc in ctx.inventory.of_kind("host"):
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
                for sp, leaf in _refs_in(opt, value, doc.name, a.role.name):
                    existing = uses.get(sp.text)
                    if existing is None:
                        uses[sp.text] = Needed(sp, leaf, [doc.name])
                    elif doc.name not in existing.used_by:
                        existing.used_by.append(doc.name)
    return uses


def needed_secrets(ctx: Context) -> list[Needed]:
    """Secrets referenced by a role option reaching a host, whose note doesn't exist yet."""
    uses = _collect_uses(ctx)
    missing = [n for n in uses.values() if not (ctx.root / n.sp.rel).exists()]
    return sorted(missing, key=lambda n: n.sp.text)


def _opt_for(sp: SecretPath) -> Option | None:
    if not sp.role:
        return None
    role = load_roles().get(sp.role)
    return role.options.get(sp.name) if role else None


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
    _print_inventory(load_context())


# --- `bastet secret set` ---


def _generate(gen: dict) -> str:
    kind = gen.get("kind", "password")
    length = int(gen.get("length") or (32 if kind == "password" else 43))
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


def _set_one(ctx: Context, sp: SecretPath, opt: Option | None, *, piped_value: str | None = None) -> bool:
    """Returns True when a value was sealed and committed (False for `e`, a skip, or a declined replace)."""
    exists = (ctx.root / sp.rel).exists()
    if exists and piped_value is None:
        if not typer.confirm(f"Replace {sp.text}? The old value stays only in encrypted git history", default=False):
            typer.echo("Not replaced.")
            return False
    if piped_value is not None:
        value = piped_value.rstrip("\n")
        if not value:
            raise BastetError(f"{sp.text}: empty value from stdin")
        source = opt.source if opt and opt.source else "chosen"
    else:
        value = None
        source = "chosen"
        while value is None:
            prompt = ("Enter value, Enter to generate, or e to fill it in yourself"
                      if opt and opt.generate else "Enter value, or e to fill it in yourself")
            first = typer.prompt(prompt, hide_input=True, default="", show_default=False)
            if first == "":
                if opt and opt.generate:
                    value, source = _generate(opt.generate), "generated"
                else:
                    typer.echo("Enter a value, or e to fill it in yourself.")
                    continue
            elif first.strip().lower() == "e":
                _write_fill_in_note(ctx, sp, exists)
                return False
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
    return True


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
                if _set_one(ctx, n.sp, n.opt):
                    committed.append(n.sp)
            break
        if choice.isdigit() and 1 <= int(choice) <= len(needed):
            n = needed[int(choice) - 1]
            if _set_one(ctx, n.sp, n.opt):
                committed.append(n.sp)
            continue
        typer.echo(f"'{choice}' isn't a choice.")
    if ctx.repo.is_repo() and committed:
        if len(committed) > 1 and base is not None:
            words = ", ".join(sp.text for sp in committed)
            ctx.repo.squash_since(base, f"secret: set {len(committed)} secrets ({words})")
        if not ctx.repo.push():
            typer.secho("warning: push failed; the commit(s) are kept locally", fg="yellow", err=True)


@secret_app.command("set")
@handles_errors
def secret_set(
    words: list[str] | None = typer.Argument(None, help="host role option, or host name (lab allowed as host)."),
) -> None:
    """Set one secret (named), or walk the list of secrets that need a value."""
    ctx = load_context()
    if words:
        sp = SecretPath.from_cli(words)
        opt = _opt_for(sp)
        if not _stdin_is_tty():
            _set_one(ctx, sp, opt, piped_value=sys.stdin.read())
        else:
            _set_one(ctx, sp, opt)
        return
    _set_walk(ctx)


# --- `bastet secret show` ---


@secret_app.command("show")
@handles_errors
def secret_show(words: list[str] = typer.Argument(..., help="host role option, or host name.")) -> None:
    """The one deliberate way to see a value: display it, or copy it to the clipboard."""
    if not _stdout_is_tty():
        raise BastetError("refuses to show a secret when output isn't a terminal")
    ctx = load_context()
    sp = SecretPath.from_cli(words)
    value = ctx.secrets.get(sp)
    choice = typer.prompt("1) display  2) clipboard  q) cancel", default="q", show_default=False).strip().lower()
    if choice == "1":
        typer.echo(value)
    elif choice == "2":
        tool = _clipboard_tool()
        if tool is None:
            raise BastetError("no clipboard available (wl-copy or xclip, and not over SSH)")
        _copy_to_clipboard(tool, value)
        typer.echo("Copied to the clipboard; it clears in 45s.")
    else:
        typer.echo("Cancelled.")
