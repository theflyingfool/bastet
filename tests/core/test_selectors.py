from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.selectors import select_hosts

TYPES = load_host_types()

FILES = {
    "Homelab.md": "---\nbastet: lab\n---\n# Homelab\n",
    "groups/servers.md": "---\nbastet: group\n---\n# servers\n",
    "groups/arch.md": "---\nbastet: group\nmatch:\n  os: arch\n---\n# arch\n",
    "hosts/pve1.md": "---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.11\n---\n# pve1\n",
    "hosts/pve2.md": '---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.12\ngroups:\n  - "[[servers]]"\n---\n# pve2\n',
    "hosts/media01.md": '---\nbastet: host\ntype: server\nip: 10.0.20.30\ngroups:\n  - "[[servers]]"\n---\n# media01\n',
    "hosts/archdev.md": "---\nbastet: host\ntype: laptop\nconnection: local\n---\n# archdev\n",
    "hosts/gone.md": "---\nbastet: host\ntype: laptop\nconnection: local\nstate: destroyed\n---\n# gone\n",
    "_bastet/facts/archdev facts.md": (
        '---\nbastet: facts\nhost: "[[archdev]]"\ngathered: 2026-10-06T10:00:00Z\nos: Arch Linux\n---\n'
    ),
}


def lab(tmp_path: Path, extra=None):
    for rel, text in {**FILES, **(extra or {})}.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return load_inventory(tmp_path, TYPES)


def names(docs) -> list[str]:
    return [d.name for d in docs]


def test_no_selectors_is_every_present_host(tmp_path):
    inv = lab(tmp_path)
    assert names(select_hosts(inv, TYPES, [], [])) == ["archdev", "media01", "pve1", "pve2"]


def test_destroyed_host_excluded_by_default(tmp_path):
    inv = lab(tmp_path)
    assert "gone" not in names(select_hosts(inv, TYPES, [], []))


def test_destroyed_host_included_when_named_exactly(tmp_path):
    inv = lab(tmp_path)
    assert names(select_hosts(inv, TYPES, ["gone"], [])) == ["gone"]


def test_exact_name_selector(tmp_path):
    inv = lab(tmp_path)
    assert names(select_hosts(inv, TYPES, ["pve1"], [])) == ["pve1"]


def test_exact_name_is_case_insensitive(tmp_path):
    inv = lab(tmp_path)
    assert names(select_hosts(inv, TYPES, ["PVE1"], [])) == ["pve1"]


def test_at_lab_selector_is_every_host(tmp_path):
    inv = lab(tmp_path)
    assert names(select_hosts(inv, TYPES, ["@lab"], [])) == ["archdev", "media01", "pve1", "pve2"]


def test_at_type_selector(tmp_path):
    inv = lab(tmp_path)
    assert names(select_hosts(inv, TYPES, ["@proxmox-node"], [])) == ["pve1", "pve2"]


def test_at_group_selector_direct_membership(tmp_path):
    inv = lab(tmp_path)
    assert names(select_hosts(inv, TYPES, ["@servers"], [])) == ["media01", "pve2"]


def test_at_group_selector_via_match_rule(tmp_path):
    inv = lab(tmp_path)
    assert names(select_hosts(inv, TYPES, ["@arch"], [])) == ["archdev"]


def test_glob_selector(tmp_path):
    inv = lab(tmp_path)
    assert names(select_hosts(inv, TYPES, ["pve*"], [])) == ["pve1", "pve2"]


def test_union_deduplicated_and_in_inventory_order(tmp_path):
    inv = lab(tmp_path)
    docs = select_hosts(inv, TYPES, ["pve2", "@servers", "pve1"], [])
    assert names(docs) == ["media01", "pve1", "pve2"]


def test_exclude_removes_from_the_result(tmp_path):
    inv = lab(tmp_path)
    assert names(select_hosts(inv, TYPES, ["@servers"], ["media01"])) == ["pve2"]


def test_exclude_takes_selector_forms_too(tmp_path):
    inv = lab(tmp_path)
    assert names(select_hosts(inv, TYPES, [], ["@proxmox-node"])) == ["archdev", "media01"]


def test_unknown_at_name_lists_groups_and_types(tmp_path):
    inv = lab(tmp_path)
    with pytest.raises(BastetError) as exc:
        select_hosts(inv, TYPES, ["@nope"], [])
    assert "servers" in str(exc.value) and "proxmox-node" in str(exc.value)


def test_glob_matching_nothing_is_an_error(tmp_path):
    inv = lab(tmp_path)
    with pytest.raises(BastetError):
        select_hosts(inv, TYPES, ["zzz*"], [])


def test_exact_name_that_is_not_a_host_is_an_error(tmp_path):
    inv = lab(tmp_path)
    with pytest.raises(BastetError) as exc:
        select_hosts(inv, TYPES, ["servers"], [])
    assert "no host named 'servers'" in str(exc.value)


def test_exact_name_not_in_inventory_is_an_error(tmp_path):
    inv = lab(tmp_path)
    with pytest.raises(BastetError):
        select_hosts(inv, TYPES, ["nope"], [])
