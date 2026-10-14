from pathlib import Path

from bastet.core.hosttypes import load_host_types
from bastet.core.initialize import InitOptions, initialize
from bastet.core.inventory import load_inventory
from bastet.roles import notes
from bastet.roles.contract import load_roles
from bastet.roles.resolve import resolve

ROLES = load_roles()
TYPES = load_host_types()


def init(tmp_path: Path) -> Path:
    options = InitOptions(inventory=tmp_path / "Homelab", remote=None, key=None, bootstrap_user="alice",
                          lab_name="Homelab", domains={}, snippet=False, keep_days=None)
    initialize(tmp_path / "cfg" / "bastet.yml", options, keys_dir=tmp_path / "cfg" / "ssh")
    return tmp_path / "Homelab"


def test_role_note_text_is_what_add_role_wrote_before():
    assert notes.role_note_text("packages", ROLES["packages"], "Homelab") == (
        '---\nbastet: role\nrole: packages\napplies_to: "[[Homelab]]"\n---\n'
        "Docs: [[Using roles]] · Options: ![[packages role#Options]]\n\nNo values set; this role uses its defaults.\n")


def test_init_writes_the_lab_packages_note_once(tmp_path):
    lab = init(tmp_path)
    note = lab / "_roles" / "lab" / "packages.md"
    assert 'role: packages\napplies_to: "[[Homelab]]"' in note.read_text()
    note.write_text(note.read_text() + "install:\n  - tree\n")
    edited = note.read_text()
    initialize(tmp_path / "cfg" / "bastet.yml", InitOptions(
        inventory=lab, remote=None, key=None, bootstrap_user="alice", lab_name="Homelab", domains={}, snippet=False,
        keep_days=None), keys_dir=tmp_path / "cfg" / "ssh")
    assert note.read_text() == edited


def test_a_new_lab_resolves_packages_for_a_host_with_origin_lab(tmp_path):
    lab = init(tmp_path)
    (lab / "hosts").mkdir(exist_ok=True)
    (lab / "hosts" / "pve1.md").write_text("---\nbastet: host\ntype: proxmox\nip: 10.1.0.11\n---\n# pve1\n")
    inv = load_inventory(lab, TYPES)
    applied = {a.role.name: a for a in resolve(inv, inv.get("pve1"), TYPES, ROLES)}
    assert "packages" in applied and {s.label for s in applied["packages"].sources} == {"lab"}


def test_default_role_notes_never_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "HOST_ROLES", ("packages",))
    folder = tmp_path / "_roles" / "hosts" / "pve1"
    [change] = notes.default_role_notes("host", folder, "pve1", ROLES)
    assert change.path == folder / "packages.md" and change.before is None
    folder.mkdir(parents=True)
    (folder / "packages.md").write_text("mine")
    assert notes.default_role_notes("host", folder, "pve1", ROLES) == []

