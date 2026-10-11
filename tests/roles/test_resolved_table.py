from pathlib import Path

from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.render import host_summary
from bastet.roles.contract import load_roles
from bastet.roles.pages import resolved_table
from bastet.roles.resolve import resolve

TYPES = load_host_types()

FILES = {
    "Homelab.md": "---\nbastet: lab\n---\n# Homelab\n",
    "groups/laptops.md": "---\nbastet: group\n---\n# laptops\n",
    "hosts/hp-13.md": '---\nbastet: host\ntype: laptop\nconnection: local\ngroups:\n  - "[[laptops]]"\n---\n# hp-13\n',
    "hosts/pve1.md": "---\nbastet: host\ntype: proxmox\nip: 10.0.10.11\n---\n# pve1\n",
    "_roles/lab/systemd.md": '---\nbastet: role\nrole: systemd\napplies_to: "[[Homelab]]"\ntimezone: UTC\nntp_service: timesyncd\n---\n',
    "_roles/hosts/hp-13/systemd.md": '---\nbastet: role\nrole: systemd\napplies_to: "[[hp-13]]"\ntimezone: America/Chicago\n---\n',
    "_roles/groups/laptops/packages.md": '---\nbastet: role\nrole: packages\napplies_to: "[[laptops]]"\ninstall:\n  - git\n  - name: jq\n    version: "1.7"\n---\n',
    "_roles/hosts/hp-13/packages.md": '---\nbastet: role\nrole: packages\napplies_to: "[[hp-13]]"\ninstall:\n  - tree\n---\n',
    "_roles/hosts/hp-13/users.md": ('---\nbastet: role\nrole: users\napplies_to: "[[hp-13]]"\nusers:\n  alice:\n'
                                    '    shell: /bin/bash\n    password_hash: "$6$secret"\n---\n'),
}


def lab(tmp_path: Path):
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return load_inventory(tmp_path, TYPES)


def rows(text):
    return [line for line in text.splitlines() if line.startswith("| ") and not line.startswith("| Role")]


def test_table_shows_winner_origin_merged_lists_and_defaults(tmp_path):
    inv = lab(tmp_path)
    text = resolved_table(resolve(inv, inv.get("hp-13"), TYPES, load_roles()))
    assert "[!warning] Resolved roles" in text and "don't edit" in text.lower()
    assert "| [[systemd role\\|systemd]] | timezone | America/Chicago | host hp-13 |" in text
    assert "| [[systemd role\\|systemd]] | ntp_service | timesyncd | lab |" in text
    assert "| [[systemd role\\|systemd]] | manage_hostname | true | default |" in text
    assert "| [[packages role\\|packages]] | install | git, jq (version 1.7), tree | group laptops, host hp-13 |" in text
    assert "$6$" not in text and "password_hash: (secret)" in text
    assert not [r for r in rows(text) if "| ntp |" in r]  # unset, no default: not shown


def test_summary_embeds_table_and_proxmox_type_adds_no_roles(tmp_path):
    inv = lab(tmp_path)
    summary = host_summary(inv, inv.get("pve1"), TYPES, [])
    assert "| [[systemd role\\|systemd]] | ntp_service | timesyncd | lab |" in summary
    assert "type proxmox" not in summary
    assert summary.index("[!grid]") < summary.index("Resolved roles")


def test_no_roles_no_table(tmp_path):
    (tmp_path / "Homelab.md").write_text("---\nbastet: lab\n---\n# Homelab\n")
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hosts" / "x.md").write_text("---\nbastet: host\ntype: vm\nip: 10.0.10.5\n---\n# x\n")
    inv = load_inventory(tmp_path, TYPES)
    assert "Resolved roles" not in host_summary(inv, inv.get("x"), TYPES, [])
