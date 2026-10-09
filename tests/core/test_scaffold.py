from pathlib import Path

import pytest

from bastet.core.errors import BastetError
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.scaffold import new_hardware, new_host

TYPES = load_host_types()

LAB = """---
bastet: lab
networks:
  servers:
    cidr: 10.0.20.0/24
    reserved: .1-.9
---
"""


def inv_with(tmp_path: Path, files: dict[str, str]):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return load_inventory(tmp_path, TYPES)


PVE1 = "---\nbastet: host\ntype: proxmox\nip: 10.0.10.11\n---\n"


def test_new_vps(tmp_path):
    inv = inv_with(tmp_path, {})
    draft = new_host(inv, TYPES, "edge1", "vps", ip="203.0.113.10", provider="linode")
    assert draft.change.path == tmp_path / "hosts" / "edge1.md"
    assert draft.change.before is None
    assert draft.change.after == (
        "---\nbastet: host\ncssclasses:\n  - bastet-host\ntype: vps\n"
        "provider: linode\nip: 203.0.113.10\nhostname: edge1\ngather: true\n---\n# edge1\n\n"
        "![[edge1 summary]]\n\n## Reports\n\n![[edge1 reports]]\n"
    )
    assert draft.suggested_ip is None


def test_new_physical_host_gets_hardware_and_reports_sections(tmp_path):
    inv = inv_with(tmp_path, {})
    draft = new_host(inv, TYPES, "pve2", "proxmox", ip="10.0.10.12")
    assert draft.change.after.endswith(
        "# pve2\n\n![[pve2 summary]]\n\n## Hardware\n\n![[hardware-here.base]]\n\n## Reports\n\n![[pve2 reports]]\n"
    )


def test_new_lxc_with_suggested_address(tmp_path):
    inv = inv_with(tmp_path, {"Homelab.md": LAB, "hosts/pve1.md": PVE1})
    draft = new_host(inv, TYPES, "git1", "lxc", on="pve1", network="servers")
    assert draft.suggested_ip == "10.0.20.10"
    assert 'runs_on: "[[pve1]]"' in draft.change.after
    assert "network: servers\nip: 10.0.20.10\n" in draft.change.after


def test_missing_minimal_names_option(tmp_path):
    inv = inv_with(tmp_path, {})
    with pytest.raises(BastetError) as e:
        new_host(inv, TYPES, "edge1", "vps", ip="203.0.113.10")
    assert "provider (--provider)" in e.value.message


def test_unknown_type(tmp_path):
    with pytest.raises(BastetError) as e:
        new_host(inv_with(tmp_path, {}), TYPES, "x", "vpz", ip="10.0.0.1")
    assert "unknown host type" in e.value.message


def test_new_host_existing_name_any_case(tmp_path):
    inv = inv_with(tmp_path, {"hosts/pve1.md": PVE1})
    with pytest.raises(BastetError) as e:
        new_host(inv, TYPES, "PVE1", "server", ip="10.0.10.99")
    assert "already exists" in e.value.message


def test_on_must_be_a_host(tmp_path):
    inv = inv_with(tmp_path, {})
    with pytest.raises(BastetError) as e:
        new_host(inv, TYPES, "git1", "lxc", on="pve1", ip="10.0.20.21")
    assert "--on pve1" in e.value.message


def test_duplicate_address_rejected(tmp_path):
    inv = inv_with(tmp_path, {"hosts/pve1.md": PVE1})
    with pytest.raises(BastetError) as e:
        new_host(inv, TYPES, "pve2", "proxmox", ip="10.0.10.11")
    assert "already used" in e.value.message


def test_dhcp_laptop_with_address(tmp_path):
    inv = inv_with(tmp_path, {})
    draft = new_host(inv, TYPES, "laptop", "laptop", ip="dhcp", address="laptop.local")
    assert "ip: dhcp\naddress: laptop.local\n" in draft.change.after


