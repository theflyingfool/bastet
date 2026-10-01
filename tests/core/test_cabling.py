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
    props, _ = propose_links(lab(tmp_path), devices())
    assert ("ap", {"port": "eth0", "to": "[[uxg]]", "to_port": "4"}) in [(p.host, p.link) for p in props]


def test_host_link_from_mac_table(tmp_path):
    props = [(p.host, p.link) for p in propose_links(lab(tmp_path), devices())[0]]
    assert ("sanrio", {"port": "enp36s0", "to": "[[sw]]", "to_port": "2"}) in props


def test_trunk_and_uplink_ports_ignored(tmp_path):
    props = [(p.host, p.link) for p in propose_links(lab(tmp_path), devices())[0]]
    assert ("sanrio", {"port": "enp36s0", "to": "[[uxg]]", "to_port": "4"}) not in props
    assert not [p for p in props if p[1]["to_port"] == "7"]
    assert not [p for p in props if p[0] == "vm1"]
    assert not [p for p in props if {p[0], p[1]["to"]} == {"sw", "[[ap]]"} or p[0] == "sw"]


def test_existing_links_kept():
    existing = [{"port": "enp36s0", "to": "[[other]]", "to_port": "1"}]
    assert merge_links(existing, [{"port": "enp36s0", "to": "[[sw]]", "to_port": "2"}])[0] is None
    merged, _ = merge_links(existing, [{"port": "eno1", "to": "[[sw]]", "to_port": "3"}])
    assert merged == existing + [{"port": "eno1", "to": "[[sw]]", "to_port": "3"}]


def test_single_device_run_still_knows_trunks(tmp_path):
    inv = lab(tmp_path)
    (tmp_path / "hosts" / "ap.md").write_text("---\nbastet: host\ntype: unifi-ap\nip: 10.10.0.3\nmac: 02:00:00:00:00:03\n---\n")
    (tmp_path / "hosts" / "sanrio.md").write_text(f"---\nbastet: host\ntype: proxmox-node\nip: 10.10.0.15\ninterfaces:\n  - name: enp36s0\n    mac: {HOST_MAC}\n---\n")
    inv = load_inventory(tmp_path, TYPES)
    props, _ = propose_links(inv, {"uxg": ("unifi-gateway", parse_mca(GATEWAY))})
    assert not [p for p in props if p.link["to_port"] == "4"]


def test_bridge_sharing_the_nic_mac_links_the_nic(tmp_path):
    lab(tmp_path)
    (tmp_path / "hosts" / "sanrio.md").write_text(
        f"---\nbastet: host\ntype: proxmox-node\nip: 10.10.0.15\ninterfaces:\n  - name: enp36s0\n    mac: {HOST_MAC}\n"
        f"  - name: vmbr0\n    mac: {HOST_MAC}\n---\n")
    props, _ = propose_links(load_inventory(tmp_path, TYPES), devices())
    assert [p.link["port"] for p in props if p.host == "sanrio"] == ["enp36s0"]


def test_port_with_several_known_hosts_is_not_linked(tmp_path):
    import json
    from unifi_fixtures import SWITCH
    lab(tmp_path)
    (tmp_path / "hosts" / "nas.md").write_text("---\nbastet: host\ntype: server\nip: 10.10.0.20\ninterfaces:\n  - name: eno1\n    mac: 02:00:00:00:10:02\n---\n")
    sw = json.loads(SWITCH)
    sw["port_table"][0]["mac_table"].append({"mac": "02:00:00:00:10:02"})
    props, notes = propose_links(load_inventory(tmp_path, TYPES), {"sw": ("unifi-switch", parse_mca(json.dumps(sw)))})
    assert not [p for p in props if p.link["to_port"] == "2"]
    assert any("port 2" in n[1] and "unmanaged switch" in n[1] for n in notes)


def test_merge_links_keeps_hand_written_entries_and_reports_conflicts():
    existing = ["[[sw]] port 3", {"port": "eno1", "to": "[[other]]", "to_port": "1"}]
    merged, conflicts = merge_links(existing, [{"port": "eno1", "to": "[[sw]]", "to_port": "2"},
                                               {"port": "eno2", "to": "[[sw]]", "to_port": "5"}])
    assert merged == existing + [{"port": "eno2", "to": "[[sw]]", "to_port": "5"}]
    assert conflicts == ["eno1: seen on [[sw]] port 2, the file says [[other]] port 1"]
    assert merge_links("see rack photo", [{"port": "eno1", "to": "[[sw]]", "to_port": "2"}])[0] is None
