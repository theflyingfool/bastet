from pathlib import Path

from bastet.core.addressing import suggest_address, used_addresses
from bastet.core.factsnote import render_hardware_facts
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory

NET = {"cidr": "10.0.20.0/24", "reserved": ".1-.9", "dhcp": ".100-.199"}


def test_skips_reserved_and_used():
    assert suggest_address(NET, set()) == "10.0.20.10"
    assert suggest_address(NET, {"10.0.20.10", "10.0.20.11"}) == "10.0.20.12"


def test_skips_dhcp_range():
    used = {f"10.0.20.{i}" for i in range(10, 100)}
    assert suggest_address(NET, used) == "10.0.20.200"


def test_full_address_ranges():
    net = {"cidr": "10.0.30.0/29", "reserved": "10.0.30.1-10.0.30.2"}
    assert suggest_address(net, set()) == "10.0.30.3"


def test_exhausted_returns_none():
    net = {"cidr": "10.0.30.0/30"}
    assert suggest_address(net, {"10.0.30.1", "10.0.30.2"}) is None


def test_used_addresses_strip_prefix_length(tmp_path: Path):
    (tmp_path / "a.md").write_text("---\nbastet: host\ntype: server\nip: 10.0.10.11/24\n---\n")
    (tmp_path / "c.md").write_text("---\nbastet: host\ntype: laptop\nip: dhcp\n---\n")
    (tmp_path / "b.md").write_text("---\nbastet: hardware\ncategory: server\n---\n")
    facts_dir = tmp_path / "_bastet" / "facts"
    facts_dir.mkdir(parents=True)
    (facts_dir / "b facts.md").write_text(
        render_hardware_facts("b", {"oob": {"type": "ipmi", "address": "10.0.10.9"}}, "2026-10-06T10:00:00Z")
    )
    inv = load_inventory(tmp_path, load_host_types())
    assert used_addresses(inv) == {"10.0.10.11", "10.0.10.9"}
