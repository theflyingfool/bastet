from pathlib import Path

from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory

TYPES = load_host_types()
LAB = ("---\nbastet: lab\nnetworks:\n  lan: {cidr: 10.10.0.0/24}\n"
       "  servers: {cidr: 10.10.20.0/24, vlan: 20}\n---\n# Lab\n")


def make(tmp_path: Path, lab: str, **hosts: str):
    (tmp_path / "Homelab.md").write_text(lab)
    (tmp_path / "hosts").mkdir()
    for name, front in hosts.items():
        (tmp_path / "hosts" / f"{name}.md").write_text(f"---\nbastet: host\ntype: server\n{front}---\n# {name}\n")
    return load_inventory(tmp_path, TYPES)


def messages(inv, severity):
    return [p.error.message for p in inv.problems if p.severity == severity]


def test_untagged_and_tagged_networks_are_fine(tmp_path):
    inv = make(tmp_path, LAB, a="ip: 10.10.0.5\n", b="ip: 10.10.20.5\nnetwork: servers\n", c="ip: dhcp\n")
    assert messages(inv, "error") == [] and messages(inv, "warning") == []


def test_bad_networks_are_errors(tmp_path):
    lab = ("---\nbastet: lab\nnetworks:\n  a: {cidr: 10.0.0.0/16, vlan: 10}\n  b: {cidr: 10.0.5.0/24, vlan: 10}\n"
           "  c: {cidr: nope}\n  d: {cidr: 10.9.0.0/24, vlan: 5000}\n---\n# Lab\n")
    errs = " | ".join(messages(make(tmp_path, lab), "error"))
    assert "VLAN 10" in errs and "overlaps" in errs and "cidr 'nope'" in errs and "vlan 5000" in errs


def test_host_network_and_address_checks(tmp_path):
    inv = make(tmp_path, LAB, a="ip: 10.10.0.5\nnetwork: servers\n", b="ip: 10.10.0.6\nnetwork: nope\n",
               c="ip: 10.99.0.1\n", d="ip: 203.0.113.9\n")
    errs = " | ".join(messages(inv, "error"))
    assert "10.10.0.5 is outside servers (10.10.20.0/24)" in errs and "network 'nope'" in errs
    assert messages(inv, "warning") == ["10.99.0.1 is in none of the lab's networks"]


def test_no_networks_means_no_address_warnings(tmp_path):
    inv = make(tmp_path, "---\nbastet: lab\n---\n# Lab\n", a="ip: 10.99.0.1\n")
    assert messages(inv, "warning") == []


def test_link_vlans_must_exist(tmp_path):
    inv = make(tmp_path, LAB, a='links:\n  - {port: eno1, to: "[[sw]]", to_port: "2", vlans: [20, 30]}\n')
    assert any("VLAN 30" in m for m in messages(inv, "error"))
