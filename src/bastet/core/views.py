from pathlib import Path

from bastet.core.changes import Change

HARDWARE_BASE_PATH = "_bastet/hardware-here.base"
HARDWARE_BASE = """filters:
  and:
    - installed_in == this
views:
  - type: table
    name: Hardware
    order:
      - file.name
      - category
      - model
      - serial
      - size
      - status
"""
HARDWARE_SECTION = "\n## Hardware\n\n![[hardware-here.base]]\n"


def ensure_views(root: Path) -> list[Change]:
    path = root / HARDWARE_BASE_PATH
    return [] if path.exists() else [Change(path, None, HARDWARE_BASE)]


def has_hardware_section(body: str) -> bool:
    return "hardware-here.base" in body or "\n## Hardware" in "\n" + body
