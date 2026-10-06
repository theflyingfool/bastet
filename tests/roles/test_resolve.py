from pathlib import Path

import pytest

from bastet.core.factsnote import render_facts
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.engine.run import ConflictError
from bastet.roles.contract import load_roles
from bastet.roles.resolve import group_distances, resolve

TYPES = load_host_types()
ROLES = load_roles()


def write_facts(root: Path, host: str, facts: dict) -> None:
    path = root / "_bastet" / "facts" / f"{host} facts.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_facts(host, facts, "2026-10-06T10:00:00Z"))

FILES = {
    "Homelab.md": "---\nbastet: lab\n---\n# Homelab\n",
    "groups/workstations.md": "---\nbastet: group\n---\n# workstations\n",
    "groups/laptops.md": '---\nbastet: group\ngroups:\n  - "[[workstations]]"\n---\n# laptops\n',
    "hosts/hp-13.md": '---\nbastet: host\ntype: laptop\nconnection: local\ngroups:\n  - "[[laptops]]"\n---\n# hp-13\n',
    "hosts/pve1.md": "---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.11\n---\n# pve1\n",
    "_roles/lab/systemd.md": ('---\nbastet: role\nrole: systemd\napplies_to: "[[Homelab]]"\ntimezone: UTC\nntp: true\n'
                              "ntp_service: timesyncd\nntp_servers:\n  - 10.0.10.1\n---\n"),
    "_roles/groups/workstations/packages.md": '---\nbastet: role\nrole: packages\napplies_to: "[[workstations]]"\ninstall:\n  - git\n  - vim\n---\n',
    "_roles/groups/laptops/packages.md": '---\nbastet: role\nrole: packages\napplies_to: "[[laptops]]"\ninstall:\n  - powertop\n  - git\n---\n',
    "_roles/hosts/hp-13/systemd.md": '---\nbastet: role\nrole: systemd\napplies_to: "[[hp-13]]"\ntimezone: America/Chicago\n---\n',
}


def lab(tmp_path: Path, extra=None):
    for rel, text in {**FILES, **(extra or {})}.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return load_inventory(tmp_path, TYPES)


def applied(inv, host):
    return {a.role.name: a for a in resolve(inv, inv.get(host), TYPES, ROLES)}


def test_role_files_share_names_without_clashing(tmp_path):
    inv = lab(tmp_path)
    assert len(inv.role_files) == 4 and not [p for p in inv.problems if "duplicate" in str(p)]


def test_group_distances(tmp_path):
    inv = lab(tmp_path)
    assert group_distances(inv, inv.get("hp-13"), TYPES) == {"laptops": 1, "workstations": 2}


def test_precedence_and_lists_add_up(tmp_path):
    a = applied(lab(tmp_path), "hp-13")
    s = a["systemd"].values
    assert s["timezone"] == "America/Chicago" and s["ntp_service"] == "timesyncd" and s["ntp_servers"] == ["10.0.10.1"]
    assert a["systemd"].origins["timezone"] == "host hp-13" and a["systemd"].origins["ntp_servers"] == "lab"
    assert [p["name"] for p in a["packages"].values["install"]] == ["git", "vim", "powertop"]


def test_type_baseline_beats_lab(tmp_path):
    s = applied(lab(tmp_path), "pve1")["systemd"].values
    assert s["ntp_service"] == "chrony" and s["timezone"] == "UTC"
    assert "packages" not in applied(lab(tmp_path), "pve1")


def test_sibling_groups_conflict_and_priority(tmp_path):
    extra = {
        "groups/a.md": "---\nbastet: group\n---\n# a\n",
        "groups/b.md": "---\nbastet: group\n---\n# b\n",
        "hosts/x.md": '---\nbastet: host\ntype: vm\nip: 10.0.10.30\ngroups:\n  - "[[a]]"\n  - "[[b]]"\n---\n# x\n',
        "_roles/groups/a/systemd.md": '---\nbastet: role\nrole: systemd\napplies_to: "[[a]]"\ntimezone: UTC\n---\n',
        "_roles/groups/b/systemd.md": '---\nbastet: role\nrole: systemd\napplies_to: "[[b]]"\ntimezone: Europe/Paris\n---\n',
    }
    inv = lab(tmp_path, extra)
    with pytest.raises(ConflictError) as e:
        resolve(inv, inv.get("x"), TYPES, ROLES)
    assert "group a" in str(e.value) and "group b" in str(e.value) and "timezone" in str(e.value)
    extra["groups/b.md"] = "---\nbastet: group\npriority: 10\n---\n# b\n"
    inv = lab(tmp_path, extra)
    assert applied(inv, "x")["systemd"].values["timezone"] == "Europe/Paris"


