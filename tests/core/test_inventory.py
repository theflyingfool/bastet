from pathlib import Path

from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory

TYPES = load_host_types()


def put(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def host(name: str, extra: str = "") -> str:
    return f"---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.{len(name)}\n{extra}---\n# {name}\n"


def test_loads_kinds_and_ignores_other_notes(tmp_path):
    put(tmp_path, "Homelab.md", "---\nbastet: lab\nname: Homelab\n---\n")
    put(tmp_path, "hosts/pve1.md", host("pve1"))
    put(tmp_path, "notes/todo.md", "# just a note\n")
    put(tmp_path, "notes/tagged.md", "---\ntags: [x]\n---\n")
    put(tmp_path, ".obsidian/x.md", "---\nbastet: host\n---\n")
    inv = load_inventory(tmp_path, TYPES)
    assert sorted(inv.objects) == ["homelab", "pve1"]
    assert inv.lab.name == "Homelab"
    assert inv.problems == []


def test_unknown_kind_is_error_with_line(tmp_path):
    put(tmp_path, "x.md", "---\ntitle: x\nbastet: hots\n---\n")
    inv = load_inventory(tmp_path, TYPES)
    [p] = inv.errors
    assert p.error.key == "bastet" and p.error.line == 3


def test_case_insensitive_duplicates(tmp_path):
    put(tmp_path, "hosts/pve1.md", host("pve1"))
    put(tmp_path, "other/PVE1.md", host("PVE1"))
    inv = load_inventory(tmp_path, TYPES)
    assert len(inv.errors) == 1
    assert "duplicate" in inv.errors[0].error.message
    assert inv.get("Pve1") is not None


def test_host_type_checks(tmp_path):
    put(tmp_path, "a.md", "---\nbastet: host\n---\n")
    put(tmp_path, "b.md", "---\nbastet: host\ntype: vpz\n---\n")
    put(tmp_path, "c.md", "---\nbastet: host\ntype: vps\nip: 203.0.113.10\n---\n")
    inv = load_inventory(tmp_path, TYPES)
    messages = sorted(p.error.message for p in inv.errors)
    assert any("missing 'type'" in m for m in messages)
    assert any("unknown host type 'vpz'" in m for m in messages)
    assert any("needs 'provider'" in m for m in messages)


def test_dangling_link_is_warning(tmp_path):
    put(tmp_path, "hosts/pve1.md", host("pve1", 'location: "[[Closet]]"\n'))
    inv = load_inventory(tmp_path, TYPES)
    assert inv.errors == []
    [w] = inv.problems
    assert w.severity == "warning" and "Closet" in w.error.message and w.error.key == "location"


def test_link_field_must_be_a_link(tmp_path):
    put(tmp_path, "hw.md", "---\nbastet: hardware\ncategory: drive\ninstalled_in: pve1\n---\n")
    inv = load_inventory(tmp_path, TYPES)
    assert any("link" in p.error.message for p in inv.errors)


def test_duplicate_ip_is_error(tmp_path):
    put(tmp_path, "a.md", "---\nbastet: host\ntype: server\nip: 10.0.10.5\n---\n")
    put(tmp_path, "b.md", "---\nbastet: host\ntype: server\nip: 10.0.10.5/24\n---\n")
    inv = load_inventory(tmp_path, TYPES)
    assert any("10.0.10.5" in p.error.message for p in inv.errors)


def test_dhcp_hosts_dont_clash(tmp_path):
    put(tmp_path, "a.md", "---\nbastet: host\ntype: laptop\nip: dhcp\naddress: laptop.local\n---\n")
    put(tmp_path, "b.md", "---\nbastet: host\ntype: laptop\nip: dhcp\n---\n")
    put(tmp_path, "c.md", "---\nbastet: host\ntype: laptop\nip: not-an-ip\n---\n")
    inv = load_inventory(tmp_path, TYPES)
    assert [p.error.file.name for p in inv.errors] == ["c.md"]


def test_hardware_checks(tmp_path):
    put(tmp_path, "a.md", "---\nbastet: hardware\n---\n")
    put(tmp_path, "b.md", "---\nbastet: hardware\ncategory: drive\nstatus: broken\n---\n")
    inv = load_inventory(tmp_path, TYPES)
    messages = " ".join(p.error.message for p in inv.errors)
    assert "missing 'category'" in messages and "status 'broken'" in messages


def test_two_lab_files(tmp_path):
    put(tmp_path, "Homelab.md", "---\nbastet: lab\n---\n")
    put(tmp_path, "Other.md", "---\nbastet: lab\n---\n")
    assert any("more than one lab" in p.error.message for p in load_inventory(tmp_path, TYPES).errors)


def test_linking_to(tmp_path):
    put(tmp_path, "hosts/pve1.md", host("pve1", 'groups:\n  - "[[pvenodes]]"\n'))
    put(tmp_path, "groups/pvenodes.md", "---\nbastet: group\n---\n")
    put(tmp_path, "hardware/d1.md", '---\nbastet: hardware\ncategory: drive\ninstalled_in: "[[PVE1]]"\n---\n')
    inv = load_inventory(tmp_path, TYPES)
    assert [(d.name, k) for d, k in inv.linking_to("pve1")] == [("d1", "installed_in")]
    assert [(d.name, k) for d, k in inv.linking_to("pvenodes")] == [("pve1", "groups")]


def test_broken_yaml_is_a_warning_not_an_error(tmp_path):
    put(tmp_path, "notes/mine.md", "---\ntitle: [oops\n---\n")
    put(tmp_path, "hosts/pve1.md", host("pve1"))
    inv = load_inventory(tmp_path, TYPES)
    assert inv.errors == []
    assert inv.problems[0].severity == "warning"
    assert inv.get("pve1") is not None


def test_connection_must_be_local_or_ssh(tmp_path):
    put(tmp_path, "a.md", "---\nbastet: host\ntype: laptop\nconnection: local\n---\n")
    put(tmp_path, "b.md", "---\nbastet: host\ntype: laptop\nconnection: telnet\n---\n")
    inv = load_inventory(tmp_path, TYPES)
    [p] = inv.errors
    assert p.error.key == "connection" and "telnet" in p.error.message


def test_user_note_wins_over_generated_group(tmp_path):
    from bastet.core.hosttypes import load_host_types
    from bastet.core.inventory import load_inventory
    (tmp_path / "Homelab.md").write_text("---\nbastet: lab\n---\n# L\n")
    (tmp_path / "_bastet" / "groups").mkdir(parents=True)
    (tmp_path / "_bastet" / "groups" / "debian.md").write_text("---\nbastet: group\nmatch:\n  os: debian\n---\n# debian\n")
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "debian.md").write_text("---\nbastet: host\ntype: laptop\n---\n# debian\n")
    inv = load_inventory(tmp_path, load_host_types())
    assert inv.get("debian").data["bastet"] == "host"
    assert not any("duplicate" in str(p) for p in inv.problems)


def test_secret_notes_are_collected_separately(tmp_path):
    put(tmp_path, "_secrets/git1/gitea/admin_password.md", "---\nbastet: secret\n---\n")
    put(tmp_path, "_secrets/db1/postgres/admin_password.md", "---\nbastet: secret\n---\n")
    inv = load_inventory(tmp_path, TYPES)
    assert inv.problems == []
    assert len(inv.secrets) == 2
    assert "admin_password" not in inv.objects