def test_bad_name(tmp_path):
    with pytest.raises(BastetError):
        new_host(inv_with(tmp_path, {}), TYPES, "a/b", "server", ip="10.0.0.1")


def test_unknown_network(tmp_path):
    inv = inv_with(tmp_path, {"Homelab.md": LAB, "hosts/pve1.md": PVE1})
    with pytest.raises(BastetError) as e:
        new_host(inv, TYPES, "git1", "lxc", on="pve1", network="iot")
    assert "servers" in e.value.message


def test_new_hardware_installed(tmp_path):
    inv = inv_with(tmp_path, {"hosts/pve1.md": PVE1})
    c = new_hardware(inv, "WD Red 4TB WX12", "drive", serial="WX12", size="4 TB", installed_in="pve1")
    assert c.path == tmp_path / "hardware" / "WD Red 4TB WX12.md"
    assert c.after == (
        "---\nbastet: hardware\ncategory: drive\nserial: WX12\nsize: 4 TB\n"
        'status: in-service\ninstalled_in: "[[pve1]]"\ncssclasses:\n  - bastet-host\n---\n# WD Red 4TB WX12\n\n![[WD Red 4TB WX12 summary]]\n'
    )


def test_new_hardware_spare_by_default_without_host(tmp_path):
    inv = inv_with(tmp_path, {"locations/Closet.md": "---\nbastet: location\n---\n"})
    c = new_hardware(inv, "Spare drive", "drive", location="Closet")
    assert "status: spare" in c.after and 'location: "[[Closet]]"' in c.after


def test_new_hardware_bad_status(tmp_path):
    with pytest.raises(BastetError):
        new_hardware(inv_with(tmp_path, {}), "x", "drive", status="broken")


def test_refuses_to_overwrite_non_bastet_file(tmp_path):
    inv = inv_with(tmp_path, {"hosts/web.md": "# my notes\nprecious\n"})
    with pytest.raises(BastetError) as e:
        new_host(inv, TYPES, "web", "server", ip="10.0.10.50")
    assert e.value.file == tmp_path / "hosts" / "web.md"


def test_refuses_same_name_any_case_anywhere(tmp_path):
    inv = inv_with(tmp_path, {"notes/Web.md": "# a personal note\n"})
    with pytest.raises(BastetError):
        new_host(inv, TYPES, "web", "server", ip="10.0.10.50")
    with pytest.raises(BastetError):
        new_hardware(inv, "WEB", "drive")


def test_new_host_local_connection(tmp_path):
    inv = inv_with(tmp_path, {})
    draft = new_host(inv, TYPES, "laptop", "laptop", ip="dhcp", address="laptop.local", connection="local")
    assert "address: laptop.local\nconnection: local\n" in draft.change.after


def test_suggested_ip_helper(tmp_path):
    from bastet.core.scaffold import suggested_ip

    inv = inv_with(tmp_path, {"Homelab.md": LAB, "hosts/pve1.md": PVE1})
    assert suggested_ip(inv, "servers") == "10.0.20.10"
    with pytest.raises(BastetError):
        suggested_ip(inv, "iot")


def test_unifi_types_are_gathered_with_mca_dump(tmp_path):
    from bastet.core.hosttypes import HostType, load_host_types
    types = load_host_types()
    assert {"unifi-gateway", "unifi-switch", "unifi-ap"} <= set(types)
    assert types["unifi-ap"].gather is True and types["unifi-ap"].fields["ports"] == "fact"
    draft = new_host(inv_with(tmp_path, {}), types, "u7-pro-xg", "unifi-ap", ip="10.10.0.3")
    assert "gather: true" in draft.change.after and "hostname: u7-pro-xg" in draft.change.after
    quiet = {**types, "quiet": HostType(name="quiet", minimal=["ip"], gather=False)}
    assert "gather: false" in new_host(inv_with(tmp_path, {}), quiet, "q1", "quiet", ip="10.10.0.9").change.after
