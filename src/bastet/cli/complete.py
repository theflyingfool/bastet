"""Tab completion helpers for Bastet CLI."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import typer


def _load_inventory_for_completion():
    """Load the inventory quietly, returning None on any error."""
    try:
        from bastet.core.config import inventory_dir, load_config
        from bastet.core.inventory import load_inventory
        from bastet.core.hosttypes import load_host_types

        config = load_config()
        inv = load_inventory(inventory_dir(), load_host_types())
        return inv
    except Exception:
        return None


def complete_hosts(ctx: "typer.Context", incomplete: str) -> list[str]:
    """Complete host names, @groups, @types, and @lab selector."""
    try:
        inv = _load_inventory_for_completion()
        if inv is None:
            return []

        candidates = []

        # Add host names
        for doc in inv.all():
            if doc.data.get("bastet") == "host":
                candidates.append(doc.name)

        # Add @group selectors
        for group in inv.of_kind("group"):
            candidates.append(f"@{group.name}")

        # Add @type selectors
        from bastet.core.hosttypes import load_host_types
        from bastet.core.config import load_config
        config = load_config()
        types = load_host_types()
        for tname in types:
            candidates.append(f"@{tname}")

        # Add @lab selector
        candidates.append("@lab")

        # Filter by incomplete prefix
        return [c for c in candidates if c.startswith(incomplete)]
    except Exception:
        return []


def complete_roles(ctx: "typer.Context", incomplete: str) -> list[str]:
    """Complete role names."""
    try:
        from bastet.roles.contract import load_roles
        roles = load_roles()
        return [name for name in roles if name.startswith(incomplete)]
    except Exception:
        return []


def complete_hosts_for_secret(ctx: "typer.Context", incomplete: str) -> list[str]:
    """Complete host names for secret set/show commands."""
    return complete_hosts(ctx, incomplete)


def complete_roles_for_secret(ctx: "typer.Context", incomplete: str) -> list[str]:
    """Complete role names for secret set/show commands."""
    try:
        # Get the host from params if available
        host_name = ctx.params.get("host")
        if not host_name:
            return []

        inv = _load_inventory_for_completion()
        if inv is None:
            return []

        # Load the host's roles
        host_doc = inv.get(host_name)
        if host_doc is None or host_doc.data.get("bastet") != "host":
            return []

        from bastet.roles.resolve import roles_for
        from bastet.roles.contract import load_roles
        roles_defs = load_roles()
        roles = roles_for(host_doc.data, roles_defs)

        return [name for name in roles if name.startswith(incomplete)]
    except Exception:
        return []


def complete_options_for_secret(ctx: "typer.Context", incomplete: str) -> list[str]:
    """Complete option names for secret set/show commands."""
    try:
        # Get host and role from params
        host_name = ctx.params.get("host")
        role_name = ctx.params.get("role")

        if not host_name or not role_name:
            return []

        from bastet.roles.contract import load_roles
        roles_defs = load_roles()

        if role_name not in roles_defs:
            return []

        role_def = roles_defs[role_name]
        return [name for name in role_def.options if name.startswith(incomplete)]
    except Exception:
        return []
