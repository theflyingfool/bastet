from pathlib import Path

from bastet.core.factsnote import render_facts
from bastet.core.frontmatter import parse_document
from bastet.core.hosttypes import load_host_types
from bastet.core.hostview import host_data, stale_fact_keys
from bastet.core.inventory import Inventory

TYPES = load_host_types()
P = Path("/v/hosts/pve1.md")


def doc(text: str):
    return parse_document(text, P)


def inv_with_facts(facts: dict | None) -> Inventory:
    inv = Inventory(root=Path("/v"))
    if facts is not None:
        text = render_facts("pve1", facts, "2026-10-06T10:00:00Z")
        inv.facts["pve1"] = parse_document(text, Path("/v/_bastet/facts/pve1 facts.md"))
    return inv


def test_host_data_facts_plus_declared_override():
    inv = inv_with_facts({"os": "Debian 13", "ram": "16 GB"})
    d = doc('---\nbastet: host\ntype: lxc\nruns_on: "[[pve1]]"\nip: 10.0.20.9\nram: 8 GB\n---\n')
    data = host_data(inv, d, TYPES)
    assert data["os"] == "Debian 13"  # fact-only: facts note wins (nothing to override)
    assert data["ram"] == "8 GB"  # 'ram' is desired-nature for lxc: host note's declared value wins


def test_host_data_ignores_stale_fact_on_host_note():
    inv = inv_with_facts({"os": "Debian 13"})
    d = doc("---\nbastet: host\ntype: server\nip: 10.0.10.5\nos: Debian 12\n---\n")
    data = host_data(inv, d, TYPES)
    assert data["os"] == "Debian 13"
    assert stale_fact_keys(d, TYPES) == ["os"]


def test_host_data_ssh_host_key_fallback():
    inv = inv_with_facts({"os": "Debian 13"})
    d = doc("---\nbastet: host\ntype: server\nip: 10.0.10.5\nssh_host_key: AAAAfake\n---\n")
    data = host_data(inv, d, TYPES)
    assert data["ssh_host_key"] == "AAAAfake"
    assert "ssh_host_key" in stale_fact_keys(d, TYPES)


def test_host_data_no_facts_note_only_declared():
    inv = inv_with_facts(None)
    d = doc("---\nbastet: host\ntype: server\nip: 10.0.10.5\n---\n")
    data = host_data(inv, d, TYPES)
    assert data == {"bastet": "host", "type": "server", "ip": "10.0.10.5"}


def test_host_data_unknown_type_uses_unknown_fields():
    inv = inv_with_facts({"os": "Debian 13"})
    d = doc("---\nbastet: host\ntype: mystery\nos: Debian 12\n---\n")
    data = host_data(inv, d, TYPES)
    assert data["os"] == "Debian 13"
    assert stale_fact_keys(d, TYPES) == ["os"]


def test_stale_fact_keys_no_warning_for_declared_keys():
    d = doc("---\nbastet: host\ntype: proxmox-node\nip: 10.0.10.11\nlocation: \"[[Rack]]\"\n---\n")
    assert stale_fact_keys(d, TYPES) == []


def test_host_data_vmid_fallback_to_stale_host_note():
    """vmid is an OBSERVED_BY_OTHERS fact: a guest never observed its own vmid, but a value left on an old
    host note (from before the facts note existed) still works for matching, same as ssh_host_key."""
    inv = inv_with_facts({"os": "Debian 13"})
    d = doc('---\nbastet: host\ntype: lxc\nruns_on: "[[pve1]]"\nip: 10.0.20.9\nvmid: 104\n---\n')
    data = host_data(inv, d, TYPES)
    assert data["vmid"] == 104
    assert "vmid" in stale_fact_keys(d, TYPES)


def test_host_data_vmid_from_facts_note_wins_over_stale_host_note():
    inv = inv_with_facts({"vmid": 104})
    d = doc('---\nbastet: host\ntype: lxc\nruns_on: "[[pve1]]"\nip: 10.0.20.9\nvmid: 999\n---\n')
    data = host_data(inv, d, TYPES)
    assert data["vmid"] == 104


def test_host_data_links_declared_wins_for_the_same_port():
    inv = inv_with_facts({"links": [{"port": "eno1", "to": "[[sw]]", "to_port": "9"}]})
    d = doc(
        '---\nbastet: host\ntype: server\nip: 10.0.10.5\n'
        'links:\n  - port: eno1\n    to: "[[other-switch]]"\n    to_port: "1"\n---\n'
    )
    data = host_data(inv, d, TYPES)
    assert data["links"] == [{"port": "eno1", "to": "[[other-switch]]", "to_port": "1"}]


def test_host_data_links_observed_added_for_other_ports():
    inv = inv_with_facts({"links": [{"port": "eno2", "to": "[[sw]]", "to_port": "9"}]})
    d = doc(
        '---\nbastet: host\ntype: server\nip: 10.0.10.5\n'
        'links:\n  - port: eno1\n    to: "[[other-switch]]"\n    to_port: "1"\n---\n'
    )
    data = host_data(inv, d, TYPES)
    assert data["links"] == [
        {"port": "eno1", "to": "[[other-switch]]", "to_port": "1"},
        {"port": "eno2", "to": "[[sw]]", "to_port": "9"},
    ]


def test_host_data_links_observed_only_when_nothing_declared():
    inv = inv_with_facts({"links": [{"port": "eno1", "to": "[[sw]]", "to_port": "9"}]})
    d = doc("---\nbastet: host\ntype: server\nip: 10.0.10.5\n---\n")
    data = host_data(inv, d, TYPES)
    assert data["links"] == [{"port": "eno1", "to": "[[sw]]", "to_port": "9"}]
