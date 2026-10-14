from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.roles.contract import load_roles
from bastet.roles.resolve import resolve

TYPES = load_host_types()
ROLES = load_roles()

FILES = {
    "Homelab.md": "---\nbastet: lab\n---\n# Homelab\n",
    "hosts/media01.md": "---\nbastet: host\ntype: proxmox\nip: 10.1.0.21\n---\n# media01\n",
    "hosts/pve1.md": "---\nbastet: host\ntype: proxmox\nip: 10.1.0.11\n---\n# pve1\n",
    "_roles/hosts/media01/ssh.md": '---\nbastet: role\nrole: ssh\napplies_to: "[[media01]]"\n---\n',
}


def test_the_removed_roles_are_not_shipped():
    assert not {"ssh", "harden"} & set(ROLES)


def test_a_note_naming_a_removed_role_fails_that_host_only(tmp_path):
    for rel, text in FILES.items():
        p: Path = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    inv = load_inventory(tmp_path, TYPES)
    with pytest.raises(BastetError, match="unknown role 'ssh'"):
        resolve(inv, inv.get("media01"), TYPES, ROLES)
    assert isinstance(resolve(inv, inv.get("pve1"), TYPES, ROLES), list)
