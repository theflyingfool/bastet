"""Block entries in a Markdown role file: packages, systemd, users and whole files, handed to the building blocks."""

from __future__ import annotations

import posixpath
import re
from dataclasses import replace
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.engine.files import Block, Directory, File, Line, Symlink
from bastet.engine.model import Resource, Trigger
from bastet.engine.packages import Package
from bastet.engine.run import Note
from bastet.engine.slots import SLOTS
from bastet.engine.systemd import (
    Hostname,
    Locale,
    TimeSettings,
    Unit,
    daemon_reload,
    drop_in,
    reload,
    restart,
)
from bastet.engine.templates import render_template
from bastet.engine.users import AuthorizedKey, Group, User, sudoer
from bastet.roles import expr

COMMON_KEYS = {"when", "before", "after", "each"}
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
BASTET_SUDOERS = "/etc/sudoers.d/bastet"
UNIT_STATES = ("up", "down")


def _fail(msg: str, path: Path, key: str) -> BastetError:
    return BastetError(msg, file=path, key=key)


def entry_names(entry: dict, options: dict, where: str, path: Path, key: str) -> set[str]:
    """The names an entry's `when:` and `{{ }}` may use: the options, plus `item` (and `key` for a map) under `each`."""
    allowed = set(options)
    if "each" not in entry:
        return allowed
    named = entry["each"]
    option = options.get(named) if isinstance(named, str) else None
    if option is None:
        raise _fail(f"{where}: each names no option: {named}", path, key)
    if option.type not in ("list", "map"):
        raise _fail(f"{where}: each: {named} must be a list or map option, not {option.type}", path, key)
    return allowed | {"item"} | ({"key"} if option.type == "map" else set())


def each_contexts(entry: dict, ctx: dict):
    """(item number, context) per item the entry applies to; one plain (None, context) without `each`.

    `when:` is judged per item. The item number only ever appears in error messages."""
    if "each" not in entry:
        if expr.truthy(entry.get("when"), ctx):
            yield None, ctx
        return
    value = ctx.get(entry["each"]) or ()
    pairs = [(None, v) for v in value] if isinstance(value, (list, tuple)) else list(value.items())
    for n, (key, item) in enumerate(pairs):
        item_ctx = {**ctx, "item": item, **({"key": key} if key is not None else {})}
        if expr.truthy(entry.get("when"), item_ctx):
            yield n, item_ctx


def build_each(role, entry: dict, where: str, ctx: dict, make) -> list[Resource]:
    """What `make(context)` builds for each item of the entry; two items building the same resource are refused."""
    out: list[Resource] = []
    seen: dict[str, int] = {}
    for n, item_ctx in each_contexts(entry, ctx):
        for resource in make(item_ctx):
            if n is not None and seen.setdefault(resource.identity, n) != n:
                raise BastetError(f"{role.name}: {where}: item {seen[resource.identity]} and item {n} (each: {entry['each']}) "
                                  f"both build {resource.label}")
            out.append(resource)
    return out


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


CHECK_KEYS = {"name", "when", "level", "message"}
CHECK_LEVELS = ("info", "warning", "error")


def parse_checks(path: Path, items: object, options: dict) -> list[dict]:
    if not isinstance(items, list):
        raise _fail("checks must be a list", path, "checks")
    allowed, out = set(options), []
    for i, entry in enumerate(items):
        where = f"checks[{i}]"
        if not isinstance(entry, dict):
            raise _fail(f"{where}: each check is a map", path, "checks")
        _unknown(entry, CHECK_KEYS, where, path)
        for need in ("when", "level", "message"):
            if not isinstance(entry.get(need), str) or not entry[need].strip():
                raise _fail(f"{where}: needs {need} (text)", path, "checks")
        if entry["level"] not in CHECK_LEVELS:
            raise _fail(f"{where}: level must be one of {', '.join(CHECK_LEVELS)}", path, "checks")
        if "name" in entry and not isinstance(entry["name"], str):
            raise _fail(f"{where}: name must be text", path, "checks")
        check_common({"when": entry["when"], "message": entry["message"]}, allowed, where, path, "checks")
        out.append(dict(entry))
    return out


def run_checks(role, ctx: dict) -> list[Note]:
    """The notes from the role's checks that hold; an `error` check that holds stops the host."""
    notes: list[Note] = []
    for check in role.checks:
        if not expr.truthy(check["when"], ctx):
            continue
        message = str(expr.resolve(check["message"], ctx))
        if check["level"] == "error":
            raise BastetError(f"{role.name}: {message}", file=role.path, key="checks")
        notes.append(Note(check["level"], role.name, message))
    return notes


def parse_packages(path: Path, items: object, options: dict) -> list[dict]:
    if not isinstance(items, list):
        raise _fail("packages must be a list", path, "packages")
    out = []
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
        check_common(entry, entry_names(entry, options, where, path, "packages"), where, path, "packages")
        out.append(dict(entry))
    return out


