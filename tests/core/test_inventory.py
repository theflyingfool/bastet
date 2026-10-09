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
    return f"---\nbastet: host\ntype: proxmox\nip: 10.0.10.{len(name)}\n{extra}---\n# {name}\n"


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


def test_facts_note_indexed_by_host_without_colliding(tmp_path):
    put(tmp_path, "hosts/pve1.md", host("pve1"))
    put(
        tmp_path,
        "_bastet/facts/pve1 facts.md",
        '---\nbastet: facts\nhost: "[[pve1]]"\ngathered: now\nos: Debian 13\n---\n',
    )
    inv = load_inventory(tmp_path, TYPES)
    assert inv.problems == []
    assert inv.get("pve1").path == tmp_path / "hosts" / "pve1.md"
    assert inv.facts_for("pve1") == {"os": "Debian 13"}
    assert sorted(inv.objects) == ["pve1"]


def test_facts_note_name_differs_from_host_note_no_duplicate(tmp_path):
    """The facts note's own file is `<host> facts.md`, not `<host>.md`, so `[[vps1]]` stays unambiguous
    and Bastet's own duplicate-name check never sees two objects named `vps1`."""
    put(tmp_path, "hosts/vps1.md", "---\nbastet: host\ntype: vps\nip: 203.0.113.10\nprovider: linode\n---\n")
    put(
        tmp_path,
        "_bastet/facts/vps1 facts.md",
        '---\nbastet: facts\nhost: "[[vps1]]"\ngathered: now\nos: Debian 13\n---\n',
    )
    inv = load_inventory(tmp_path, TYPES)
    assert inv.errors == []
    assert not any("duplicate" in p.error.message for p in inv.problems)
    assert inv.get("vps1").path == tmp_path / "hosts" / "vps1.md"
    assert inv.facts_for("vps1") == {"os": "Debian 13"}


def test_facts_note_for_unknown_host_is_a_warning(tmp_path):
    put(tmp_path, "_bastet/facts/ghost facts.md", '---\nbastet: facts\nhost: "[[ghost]]"\ngathered: now\n---\n')
    inv = load_inventory(tmp_path, TYPES)
    [w] = inv.problems
    assert w.severity == "warning"
    assert "no host named ghost" in w.error.message
    assert inv.facts_for("ghost") == {}


def test_renamed_host_two_facts_notes_canonical_path_wins(tmp_path):
    """Host `zeta` renamed to `alpha` in Obsidian: it rewrites the `host:` link inside the old note
    (left at its old filename), but the new facts note only appears at the next gather. Whichever one
    sits at `facts_path(alpha)` is canonical; the other is a warning, never read."""
    put(tmp_path, "hosts/alpha.md", '---\nbastet: host\ntype: vps\nprovider: x\nip: 203.0.113.10\n---\n# alpha\n')
    put(tmp_path, "_bastet/facts/zeta facts.md",
        '---\nbastet: facts\nhost: "[[alpha]]"\ngathered: "2026-01-01T00:00:00Z"\nos: Debian 12\n---\n')
    put(tmp_path, "_bastet/facts/alpha facts.md",
        '---\nbastet: facts\nhost: "[[alpha]]"\ngathered: "2026-10-06T00:00:00Z"\nos: Debian 13\n---\n')
    inv = load_inventory(tmp_path, TYPES)
    assert inv.facts_for("alpha").get("os") == "Debian 13"
    warnings = [p.error.message for p in inv.problems if p.severity == "warning"]
    assert any("zeta facts" in m and "alpha" in m for m in warnings)


def test_stale_fact_keys_warning(tmp_path):
    put(
        tmp_path,
        "hosts/pve1.md",
        "---\nbastet: host\ntype: server\nip: 10.0.10.5\nos: Debian 12\nkernel: 6.9\ncpu: Ryzen\n---\n",
    )
    inv = load_inventory(tmp_path, TYPES)
    [w] = inv.problems
    assert w.severity == "warning"
    assert w.error.message == (
        "os, kernel, cpu are gathered facts; they now live in _bastet/facts/pve1 facts.md (remove them from this note)"
    )
    assert w.error.line == 5  # the 'os:' line


