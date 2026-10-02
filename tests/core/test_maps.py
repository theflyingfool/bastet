from pathlib import Path

from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.maps import cabling_map, networks_map

TYPES = load_host_types()


def lab(tmp_path: Path):
    (tmp_path / "Homelab.md").write_text(
        "---\nbastet: lab\nnetworks:\n  lan: {cidr: 10.10.0.0/24}\n  servers: {cidr: 10.10.20.0/24, vlan: 20}\n---\n# L\n")
    h = tmp_path / "hosts"
    h.mkdir()
    (h / "gw.md").write_text("---\nbastet: host\ntype: unifi-gateway\nip: 10.10.0.1\n---\n# gw\n")
    (h / "sw.md").write_text('---\nbastet: host\ntype: unifi-switch\nip: 10.10.0.5\nlinks:\n'
                             '  - {port: "9", to: "[[gw]]", to_port: "4", speed: 10G}\n---\n# sw\n')
    (h / "nas.md").write_text('---\nbastet: host\ntype: server\nip: 10.10.20.7\nlinks:\n'
                              '  - {port: eno1, to: "[[sw]]", to_port: "2"}\n---\n# nas\n')
    (h / "far.md").write_text('---\nbastet: host\ntype: server\nip: 192.168.50.2\nlinks:\n'
                              '  - {port: eth0, to: "[[nas]]", to_port: eno2}\n---\n# far\n')
    return load_inventory(tmp_path, TYPES)


def test_cabling_map_edges_and_around(tmp_path):
    inv = lab(tmp_path)
    full = cabling_map(inv)
    assert full.startswith("```mermaid") and full.count("---") >= 3 and "9 ↔ 4 · 10G" in full
    near = cabling_map(inv, around="gw")
    assert "gw" in near and "sw" in near and "far" not in near


def test_networks_map_groups_hosts(tmp_path):
    text = networks_map(lab(tmp_path))
    assert "lan · 10.10.0.0/24" in text and "servers · 10.10.20.0/24 · VLAN 20" in text
    assert "Elsewhere" in text and "192.168.50.2" in text


def test_empty_maps(tmp_path):
    (tmp_path / "Homelab.md").write_text("---\nbastet: lab\n---\n# L\n")
    inv = load_inventory(tmp_path, TYPES)
    assert cabling_map(inv) == "" and networks_map(inv) == ""


def test_networks_map_mixed_ip_versions(tmp_path):
    inv = lab(tmp_path)
    (tmp_path / "hosts" / "v6.md").write_text("---\nbastet: host\ntype: server\nip: 2001:db8::5\n---\n# v6\n")
    (tmp_path / "hosts" / "pub.md").write_text("---\nbastet: host\ntype: server\nip: 203.0.113.10\n---\n# pub\n")
    text = networks_map(load_inventory(tmp_path, TYPES))
    assert "2001:db8::5" in text and "203.0.113.10" in text
