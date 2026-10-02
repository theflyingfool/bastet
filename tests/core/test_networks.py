from pathlib import Path

from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.networks import compare_networks, lab_networks

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


def test_compare_networks(tmp_path):
    inv = make(tmp_path, LAB.replace("  servers: {cidr: 10.10.20.0/24, vlan: 20}\n",
                                     "  servers: {cidr: 10.10.20.0/24, vlan: 20}\n  iot: {cidr: 10.10.40.0/24, vlan: 40}\n"))
    seen = [{"interface": "br0", "cidr": "10.10.0.0/24", "address": "10.10.0.1"},
            {"interface": "br30", "cidr": "10.10.30.0/24", "address": "10.10.30.1"},
            {"interface": "br20", "cidr": "10.10.20.0/24", "address": "10.10.20.1"}]
    assert compare_networks(lab_networks(inv), seen) == [
        ("warn", "10.10.30.0/24 (br30) is on the gateway but not in the lab file's networks"),
        ("info", "iot (10.10.40.0/24) isn't on the gateway yet"),
    ]


def test_malformed_link_vlan_is_an_error_not_a_crash(tmp_path):
    inv = make(tmp_path, LAB, a='ip: 10.10.0.5\nlinks:\n  - {port: eno1, vlan: {id: 10}}\n  - {port: eno2, vlan: "20"}\n')
    errs = messages(inv, "error")
    assert any("isn't a number" in m for m in errs) and not any("VLAN 20" in m for m in errs)


def test_untagged_only_lab_skips_link_vlan_check(tmp_path):
    inv = make(tmp_path, "---\nbastet: lab\nnetworks:\n  lan: {cidr: 10.10.0.0/24}\n---\n# Lab\n",
               a='ip: 10.10.0.5\nlinks:\n  - {port: eno1, native_vlan: 1}\n')
    assert messages(inv, "error") == []
