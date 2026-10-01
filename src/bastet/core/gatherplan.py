from collections.abc import Callable
from dataclasses import dataclass, field

from bastet.core.attribution import last_setter
from bastet.core.changes import Change
from bastet.core.facts import Extracted, propose_type
from bastet.core.frontmatter import Document, set_keys
from bastet.core.gitrepo import BASTET_NAME, GitRepo
from bastet.core.hosttypes import HostType, load_host_types
from bastet.core.units import same_value
from bastet.core.views import HARDWARE_SECTION, ensure_page_embed, has_hardware_section, summary_embed

HARDWARE_KEYS = {"ram", "cpu", "cpu_cores", "cpu_threads", "storage"}


@dataclass
class Note:
    host: str
    severity: str
    message: str


@dataclass
class HostUpdate:
    change: Change | None
    notes: list[Note] = field(default_factory=list)


def merge_facts(
    doc: Document,
    observed: dict,
    repo: GitRepo,
    *,
    take: set[str],
    nature_of: Callable[[str], str | None],
    warn: Callable[[str], bool],
) -> tuple[dict, list[Note]]:
    """Per-field merge: desired fields reported, facts added or updated, hand-set values kept and attributed."""
    updates: dict[str, object] = {}
    notes: list[Note] = []
    for key, value in observed.items():
        nature = nature_of(key)
        current = doc.data.get(key)
        if nature == "desired":
            if current is not None and not same_value(key, current, value):
                notes.append(Note(doc.name, "info", f"{key}: desired {current!r}, host has {value!r} (apply will handle desired fields later)"))
            continue
        if nature != "fact":
            continue
        if current is None or key in take:
            if current is None or not same_value(key, current, value):
                updates[key] = value
            continue
        if same_value(key, current, value):
            continue
        setter = last_setter(repo, doc.path, key)
        if setter is not None and setter.author == BASTET_NAME:
            updates[key] = value
            continue
        who = setter.describe() if setter is not None else "set by you"
        notes.append(Note(
            doc.name, "warn" if warn(key) else "info",
            f"{key}: file says {current!r} ({who}), observed {value!r}; keeping yours. Use --take {key} to accept the observed value",
        ))
    return updates, notes


def plan_update(
    doc: Document,
    ex: Extracted,
    host_type: HostType,
    repo: GitRepo,
    *,
    take: set[str],
    hostkey: str | None,
    types: dict[str, HostType] | None = None,
) -> HostUpdate:
    text = doc.path.read_text(encoding="utf-8")
    observed = dict(ex.facts)
    if hostkey:
        observed["ssh_host_key"] = hostkey
    if str(doc.data.get("ip", "")).strip().lower() == "dhcp":
        observed.pop("gateway", None)
        if isinstance(observed.get("interfaces"), list):
            observed["interfaces"] = [
                {k: v for k, v in i.items() if k != "addresses"} for i in observed["interfaces"] if isinstance(i, dict)
            ]
    updates, notes = merge_facts(
        doc, observed, repo, take=take,
        nature_of=host_type.fields.get,
        warn=lambda key: host_type.physical and key in HARDWARE_KEYS,
    )
    if "gather" not in doc.data:
        updates["gather"] = True
    if "hostname" not in doc.data and ex.facts.get("hostname"):
        updates = {"hostname": ex.facts["hostname"], **updates}  # first, where it reads naturally

    proposal = propose_type(ex)
    current_type = doc.data.get("type")
    if proposal and current_type == "unknown":
        known = (types or load_host_types()).get(proposal)
        merged = {**doc.data, **updates}
        missing = [f for f in (known.minimal if known else []) if merged.get(f) in (None, "")]
        if missing:
            notes.append(Note(doc.name, "info", f"this host looks like a {proposal}; set type: {proposal} and add {', '.join(missing)}"))
        else:
            updates["type"] = proposal
    elif proposal and current_type and proposal != current_type:
        notes.append(Note(doc.name, "info", f"type is {current_type!r} but this host looks like a {proposal}"))

    new_text = set_keys(text, updates, doc.path) if updates else text
    new_text = ensure_page_embed(new_text, summary_embed(doc.name))
    if host_type.physical and not has_hardware_section(doc.body):
        new_text = new_text.rstrip("\n") + "\n" + HARDWARE_SECTION
    change = Change(doc.path, text, new_text) if new_text != text else None
    return HostUpdate(change, notes)