def parse_systemd(path: Path, items: object, options: dict) -> list[dict]:
    if not isinstance(items, list):
        raise _fail("systemd must be a list", path, "systemd")
    out = []
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
        check_common(entry, entry_names(entry, options, where, path, "systemd"), where, path, "systemd")
        out.append(dict(entry))
    return out


def parse_users(path: Path, items: object, options: dict) -> list[dict]:
    if not isinstance(items, list):
        raise _fail("users must be a list", path, "users")
    out = []
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
        check_common(entry, entry_names(entry, options, where, path, "users"), where, path, "users")
        out.append(dict(entry))
    return out


def placed(resource: Resource, role, entry: dict, secret_options: frozenset = frozenset()) -> Resource:
    """Order and capabilities from the entry; secret when the entry uses a secret-valued option."""
    secret = bool((expr.names_in(entry) | {entry.get("each")}) & secret_options)
    return replace(resource, run_before=entry.get("before"), run_after=entry.get("after"), provides=tuple(role.provides),
                   **({"secret": True} if secret else {}))


def _packages(role, ctx: dict, secrets: frozenset) -> list[Resource]:
    out: list[Resource] = []
    for i, entry in enumerate(role.packages):
        def make(c: dict, entry: dict = entry, i: int = i) -> list[Resource]:
            fields = {k: expr.resolve(v, c) for k, v in entry.items() if k not in COMMON_KEYS}
            name = fields.pop("name", None)
            if name is None:
                raise BastetError(f"{role.name}: packages[{i}]: name resolved to nothing")
            fields = {k: v for k, v in fields.items() if v is not None}
            names = name if isinstance(name, list) else [name]
            if any(n is None for n in names):
                raise BastetError(f"{role.name}: packages[{i}]: a name in the list resolved to nothing (an unset option?)")
            return [placed(Package(name=str(n), **fields), role, entry, secrets) for n in names]

        out += build_each(role, entry, f"packages[{i}]", ctx, make)
    return out


def _need(role, kind: str, where: str, f: dict, required: tuple[str, ...]) -> None:
    for field in required:
        if f.get(field) in (None, ""):
            raise BastetError(f"{role.name}: {where}: {kind}: {field} resolved to nothing")


def refuse_bastet_path(path: str, where: str) -> None:
    """Files that carry Bastet's own access (its sudoers rule and its authorized_keys) are not a role's to write."""
    clean = posixpath.normpath(path) if path.startswith("/") else path
    if clean == BASTET_SUDOERS or re.search(r"(^|/|~)bastet/\.ssh/authorized_keys$", clean):
        raise BastetError(f"{where}: {path} would lock Bastet out of this host; the bastet account is managed by Bastet itself")


def _guard_bastet(role, where: str, kind: str, f: dict) -> None:
    named = (f.get("user"),) if kind == "key" else (f.get("name"), f.get("user"))
    if BASTET_USER in named:
        raise BastetError(f"{role.name}: {where}: the bastet account is managed by Bastet itself")


def _users(role, ctx: dict, secrets: frozenset) -> list[Resource]:
    out: list[Resource] = []
    for i, entry in enumerate(role.users):
        kind, where = entry["kind"], f"users[{i}]"

        def make(c: dict, entry: dict = entry, kind: str = kind, where: str = where) -> list[Resource]:
            resolved = {k: expr.resolve(v, c) for k, v in entry.items() if k not in COMMON_KEYS | {"kind"}}
            f = {k: tuple(v) if isinstance(v, list) else v for k, v in resolved.items() if v is not None}
            _need(role, kind, where, f, USERS_REQUIRED[kind])
            _guard_bastet(role, where, kind, f)
            try:
                if kind == "user":
                    made = User(**f)
                elif kind == "group":
                    made = Group(**f)
                elif kind == "key":
                    made = AuthorizedKey(**f)
                else:
                    made = sudoer(f.pop("name"), **f)
            except (TypeError, ValueError) as exc:
                raise BastetError(f"{role.name}: {where}: {exc}") from None
            return [placed(made, role, entry, secrets)]

        out += build_each(role, entry, where, ctx, make)
    return out


CONTAINER_TIME_NOTE = "time: the clock and NTP settings of a container come from its Proxmox node; only the time zone is applied"
CONTAINER_HOSTNAME_NOTE = "hostname: the hostname of a container comes from its Proxmox node; not changed"


def _systemd(role, ctx: dict, host, secrets: frozenset, notes: list[Note]) -> list[Resource]:
    out: list[Resource] = []
    for i, entry in enumerate(role.systemd):
        out += build_each(role, entry, f"systemd[{i}]", ctx,
                          lambda c, entry=entry, i=i: _systemd_entry(role, c, host, secrets, notes, entry, i))
    return out


