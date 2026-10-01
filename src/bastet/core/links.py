import re

LINK = re.compile(r"^\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]$")


def link_target(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    m = LINK.match(value.strip())
    if not m:
        return None
    return m.group(1).strip().rsplit("/", 1)[-1]


def make_link(name: str) -> str:
    return f"[[{name}]]"
