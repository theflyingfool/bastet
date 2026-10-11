"""Block entries in a Markdown role file: packages, systemd, users and whole files, handed to the building blocks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.engine.files import Block, Directory, File, Line, Symlink
from bastet.engine.model import Resource
from bastet.engine.packages import Package
from bastet.engine.slots import SLOTS
from bastet.engine.systemd import (
    Hostname,
    Locale,
    TimeSettings,
    Unit,
    drop_in,
    reload,
    restart,
)
from bastet.engine.templates import render_template
from bastet.engine.users import AuthorizedKey, Group, User, sudoer
from bastet.roles import expr

COMMON_KEYS = {"when", "before", "after"}
PACKAGE_KEYS = {"name", "state", "version", "aur", "purge"} | COMMON_KEYS
SYSTEMD_KINDS = {
    "unit": {"name", "enabled", "state"},
    "time": {"timezone", "ntp", "rtc_local"},
    "hostname": {"name"},
    "locale": {"lang", "keymap"},
    "dropin": {"unit", "name", "content", "restart"},
}
SYSTEMD_REQUIRED = {"unit": ("name",), "dropin": ("unit", "name", "content")}
USER_FIELDS = {"name", "uid", "group", "groups", "append", "comment", "home", "create_home", "move_home", "shell", "system",
               "password", "password_hash", "update_password", "locked", "expires", "max_days", "min_days", "warn_days",
               "inactive_days", "non_unique", "skeleton"}
USERS_KINDS = {
    "user": USER_FIELDS,
    "group": {"name", "gid", "system", "members", "append_members"},
    "key": {"user", "key", "options", "path", "state"},
    "sudoer": {"name", "rules", "user", "group", "commands", "runas", "hosts", "nopasswd", "setenv", "defaults"},
}
USERS_REQUIRED = {"user": ("name",), "group": ("name",), "key": ("user", "key"), "sudoer": ("name",)}
BASTET_USER = "bastet"


def _fail(msg: str, path: Path, key: str) -> BastetError:
    return BastetError(msg, file=path, key=key)


def check_common(entry: dict, allowed: set[str], where: str, path: Path, key: str) -> None:
    """`when`, `before`/`after` and every `{{ }}` string in an entry, checked when the role is read."""
    if "when" in entry:
        if not isinstance(entry["when"], str):
            raise _fail(f"{where}: when must be text", path, key)
        try:
            expr.check_when(entry["when"], allowed, where)
        except BastetError as exc:
            raise _fail(exc.message, path, key) from None
    for k in ("before", "after"):
        if k in entry and entry[k] not in SLOTS:
            raise _fail(f"{where}: {k}: unknown block {entry[k]!r} (known: {', '.join(SLOTS)})", path, key)
    if "before" in entry and "after" in entry:
        raise _fail(f"{where}: use before or after, not both", path, key)
    _walk_check(entry, allowed, where, path, key)


def _walk_check(value: object, allowed: set[str], where: str, path: Path, key: str) -> None:
    if isinstance(value, str):
        try:
            expr.check_text(value, allowed, where)
        except BastetError as exc:
            raise _fail(exc.message, path, key) from None
    elif isinstance(value, list):
        for v in value:
            _walk_check(v, allowed, where, path, key)
    elif isinstance(value, dict):
        for k, v in value.items():
            if k != "when":
                _walk_check(v, allowed, where, path, key)


def _unknown(entry: dict, keys: set[str], where: str, path: Path) -> None:
    if bad := sorted(str(k) for k in set(entry) - keys):
        raise _fail(f"{where}: unknown key {', '.join(bad)}", path, bad[0])


def parse_packages(path: Path, items: object, options: dict) -> list[dict]:
    if not isinstance(items, list):
        raise _fail("packages must be a list", path, "packages")
    allowed, out = set(options), []
    for i, item in enumerate(items):
        where = f"packages[{i}]"
        entry = {"name": item} if isinstance(item, str) else item
        if not isinstance(entry, dict):
            raise _fail(f"{where}: each entry is a name or a map", path, "packages")
        _unknown(entry, PACKAGE_KEYS, where, path)
        if not isinstance(entry.get("name"), str) or not entry["name"]:
            raise _fail(f"{where}: needs a name", path, "packages")
        if entry.get("state", "present") not in ("present", "absent"):
            raise _fail(f"{where}: state must be present or absent", path, "packages")
        check_common(entry, allowed, where, path, "packages")
        out.append(dict(entry))
    return out


def parse_systemd(path: Path, items: object, options: dict) -> list[dict]:
    if not isinstance(items, list):
        raise _fail("systemd must be a list", path, "systemd")
    allowed, out = set(options), []
    for i, entry in enumerate(items):
        where = f"systemd[{i}]"
        if not isinstance(entry, dict):
            raise _fail(f"{where}: each entry is a map", path, "systemd")
        kind = entry.get("kind")
        if kind is None:
            raise _fail(f"{where}: needs a kind", path, "systemd")
        if kind not in SYSTEMD_KINDS:
            raise _fail(f"{where}: kind must be one of {', '.join(SYSTEMD_KINDS)}", path, "systemd")
        _unknown(entry, SYSTEMD_KINDS[kind] | COMMON_KEYS | {"kind"}, where, path)
        for need in SYSTEMD_REQUIRED.get(kind, ()):
            if entry.get(need) in (None, ""):
                raise _fail(f"{where}: {kind}: needs {need}", path, "systemd")
        if entry.get("state") not in (None, "up", "down") and not str(entry["state"]).startswith("{{"):
            raise _fail(f"{where}: state must be up or down", path, "systemd")
        check_common(entry, allowed, where, path, "systemd")
        out.append(dict(entry))
    return out


def parse_users(path: Path, items: object, options: dict) -> list[dict]:
    if not isinstance(items, list):
        raise _fail("users must be a list", path, "users")
    allowed, out = set(options), []
    for i, entry in enumerate(items):
        where = f"users[{i}]"
        if not isinstance(entry, dict):
            raise _fail(f"{where}: each entry is a map", path, "users")
        kind = entry.get("kind")
        if kind is None:
            raise _fail(f"{where}: needs a kind", path, "users")
        if kind not in USERS_KINDS:
            raise _fail(f"{where}: kind must be one of {', '.join(USERS_KINDS)}", path, "users")
        _unknown(entry, USERS_KINDS[kind] | COMMON_KEYS | {"kind"}, where, path)
        for need in USERS_REQUIRED[kind]:
            if entry.get(need) in (None, ""):
                raise _fail(f"{where}: {kind}: needs {need}", path, "users")
        if entry.get("password") is not None and entry.get("password_hash") is not None:
            raise _fail(f"{where}: give password or password_hash, not both", path, "users")
        named = (entry.get("user"),) if kind == "key" else (entry.get("name"), entry.get("user"))
        if BASTET_USER in named:
            raise _fail(f"{where}: the bastet account is managed by Bastet itself", path, "users")
        check_common(entry, allowed, where, path, "users")
        out.append(dict(entry))
    return out


def placed(resource: Resource, role, entry: dict, secret_options: frozenset = frozenset()) -> Resource:
    """Order and capabilities from the entry; secret when the entry uses a secret-valued option."""
    secret = bool(expr.names_in(entry) & secret_options)
    return replace(resource, run_before=entry.get("before"), run_after=entry.get("after"), provides=tuple(role.provides),
                   **({"secret": True} if secret else {}))


def _packages(role, ctx: dict, secrets: frozenset) -> list[Resource]:
    out: list[Resource] = []
    for i, entry in enumerate(role.packages):
        if not expr.truthy(entry.get("when"), ctx):
            continue
        fields = {k: expr.resolve(v, ctx) for k, v in entry.items() if k not in COMMON_KEYS}
        name = fields.pop("name", None)
        if name is None:
            raise BastetError(f"{role.name}: packages[{i}]: name resolved to nothing")
        fields = {k: v for k, v in fields.items() if v is not None}
        for n in name if isinstance(name, list) else [name]:
            out.append(placed(Package(name=str(n), **fields), role, entry, secrets))
    return out


def _users(role, ctx: dict, secrets: frozenset) -> list[Resource]:
    out: list[Resource] = []
    for entry in role.users:
        if not expr.truthy(entry.get("when"), ctx):
            continue
        kind = entry["kind"]
        resolved = {k: expr.resolve(v, ctx) for k, v in entry.items() if k not in COMMON_KEYS | {"kind"}}
        f = {k: tuple(v) if isinstance(v, list) else v for k, v in resolved.items() if v is not None}
        if kind == "user":
            made = User(**f)
        elif kind == "group":
            made = Group(**f)
        elif kind == "key":
            made = AuthorizedKey(**f)
        else:
            made = sudoer(f.pop("name"), **f)
        out.append(placed(made, role, entry, secrets))
    return out


def _systemd(role, ctx: dict, host, secrets: frozenset) -> list[Resource]:
    out: list[Resource] = []
    for entry in role.systemd:
        if not expr.truthy(entry.get("when"), ctx):
            continue
        kind = entry["kind"]
        f = {k: expr.resolve(v, ctx) for k, v in entry.items() if k not in COMMON_KEYS | {"kind"}}
        if kind == "unit":
            made = [Unit(name=f["name"], enabled=f.get("enabled"), state=f.get("state"))]
        elif kind == "time":
            if host.container:  # a container can't set the clock or NTP; only the timezone applies
                f = {k: v for k, v in f.items() if k not in ("ntp", "rtc_local")}
            made = [TimeSettings(**f)] if any(v is not None for v in f.values()) else []
        elif kind == "hostname":
            made = [] if host.container else [Hostname(name=str(f.get("name") or host.data.get("hostname") or host.name))]
        elif kind == "locale":
            made = [Locale(**f)] if any(v is not None for v in f.values()) else []
        else:
            made = [drop_in(f["unit"], f["name"], f["content"], restart_unit=f.get("restart", True))]
        out += [placed(r, role, entry, secrets) for r in made]
    return out


def triggers(entry: dict) -> dict:
    """The `restart`/`reload` unit lists of an entry as `on_change` triggers."""
    units = [restart(u) for u in entry.get("restart") or []] + [reload(u) for u in entry.get("reload") or []]
    return {"on_change": tuple(units)} if units else {}


def _text(role, entry: dict, i: int, key: str, ctx: dict) -> str:
    value = expr.resolve(entry[key], ctx)
    if value is None:
        raise BastetError(f"{role.name}: files[{i}]: {key} resolved to nothing")
    return str(value)


def build_files(role, ctx: dict, entry: dict, i: int, secrets: frozenset = frozenset()) -> list[Resource]:
    """One resource from a `files` entry that is not `edit` or `render`."""
    path, used = entry["path"], entry
    if "directory" in entry:
        made = Directory(path=path, owner=entry.get("owner"), group=entry.get("group"), mode=entry.get("mode"))
    elif "link" in entry:
        made = Symlink(path=path, target=_text(role, entry, i, "link", ctx))
    elif "line" in entry:
        made = Line(path=path, line=_text(role, entry, i, "line", ctx), match=entry.get("match"), unique=bool(entry.get("unique")),
                    validate=entry.get("validate"), **triggers(entry))
    elif "block" in entry:
        made = Block(path=path, block=_text(role, entry, i, "block", ctx), marker=entry["marker"], comment=entry.get("comment", "#"),
                     validate=entry.get("validate"), **triggers(entry))
    else:
        if "template" in entry:
            content = render_template(role.path.parent, entry["template"], ctx)
            try:  # a template that mentions a secret option makes its file secret
                used = {**entry, "template text": (role.path.parent / entry["template"]).read_text(encoding="utf-8")}
            except OSError:
                pass
        else:
            content = _text(role, entry, i, "content", ctx)
        made = File(path=path, content=content, owner=entry.get("owner"), group=entry.get("group"), mode=entry.get("mode"),
                    validate=entry.get("validate"), **triggers(entry))
    return [placed(made, role, used, secrets)]


def build_entries(role, values: dict, host, secret_options: frozenset = frozenset()) -> list[Resource]:
    ctx = expr.context(role.options, values, host)
    return [*_packages(role, ctx, secret_options), *_users(role, ctx, secret_options), *_systemd(role, ctx, host, secret_options)]
