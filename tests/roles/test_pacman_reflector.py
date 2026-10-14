import yaml

from bastet.core.factsnote import render_facts
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.engine.files import Settings
from bastet.engine.packages import Package
from bastet.engine.systemd import Unit
from bastet.roles.builtin import HostInfo, batches_for
from bastet.roles.contract import load_roles
from bastet.roles.resolve import resolve

ROLES = load_roles()
TYPES = load_host_types()


def build(tmp_path, values):
    """The resources and notes the pacman role builds for an Arch host that has a lab-level pacman note with `values`."""
    note = "---\n" + yaml.safe_dump({"bastet": "role", "role": "pacman", "applies_to": "[[Homelab]]", **values}) + "---\n"
    files = {"Homelab.md": "---\nbastet: lab\n---\n# Homelab\n",
             "hosts/vps1.md": "---\nbastet: host\ntype: vps\nprovider: linode\nip: 10.1.0.31\n---\n# vps1\n",
             "_bastet/facts/vps1 facts.md": render_facts("vps1", {"os": "Arch Linux"}, "2026-10-06T10:00:00Z"),
             "_roles/lab/pacman.md": note}
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    inv = load_inventory(tmp_path, TYPES)
    applied = [a for a in resolve(inv, inv.get("vps1"), TYPES, ROLES) if a.role.name == "pacman"]
    host = HostInfo(name="vps1", type="vps", data={"os": "Arch Linux"}, root=tmp_path, lab={})
    batches = batches_for(applied, host)
    return [r for b in batches for r in b.resources], [n for b in batches for n in b.notes]


def no_extract_lines(resources):
    [settings] = [r for r in resources if isinstance(r, Settings)]
    return [line for line in settings.lines if line.startswith("NoExtract")]


def test_no_options_install_reflector_and_start_its_timer(tmp_path):
    resources, _ = build(tmp_path, {})
    assert [r.name for r in resources if isinstance(r, Package)] == ["reflector"]
    assert any(isinstance(r, Unit) and r.name == "reflector.timer" and r.enabled and r.state == "up" for r in resources)


def test_reflector_false_emits_neither(tmp_path):
    resources, _ = build(tmp_path, {"reflector": False})
    assert not [r for r in resources if isinstance(r, Package)]
    assert not [r for r in resources if isinstance(r, Unit)]


def test_the_mirrorlist_is_protected_only_while_reflector_is_on(tmp_path):
    assert no_extract_lines(build(tmp_path / "on", {})[0]) == ["NoExtract = etc/pacman.d/mirrorlist"]
    assert no_extract_lines(build(tmp_path / "off", {"reflector": False})[0]) == []


def test_a_users_own_no_extract_is_kept_and_leaves_a_warning(tmp_path):
    resources, notes = build(tmp_path / "own", {"no_extract": ["usr/share/doc/*"]})
    assert no_extract_lines(resources) == ["NoExtract = usr/share/doc/*"]
    [note] = [n for n in notes if "mirrorlist" in n.message]
    assert note.level == "warning"
    assert not [n for n in build(tmp_path / "off", {"no_extract": ["usr/share/doc/*"], "reflector": False})[1] if "mirrorlist" in n.message]
    assert not [n for n in build(tmp_path / "both", {"no_extract": ["etc/pacman.d/mirrorlist"]})[1] if "mirrorlist" in n.message]
