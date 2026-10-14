from pathlib import Path

import yaml

from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.roles.contract import load_roles
from bastet.roles.pages import resolved_table
from bastet.roles.resolve import resolve

TYPES = load_host_types()
BASE = {"bastet": "role-definition", "version": "1.0.0", "api": 0}
REBOOT = {"type": "string", "description": "when to reboot", "choices": ["never", "ask", "auto"]}


def write_role(directory: Path, name: str, options: dict, **extra) -> None:
    folder = directory / name
    folder.mkdir(parents=True, exist_ok=True)
    data = {**BASE, "name": name, "description": f"The {name} role", "options": options, **extra}
    (folder / f"{name} role.md").write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\nNotes.\n")


def note(root: Path, rel: str, role: str, target: str, **values) -> None:
    p = root / "_roles" / rel / f"{role}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\n" + yaml.safe_dump({"bastet": "role", "role": role, "applies_to": f"[[{target}]]", **values}) + "---\n")


def lab(tmp_path: Path, notes: list[tuple], target_extra: dict | None = None):
    """A lab with one host (media01) and the roles `target` (reboot) and `manager` (reboot supersedes it, plus mode)."""
    files = {"Homelab.md": "---\nbastet: lab\n---\n# Homelab\n",
             "hosts/media01.md": "---\nbastet: host\ntype: proxmox\nip: 10.1.0.21\n---\n# media01\n"}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    roles_dir = tmp_path / "shipped"
    write_role(roles_dir, "target", {"reboot": REBOOT}, **(target_extra or {}))
    write_role(roles_dir, "manager", {"reboot": {"supersedes": "target.reboot"}, "mode": {"type": "string"}})
    for args in notes:
        rel, role, target, values = args
        note(tmp_path, rel, role, target, **values)
    inv = load_inventory(tmp_path, TYPES)
    roles = load_roles(roles_dir)
    return inv, roles, {a.role.name: a for a in resolve(inv, inv.get("media01"), TYPES, roles)}


LAB_TARGET = ("lab", "target", "Homelab", {"reboot": "ask"})
LAB_MANAGER = ("lab", "manager", "Homelab", {"reboot": "auto"})


def test_the_manager_value_wins_a_tie_with_the_lab_note(tmp_path):
    _, _, a = lab(tmp_path, [LAB_TARGET, LAB_MANAGER])
    assert a["target"].values["reboot"] == "auto" and a["target"].origins["reboot"] == "lab, manager"


def test_a_host_note_on_the_target_beats_a_lab_note_on_the_manager(tmp_path):
    _, _, a = lab(tmp_path, [LAB_MANAGER, ("hosts/media01", "target", "media01", {"reboot": "never"})])
    assert a["target"].values["reboot"] == "never" and a["target"].origins["reboot"] == "host media01"


def test_an_unset_manager_option_changes_nothing(tmp_path):
    _, _, a = lab(tmp_path, [LAB_TARGET, ("lab", "manager", "Homelab", {"mode": "x"})])
    assert a["target"].values["reboot"] == "ask" and a["target"].origins["reboot"] == "lab"


def test_the_target_is_applied_when_it_has_no_note(tmp_path):
    _, _, a = lab(tmp_path, [LAB_MANAGER])
    assert a["target"].values["reboot"] == "auto" and a["target"].origins["reboot"] == "lab, manager"


def test_the_resolved_table_shows_the_effective_value_and_its_origin(tmp_path):
    inv, roles, a = lab(tmp_path, [("lab", "target", "Homelab", {"reboot": "ask"}),
                                   ("hosts/media01", "manager", "media01", {"reboot": "never"})])
    rows = [line for line in resolved_table(list(a.values())).splitlines() if "| reboot |" in line]
    assert len(rows) == 2 and all("never" in r and "host media01, manager" in r for r in rows)


def test_a_role_override_that_clears_the_option_wins_over_supersedes(tmp_path):
    clear = [{"when": "true", "reboot": None}]
    _, _, a = lab(tmp_path, [LAB_TARGET, LAB_MANAGER], target_extra={"overrides": clear})
    assert "reboot" not in a["target"].values or a["target"].values["reboot"] is None