def _systemd_entry(role, ctx: dict, host, secrets: frozenset, notes: list[Note], entry: dict, i: int) -> list[Resource]:
    kind = entry["kind"]
    f = {k: expr.resolve(v, ctx) for k, v in entry.items() if k not in COMMON_KEYS | {"kind"}}
    _need(role, kind, f"systemd[{i}]", f, SYSTEMD_REQUIRED.get(kind, ()))
    if kind == "unit":
        if f.get("state") not in (None, *UNIT_STATES):
            raise BastetError(f"{role.name}: systemd[{i}]: state resolved to {f['state']!r}; it must be up or down")
        if f.get("enabled") not in (None, True, False):
            raise BastetError(f"{role.name}: systemd[{i}]: enabled resolved to {f['enabled']!r}; it must be true or false")
        made = [Unit(name=str(f["name"]), enabled=f.get("enabled"), state=f.get("state"))]
    elif kind == "time":
        if host.container:  # a container can't set the clock or NTP; only the timezone applies
            if any(f.get(k) is not None for k in ("ntp", "rtc_local")):
                notes.append(Note("info", role.name, CONTAINER_TIME_NOTE))
            f = {k: v for k, v in f.items() if k not in ("ntp", "rtc_local")}
        made = [TimeSettings(**f)] if any(v is not None for v in f.values()) else []
    elif kind == "hostname":
        if host.container:
            notes.append(Note("info", role.name, CONTAINER_HOSTNAME_NOTE))
        made = [] if host.container else [Hostname(name=str(f.get("name") or host.data.get("hostname") or host.name))]
    elif kind == "locale":
        made = [Locale(**f)] if any(v is not None for v in f.values()) else []
    else:
        restart_unit = True if f.get("restart") is None else bool(f["restart"])  # unset means the default
        made = [drop_in(str(f["unit"]), str(f["name"]), str(f["content"]), restart_unit=restart_unit)]
    return [placed(r, role, entry, secrets) for r in made]


def triggers(entry: dict) -> dict:
    """The `restart`/`reload` unit lists of a resolved entry as `on_change` triggers."""
    units = [daemon_reload()] if entry.get("daemon_reload") else []
    units += [restart(u) for u in entry.get("restart") or [] if u] + [reload(u) for u in entry.get("reload") or [] if u]
    units += [Trigger(label=c["name"], command=c["run"], order=60) for c in entry.get("on_change") or []]
    return {"on_change": tuple(units)} if units else {}


UNRESOLVED_KEYS = COMMON_KEYS | {"edit", "render", "backup", "template", "unique", "directory"}


def resolved_files_entry(role, entry: dict, i: int, ctx: dict) -> dict:
    """The fields of a `files` entry with their `{{ }}` filled in; optional ones that come out unset are dropped."""
    r = {k: expr.resolve(v, ctx) for k, v in entry.items() if k not in UNRESOLVED_KEYS}
    if r.get("path") in (None, ""):
        raise BastetError(f"{role.name}: files[{i}]: path resolved to nothing")
    r["path"] = str(r["path"])
    refuse_bastet_path(r["path"], f"{role.name}: files[{i}]")
    return {k: v for k, v in r.items() if v is not None}


def _text(role, r: dict, i: int, key: str) -> str:
    if r.get(key) is None:
        raise BastetError(f"{role.name}: files[{i}]: {key} resolved to nothing")
    return str(r[key])


def build_files(role, ctx: dict, entry: dict, i: int, secrets: frozenset = frozenset(), r: dict | None = None) -> list[Resource]:
    """One resource from a `files` entry that is not `edit` or `render`."""
    r = resolved_files_entry(role, entry, i, ctx) if r is None else r
    path, used = r["path"], entry
    if "directory" in entry:
        made = Directory(path=path, owner=r.get("owner"), group=r.get("group"), mode=r.get("mode"))
    elif "link" in entry:
        made = Symlink(path=path, target=_text(role, r, i, "link"))
    elif "line" in entry:
        made = Line(path=path, line=_text(role, r, i, "line"), match=r.get("match"), unique=bool(entry.get("unique")),
                    validate=r.get("validate"), **triggers(r))
    elif "block" in entry:
        made = Block(path=path, block=_text(role, r, i, "block"), marker=_text(role, r, i, "marker"), comment=r.get("comment", "#"),
                     validate=r.get("validate"), **triggers(r))
    else:
        if "template" in entry:
            content = render_template(role.path.parent, entry["template"], ctx, sandbox=True)
            try:  # a template that mentions a secret option makes its file secret
                used = {**entry, "template text": (role.path.parent / entry["template"]).read_text(encoding="utf-8")}
            except OSError:
                pass
        else:
            content = _text(role, r, i, "content")
        made = File(path=path, content=content, owner=r.get("owner"), group=r.get("group"), mode=r.get("mode"),
                    validate=r.get("validate"), **triggers(r))
    return [placed(made, role, used, secrets)]


def build_entries(role, ctx: dict, host, secret_options: frozenset = frozenset(), notes: list[Note] | None = None) -> list[Resource]:
    notes = [] if notes is None else notes
    return [*_packages(role, ctx, secret_options), *_users(role, ctx, secret_options),
            *_systemd(role, ctx, host, secret_options, notes)]
