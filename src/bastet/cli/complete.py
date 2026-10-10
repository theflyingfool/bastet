"""Tab completion helpers for the Bastet CLI: hosts, roles and secret paths, all read from the
inventory with no network and no git operations. Every function returns [] rather than raising,
since a completion that can't load the inventory should just offer nothing.
"""

from __future__ import annotations

import typer


def _inventory():
    """The inventory and its host types, loaded quietly -- None on any error (e.g. no inventory yet)."""
    try:
        from bastet.core.config import config_path, data_dir, inventory_dir, load_config
        from bastet.core.hosttypes import load_host_types
        from bastet.core.inventory import load_inventory

        config = load_config(config_path())
        types = load_host_types()
        root = inventory_dir(config, data_dir())
        inv = load_inventory(root, types)
        return inv, types
    except Exception:
        return None, None


def complete_hosts(ctx: typer.Context, incomplete: str) -> list[str]:
    """Complete host names, plus `@group`, `@type` and `@lab` selectors (for `run`/`show`)."""
    try:
        inv, types = _inventory()
        if inv is None:
            return []
        candidates = [doc.name for doc in inv.of_kind("host")]
        candidates += [f"@{group.name}" for group in inv.of_kind("group")]
        candidates += [f"@{name}" for name in types]
        candidates.append("@lab")
        return [c for c in candidates if c.startswith(incomplete)]
    except Exception:
        return []


def complete_roles(ctx: typer.Context, incomplete: str) -> list[str]:
    """Complete role names (for `add role`)."""
    try:
        from bastet.roles.contract import load_roles

        return sorted(name for name in load_roles() if name.startswith(incomplete))
    except Exception:
        return []


def _secret_hosts(incomplete: str) -> list[str]:
    inv, _types = _inventory()
    if inv is None:
        return []
    candidates = [doc.name for doc in inv.of_kind("host")]
    candidates.append("lab")
    return [c for c in candidates if c.startswith(incomplete)]


def _secret_roles(host: str, incomplete: str) -> list[str]:
    try:
        from bastet.roles.contract import load_roles
    except Exception:
        return []
    roles = load_roles()
    if host.lower() == "lab":
        # every role can reach the lab; offer the whole library
        return sorted(name for name in roles if name.startswith(incomplete))
    inv, types = _inventory()
    if inv is None:
        return []
    doc = inv.get(host)
    if doc is None or doc.data.get("bastet") not in ("host", "group"):
        return []
    from bastet.core.errors import BastetError
    from bastet.roles.resolve import resolve

    try:
        applied = resolve(inv, doc, types, roles) if doc.data.get("bastet") == "host" else []
    except BastetError:
        return []
    names = sorted({a.role.name for a in applied}) if applied else sorted(roles)
    return [n for n in names if n.startswith(incomplete)]


def _secret_options(role: str, incomplete: str) -> list[str]:
    try:
        from bastet.roles.contract import load_roles
    except Exception:
        return []
    role_def = load_roles().get(role)
    if role_def is None:
        return []
    return sorted(name for name in role_def.options if name.startswith(incomplete))


def complete_secret_words(ctx: typer.Context, args: list[str], incomplete: str) -> list[str]:
    """Complete `secret set`/`secret show`'s `host role option` words, one at a time: host names
    (and `lab`) first, then the roles that reach the chosen host, then that role's options.
    """
    try:
        words = list(ctx.params.get("words") or ())
    except Exception:
        words = []
    if len(words) == 0:
        return _secret_hosts(incomplete)
    if len(words) == 1:
        return _secret_roles(words[0], incomplete)
    if len(words) == 2:
        return _secret_options(words[1], incomplete)
    return []
