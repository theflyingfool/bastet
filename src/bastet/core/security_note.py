"""The security section of a host's facts note, written by `bastet run -c`/`-a`.

Rewritten in place by the run command, which replaces only the part of the note's body after
`SECURITY_MARKER` -- the frontmatter and sections 1-3 (cards, warnings, roles table) are someone
else's and stay untouched.
"""

from __future__ import annotations

from bastet.core.factsnote import SECURITY_MARKER
from bastet.engine.security import REPORTS


def security_items(items) -> list:
    return [i for i in items if hasattr(i.resource, "security_section")]


def security_section(items, when: str) -> str:
    order = {cls: n for n, cls in enumerate(REPORTS)}
    parts = [SECURITY_MARKER, f"\nSecurity, refreshed by `bastet run -c`/`-a`. Checked {when}.\n"]
    for item in sorted(security_items(items), key=lambda i: order.get(type(i.resource), len(order))):
        res = item.resource
        if item.status in ("failed", "skipped") or not item.current:
            parts.append(f"\n## {res.title}\n\n_not read: {item.error or 'no result'}_\n")
        else:
            parts.append("\n" + res.security_section(item.current))
    return "".join(parts)
