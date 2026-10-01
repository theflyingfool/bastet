"""Bastet-owned Obsidian views (Bases) and the page sections that embed them."""

from pathlib import Path

from bastet.core.changes import Change

HOST_COLUMNS = (
    "type", "os", "ip", "address", "cpu", "cpu_cores", "cpu_threads", "ram", "storage",
    "chassis", "virtualization", "runs_on", "location",
)
HARDWARE_COLUMNS = (
    "category", "make", "model", "serial", "size", "media", "interface", "health", "pool",
    "memory_slots", "bios", "oob_address", "slot", "driver", "status", "installed_in",
    "location", "purchased", "warranty_until",
)
HARDWARE_LIST_COLUMNS = ("file.name", "category", "model", "serial", "size", "status")


def _yaml_list(items: tuple[str, ...], indent: str = "      ") -> str:
    return "".join(f"{indent}- {item}\n" for item in items)


def _base(filter_expr: str, views: list[tuple[str, str, tuple[str, ...]]]) -> str:
    """A .base file: one filter, then views in order (the first is the one shown by default)."""
    text = f"filters:\n  and:\n    - {filter_expr}\nviews:\n"
    for view_type, name, columns in views:
        text += f"  - type: {view_type}\n    name: {name}\n    order:\n" + _yaml_list(columns)
    return text


HARDWARE_BASE_PATH = "_bastet/hardware-here.base"
HOST_SUMMARY_BASE_PATH = "_bastet/host-summary.base"
HARDWARE_SUMMARY_BASE_PATH = "_bastet/hardware-summary.base"

HARDWARE_BASE = _base(
    "installed_in == this",
    [("cards", "Cards", HARDWARE_LIST_COLUMNS), ("table", "Table", HARDWARE_LIST_COLUMNS)],
)
HOST_SUMMARY_BASE = _base(
    "file.path == this.file.path",
    [("cards", "Summary", HOST_COLUMNS), ("table", "Table", HOST_COLUMNS)],
)
HARDWARE_SUMMARY_BASE = _base(
    "file.path == this.file.path",
    [("cards", "Summary", HARDWARE_COLUMNS), ("table", "Table", HARDWARE_COLUMNS)],
)

VIEWS = {
    HARDWARE_BASE_PATH: HARDWARE_BASE,
    HOST_SUMMARY_BASE_PATH: HOST_SUMMARY_BASE,
    HARDWARE_SUMMARY_BASE_PATH: HARDWARE_SUMMARY_BASE,
}

HARDWARE_SECTION = "\n## Hardware\n\n![[hardware-here.base]]\n"
HOST_SUMMARY_SECTION = "\n## Summary\n\n![[host-summary.base]]\n"
HARDWARE_SUMMARY_SECTION = "\n## Summary\n\n![[hardware-summary.base]]\n"


def ensure_views(root: Path) -> list[Change]:
    """Create missing views and refresh outdated ones; files under _bastet/ belong to Bastet."""
    changes = []
    for rel, content in VIEWS.items():
        path = root / rel
        before = path.read_text(encoding="utf-8") if path.exists() else None
        if before != content:
            changes.append(Change(path, before, content))
    return changes


def has_hardware_section(body: str) -> bool:
    return "hardware-here.base" in body or "\n## Hardware" in "\n" + body


def insert_after_title(text: str, section: str) -> str:
    """Insert `section` right after the first `# ` heading below the frontmatter (or at the top of the body)."""
    lines = text.split("\n")
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    insert_at = start
    for i in range(start, len(lines)):
        if lines[i].startswith("# "):
            insert_at = i + 1
            break
    block = section.strip("\n").split("\n")
    tail = [""] if insert_at < len(lines) and lines[insert_at].strip() else []
    return "\n".join(lines[:insert_at] + [""] + block + tail + lines[insert_at:])
