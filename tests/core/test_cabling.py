from bastet.core.cabling import merge_links, propose_links
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.unifi import parse_mca
from unifi_fixtures import AP, GATEWAY, GUEST_MAC, HOST_MAC, SWITCH

TYPES = load_host_types()


def lab(tmp_path):
    files = {
        "Homelab.md": "---\nbastet: lab\n---\n",
        "hosts/uxg.md": "---\nbastet: host\ntype: unifi-gateway\nip: 10.10.0.1\n---\n",
        "hosts/ap.md": "---\nbastet: host\ntype: unifi-ap\nip: 10.10.0.3\n---\n",
        "hosts/sw.md": "---\nbastet: host\ntype: unifi-switch\nip: 10.10.0.5\n---\n",
        "hosts/sanrio.md": f"---\nbastet: host\ntype: proxmox-node\nip: 10.10.0.15\ninterfaces:\n  - name: enp36s0\n    mac: {HOST_MAC}\n---\n",
        "hosts/vm1.md": f'---\nbastet: host\ntype: vm\nruns_on: "[[sanrio]]"\nip: 10.10.0.60\ninterfaces:\n  - name: eth0\n    mac: {GUEST_MAC}\n---\n',
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return load_inventory(tmp_path, TYPES)


def devices():
    return {"uxg": ("unifi-gateway", parse_mca(GATEWAY)), "ap": ("unifi-ap", parse_mca(AP)),
            "sw": ("unifi-switch", parse_mca(SWITCH))}


def test_unifi_to_unifi_link_goes_downstream(tmp_path):
    props = propose_links(lab(tmp_path), devices())
    assert ("ap", {"port": "eth0", "to": "[[uxg]]", "to_port": "4"}) in [(p.host, p.link) for p in props]


def test_host_link_from_mac_table(tmp_path):
    props = [(p.host, p.link) for p in propose_links(lab(tmp_path), devices())]
    assert ("sanrio", {"port": "enp36s0", "to": "[[sw]]", "to_port": "2"}) in props


def test_trunk_and_uplink_ports_ignored(tmp_path):
    props = [(p.host, p.link) for p in propose_links(lab(tmp_path), devices())]
    assert ("sanrio", {"port": "enp36s0", "to": "[[uxg]]", "to_port": "4"}) not in props
    assert not [p for p in props if p[1]["to_port"] == "7"]
    assert not [p for p in props if p[0] == "vm1"]
    assert not [p for p in props if {p[0], p[1]["to"]} == {"sw", "[[ap]]"} or p[0] == "sw"]


def test_existing_links_kept():
    existing = [{"port": "enp36s0", "to": "[[other]]", "to_port": "1"}]
    assert merge_links(existing, [{"port": "enp36s0", "to": "[[sw]]", "to_port": "2"}]) is None
    merged = merge_links(existing, [{"port": "eno1", "to": "[[sw]]", "to_port": "3"}])
    assert merged == existing + [{"port": "eno1", "to": "[[sw]]", "to_port": "3"}]
