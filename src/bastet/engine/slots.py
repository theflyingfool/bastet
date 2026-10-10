"""Where each entry runs: the blocks in order, and the exceptions an entry can ask for."""

from __future__ import annotations

from bastet.core.errors import BastetError

SLOTS = ("repositories", "packages", "users", "files", "systemd", "commands", "reports")
WANTS = {"repositories": ("package-manager",), "packages": ("package-manager",)}   # a block's "run these first, if any"


def _position(name: str, what: str) -> int:
    try:
        return SLOTS.index(name)
    except ValueError:
        raise BastetError(f"{what}: unknown block {name!r} (known: {', '.join(SLOTS)})") from None


def rank(res) -> float:
    """Position of an entry in the run: its block, or just before/after the block it names."""
    what = res.label
    base = float(SLOTS.index(res.slot))
    if res.run_before:
        return _position(res.run_before, f"{what}: before") - 0.5
    if res.run_after:
        return _position(res.run_after, f"{what}: after") + 0.5
    for capability in res.provides:
        for slot, wanted in WANTS.items():
            if capability in wanted:
                base = min(base, SLOTS.index(slot) - 0.5)
    return base


def apply_order(planned) -> list:
    """Every item of every batch in run order; ties keep batch order, then the order inside the batch."""
    keyed = [(rank(item.resource), b, i, item) for b, (_, items) in enumerate(planned) for i, item in enumerate(items)]
    keyed.sort(key=lambda k: k[:3])
    return [k[3] for k in keyed]
