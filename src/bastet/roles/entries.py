"""Block entries in a Markdown role file: packages, systemd, users and whole files, handed to the building blocks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from bastet.core.errors import BastetError
from bastet.engine.model import Resource
from bastet.engine.packages import Package
from bastet.engine.slots import SLOTS
from bastet.roles import expr

COMMON_KEYS = {"when", "before", "after"}
PACKAGE_KEYS = {"name", "state", "version", "aur", "purge"} | COMMON_KEYS


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


def build_entries(role, values: dict, host, secret_options: frozenset = frozenset()) -> list[Resource]:
    ctx = expr.context(role.options, values, host)
    return [*_packages(role, ctx, secret_options)]