def test_secret_conflict_hides_values(tmp_path):
    extra = {
        "groups/a.md": "---\nbastet: group\n---\n# a\n",
        "groups/b.md": "---\nbastet: group\n---\n# b\n",
        "hosts/x.md": '---\nbastet: host\ntype: vm\nip: 10.0.10.30\ngroups:\n  - "[[a]]"\n  - "[[b]]"\n---\n# x\n',
        "_roles/groups/a/users.md": '---\nbastet: role\nrole: users\napplies_to: "[[a]]"\nusers:\n  nick:\n    password_hash: "$6$aaa"\n---\n',
        "_roles/groups/b/users.md": '---\nbastet: role\nrole: users\napplies_to: "[[b]]"\nusers:\n  nick:\n    password_hash: "$6$bbb"\n---\n',
    }
    inv = lab(tmp_path, extra)
    with pytest.raises(ConflictError) as e:
        resolve(inv, inv.get("x"), TYPES, ROLES)
    assert "$6$" not in str(e.value) and "(secret)" in str(e.value)


def test_bad_role_files(tmp_path):
    inv = lab(tmp_path, {"_roles/hosts/hp-13/nope.md": '---\nbastet: role\nrole: nope\napplies_to: "[[hp-13]]"\n---\n'})
    from bastet.core.errors import BastetError
    with pytest.raises(BastetError) as e:
        resolve(inv, inv.get("hp-13"), TYPES, ROLES)
    assert "unknown role 'nope'" in str(e.value) and e.value.file.name == "nope.md"
    inv = lab(tmp_path, {"_roles/stray.md": "---\nbastet: role\nrole: files\n---\n"})
    assert any("applies_to" in str(p) for p in inv.problems)


def test_host_types_have_baseline_roles():
    assert TYPES["proxmox-node"].roles == {"systemd": {"ntp_service": "chrony", "manage_hostname": False}, "proxmox": {}}
    assert TYPES["laptop"].roles == {}


def test_os_group_by_match(tmp_path):
    (tmp_path / "Homelab.md").write_text("---\nbastet: lab\n---\n# L\n")
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "a.md").write_text("---\nbastet: host\ntype: laptop\n---\n# a\n")
    (tmp_path / "hosts" / "d.md").write_text("---\nbastet: host\ntype: laptop\n---\n# d\n")
    write_facts(tmp_path, "a", {"os": "Arch Linux"})
    write_facts(tmp_path, "d", {"os": "Debian GNU/Linux 13 (trixie)"})
    (tmp_path / "_bastet" / "groups").mkdir(parents=True)
    (tmp_path / "_bastet" / "groups" / "arch.md").write_text("---\nbastet: group\nmatch:\n  os: arch\n---\n# arch\n")
    (tmp_path / "_roles" / "groups").mkdir(parents=True)
    (tmp_path / "_roles" / "groups" / "tree.md").write_text(
        '---\nbastet: role\nrole: packages\napplies_to: "[[arch]]"\ninstall: [tree]\n---\n')
    types = load_host_types()
    inv = load_inventory(tmp_path, types)
    roles = load_roles()
    on_arch = {a.role.name: a for a in resolve(inv, inv.get("a"), types, roles)}
    assert on_arch["packages"].values["install"] == [{"name": "tree"}]
    assert "packages" not in {a.role.name for a in resolve(inv, inv.get("d"), types, roles)}


def _match_lab(tmp_path, rule):
    (tmp_path / "Homelab.md").write_text("---\nbastet: lab\n---\n# L\n")
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "a.md").write_text("---\nbastet: host\ntype: laptop\n---\n# a\n")
    write_facts(tmp_path, "a", {"os": "Debian GNU/Linux 13 (trixie)"})
    (tmp_path / "groups").mkdir()
    (tmp_path / "groups" / "g.md").write_text(f"---\nbastet: group\nmatch: {rule}\n---\n# g\n")
    types = load_host_types()
    inv = load_inventory(tmp_path, types)
    return inv, inv.get("a")


@pytest.mark.parametrize("rule", ["debian", "{}", "[os]"])
def test_match_must_be_a_rule(tmp_path, rule):
    from bastet.core.errors import BastetError
    inv, host = _match_lab(tmp_path, rule)
    with pytest.raises(BastetError, match="match"):
        group_distances(inv, host, TYPES)


def test_match_os_is_case_insensitive(tmp_path):
    inv, host = _match_lab(tmp_path, "{os: Debian}")
    assert "g" in group_distances(inv, host, TYPES)


def test_non_numeric_group_priority(tmp_path):
    from bastet.core.errors import BastetError
    files = {
        "Homelab.md": "---\nbastet: lab\n---\n",
        "groups/a.md": "---\nbastet: group\npriority: high\n---\n",
        "hosts/x.md": '---\nbastet: host\ntype: vm\nip: 10.0.10.30\ngroups:\n  - "[[a]]"\n---\n',
        "_roles/groups/a/systemd.md": '---\nbastet: role\nrole: systemd\napplies_to: "[[a]]"\ntimezone: UTC\n---\n',
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    inv = load_inventory(tmp_path, TYPES)
    with pytest.raises(BastetError) as e:
        resolve(inv, inv.get("x"), TYPES, ROLES)
    assert "priority" in str(e.value)
