from dataclasses import dataclass, field

from bastet.core.changes import Change
from bastet.core.facts import Extracted, propose_type
from bastet.core.factsnote import OBSERVED_BY_OTHERS, facts_change
from bastet.core.frontmatter import Document
from bastet.core.hosttypes import HostType
from bastet.core.inventory import Inventory
from bastet.core.units import same_value
from bastet.core.views import summary_embed


@dataclass
class Note:
    host: str
    severity: str
    message: str


@dataclass
class HostUpdate:
    change: Change | None
    notes: list[Note] = field(default_factory=list)
    facts: dict = field(default_factory=dict)


def plan_facts(
    doc: Document,
    ex: Extracted,
    host_type: HostType,
    inv: Inventory,
    *,
    hostkey: str | None,
    gathered: str,
    types: dict[str, HostType],
    existing: dict | None = None,
) -> HostUpdate:
    """Everything observed goes to the host's facts note; the host note itself is never written.

    A desired or yours field the host note declares differently from what was observed is an info
    note (drift, for `apply` to reconcile later); a type proposal and a missing summary embed are
    notes too. Facts have no attribution and no `--take`: the facts note is Bastet's, so it is simply
    replaced with what was observed.

    `existing` is what the facts note already holds, for keys the host's own gather never produces
    (`OBSERVED_BY_OTHERS`). It defaults to `inv.facts_for(doc.name)` (the note as last written), but a
    caller merging several sources into one facts note in a single run (gather.py) passes its own
    accumulator instead, so a vmid or link added earlier in the same run isn't lost here.
    """
    observed = dict(ex.facts)
    if hostkey:
        observed["ssh_host_key"] = hostkey
    if str(doc.data.get("ip", "")).strip().lower() == "dhcp":
        observed.pop("gateway", None)
        if isinstance(observed.get("interfaces"), list):
            observed["interfaces"] = [
                {k: v for k, v in i.items() if k != "addresses"} for i in observed["interfaces"] if isinstance(i, dict)
            ]
    baseline = inv.facts_for(doc.name) if existing is None else existing
    for key in OBSERVED_BY_OTHERS:  # never produced by the host's own gather; keep whatever is already there
        if key not in observed and key in baseline:
            observed[key] = baseline[key]

    notes: list[Note] = []
    for key, value in observed.items():
        nature = host_type.fields.get(key)
        if nature not in ("desired", "yours"):
            continue
        current = doc.data.get(key)
        if current is None or same_value(key, current, value):
            continue
        if nature == "yours":
            notes.append(Note(doc.name, "info", f"{key}: file says {current!r}, host reports {value!r}"))
        else:
            notes.append(Note(doc.name, "info", f"{key}: desired {current!r}, host has {value!r} (apply will handle desired fields later)"))

    proposal = propose_type(ex)
    current_type = doc.data.get("type")
    if proposal and current_type == "unknown":
        known = types.get(proposal)
        missing = [f for f in (known.minimal if known else []) if doc.data.get(f) in (None, "")]
        suffix = f" and add {', '.join(missing)}" if missing else ""
        notes.append(Note(doc.name, "info", f"this host looks like a {proposal}; set type: {proposal}{suffix}"))
    elif proposal and current_type and proposal != current_type:
        notes.append(Note(doc.name, "info", f"type is {current_type!r} but this host looks like a {proposal}"))

    if summary_embed(doc.name) not in doc.body:
        rel = doc.path.relative_to(inv.root).as_posix()
        notes.append(Note(
            doc.name, "info",
            f"{rel} has no summary embed; add {summary_embed(doc.name)} (bastet add host does this for new hosts)",
        ))

    change = facts_change(inv.root, doc.name, observed, gathered)
    return HostUpdate(change, notes, observed)