def test_stale_fallback_key_already_in_facts_note_says_remove_it(tmp_path):
    """ssh_host_key on the host note matches what the facts note already holds -- it's safe to tell the
    user to remove it: the fallback has already done its job."""
    put(tmp_path, "_bastet/facts/g facts.md",
        '---\nbastet: facts\nhost: "[[g]]"\ngathered: "2026-10-06T00:00:00Z"\nssh_host_key: ssh-ed25519 AAAA\n---\n')
    put(tmp_path, "hosts/g.md",
        '---\nbastet: host\ntype: lxc\nruns_on: "[[pve1]]"\nip: 10.0.20.21\nssh_host_key: ssh-ed25519 AAAA\n---\n')
    inv = load_inventory(tmp_path, TYPES)
    [w] = [p for p in inv.problems if "ssh_host_key" in p.error.message]
    assert "remove them from this note" in w.error.message
    assert "kept" not in w.error.message


def test_stale_fallback_key_not_yet_in_facts_note_says_kept_until_gather(tmp_path):
    """ssh_host_key is only on the host note so far (never gathered yet) -- telling the user to remove
    it now would silently undo the pin; it must say it's kept until the next gather copies it in."""
    put(tmp_path, "hosts/g.md",
        '---\nbastet: host\ntype: lxc\nruns_on: "[[pve1]]"\nip: 10.0.20.21\nssh_host_key: ssh-ed25519 AAAA\n---\n')
    inv = load_inventory(tmp_path, TYPES)
    [w] = [p for p in inv.problems if "ssh_host_key" in p.error.message]
    assert "kept" in w.error.message and "next gather" in w.error.message
    assert "remove them from this note" not in w.error.message


def test_stale_fact_keys_no_warning_for_declared_keys(tmp_path):
    put(tmp_path, "locations/Rack.md", "---\nbastet: location\n---\n")
    put(tmp_path, "hosts/pve1.md", host("pve1", 'location: "[[Rack]]"\n'))
    inv = load_inventory(tmp_path, TYPES)
    assert inv.problems == []


def test_stale_fact_keys_one_line_per_host(tmp_path):
    put(tmp_path, "hosts/a.md", "---\nbastet: host\ntype: server\nip: 10.0.10.5\nos: Debian 12\nkernel: 6.9\n---\n")
    put(tmp_path, "hosts/b.md", "---\nbastet: host\ntype: server\nip: 10.0.10.6\ncpu: Ryzen\n---\n")
    inv = load_inventory(tmp_path, TYPES)
    stale_warnings = [p for p in inv.problems if "are gathered facts" in p.error.message]
    assert len(stale_warnings) == 2
    assert any("os, kernel are gathered facts" in p.error.message for p in stale_warnings)
    assert any("cpu are gathered facts" in p.error.message for p in stale_warnings)


def test_facts_note_with_no_facts_is_empty(tmp_path):
    put(tmp_path, "hosts/pve1.md", host("pve1"))
    assert load_inventory(tmp_path, TYPES).facts_for("pve1") == {}




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


def test_old_proxmox_node_type_name_gives_helpful_error(tmp_path):
    put(tmp_path, "hosts/pve1.md", "---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.11\n---\n# pve1\n")
    inv = load_inventory(tmp_path, TYPES)
    [error] = inv.errors
    assert "proxmox-node" in error.error.message
    assert "renamed to proxmox" in error.error.message


def test_group_named_after_type_is_reserved_name_error(tmp_path):
    put(tmp_path, "groups/proxmox.md", "---\nbastet: group\n---\n# proxmox\n")
    inv = load_inventory(tmp_path, TYPES)
    [error] = inv.errors
    assert "proxmox" in error.error.message
    assert "host type" in error.error.message
    assert "rename this group" in error.error.message
