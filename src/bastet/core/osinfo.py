"""Which OS a host runs, as a short id (arch, debian, …), from the `os` fact gather records."""

from __future__ import annotations

import re
from collections.abc import Mapping

ARCH_LIKE = ("arch", "manjaro", "endeavouros", "cachyos")
_KNOWN = (  # checked in order against the lowercased PRETTY_NAME
    ("linux mint", "mint"), ("opensuse", "opensuse"), ("endeavouros", "endeavouros"), ("cachyos", "cachyos"),
    ("arch", "arch"), ("debian", "debian"), ("ubuntu", "ubuntu"), ("fedora", "fedora"), ("alpine", "alpine"),
    ("rocky", "rocky"), ("almalinux", "almalinux"), ("manjaro", "manjaro"), ("raspbian", "raspbian"),
)


def os_id(data: Mapping) -> str | None:
    text = str(data.get("os") or "").strip().lower()
    if not text:
        return None
    for needle, ident in _KNOWN:
        if needle in text:
            return ident
    first = re.sub(r"[^a-z0-9]+", "-", text.split()[0]).strip("-")
    return first or None
