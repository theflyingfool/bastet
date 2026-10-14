from pathlib import Path

import pytest

from bastet.core.changes import write_changes
from bastet.core.factsnote import facts_path, render_facts
from bastet.core.gitrepo import GitRepo
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.render import generated_changes

TYPES = load_host_types()
FILES = {
    "Homelab.md": "---\nbastet: lab\n---\n# Homelab\n",
    "hosts/vps1.md": "---\nbastet: host\ntype: vps\nprovider: linode\nip: 203.0.113.10\n---\n# vps1\n",
}


@pytest.fixture
def root(tmp_path) -> Path:
    for rel, text in FILES.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    facts_path(tmp_path, "vps1").parent.mkdir(parents=True, exist_ok=True)
    facts_path(tmp_path, "vps1").write_text(render_facts("vps1", {"os": "Arch Linux"}, "2026-10-06T10:00:00Z"))
    GitRepo(tmp_path).init()
    return tmp_path


def refresh(root: Path) -> None:
    write_changes(generated_changes(load_inventory(root, TYPES), TYPES, GitRepo(root)))


def test_groups_are_copied_into_the_user_folder_and_nothing_goes_under_bastet(root):
    refresh(root)
    assert "match:\n  os: arch\n" in (root / "groups" / "arch.md").read_text()
    assert "match:\n  type: vps\n" in (root / "groups" / "vps.md").read_text()
    assert "generated: true" not in (root / "groups" / "arch.md").read_text()
    assert not (root / "_bastet" / "groups").exists()


def test_an_old_generated_group_is_replaced_and_the_type_named_copy_loads_clean(root):
    old = root / "_bastet" / "groups"
    old.mkdir(parents=True)
    (old / "arch.md").write_text("---\ngenerated: true\nbastet: group\nmatch:\n  os: arch\n---\nold\n")
    refresh(root)
    assert (root / "groups" / "arch.md").exists() and not (old / "arch.md").exists()
    inv = load_inventory(root, TYPES)
    assert not [p for p in inv.problems if "host type" in str(p)]


def test_a_user_edit_survives_the_next_refresh_byte_for_byte(root):
    refresh(root)
    copy = root / "groups" / "arch.md"
    copy.write_text(copy.read_text() + "\nMy own words.\n")
    edited = copy.read_text()
    refresh(root)
    assert copy.read_text() == edited


def test_a_user_note_of_that_name_elsewhere_is_never_overwritten(root):
    (root / "notes").mkdir()
    (root / "notes" / "arch.md").write_text("---\nbastet: group\nmatch:\n  os: arch\n---\nmine\n")
    refresh(root)
    assert not (root / "groups" / "arch.md").exists()
    assert (root / "notes" / "arch.md").read_text().endswith("mine\n")


def test_a_user_group_named_like_a_type_with_another_match_still_errors(root):
    (root / "groups").mkdir()
    (root / "groups" / "vps.md").write_text("---\nbastet: group\nmatch:\n  os: arch\n---\nmine\n")
    inv = load_inventory(root, TYPES)
    assert [p for p in inv.problems if "host type" in str(p)]


def test_a_copied_group_gets_the_default_group_notes(root):
    refresh(root)
    note = root / "_roles" / "groups" / "arch" / "base.md"
    assert 'applies_to: "[[arch]]"' in note.read_text()
    note.write_text("mine")
    refresh(root)
    assert note.read_text() == "mine"
