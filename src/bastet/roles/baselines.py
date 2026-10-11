"""Package baselines: the packages a provider's stock image ships with.

Shipped program data (`data/baselines/<provider>-<os>.txt`), used only as an allowance for the
unaccounted-packages report; nothing in a baseline is installed or managed.
"""
import re
from importlib import resources

from bastet.core.osinfo import ARCH_LIKE

PROVIDER = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def baseline_for(host) -> tuple[str, ...]:
    """The stock-image package names for the host's provider and OS, or () when none is shipped."""
    provider = str(host.data.get("provider") or "").strip().lower()
    if not PROVIDER.match(provider):
        return ()
    if host.os_id in ARCH_LIKE:
        family = "arch"
    elif host.debian_like:
        family = "debian"
    else:
        return ()
    path = resources.files("bastet") / "data" / "baselines" / f"{provider}-{family}.txt"
    if not path.is_file():
        return ()
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return tuple(line for line in lines if line and not line.startswith("#"))
