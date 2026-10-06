from bastet.core.cabling import merge_links, port_rows, propose_links
from bastet.core.factsnote import render_facts
from bastet.core.hosttypes import load_host_types
from bastet.core.inventory import load_inventory
from bastet.core.unifi import parse_mca
from unifi_fixtures import AP, GATEWAY, GUEST_MAC, HOST_MAC, SWITCH

TYPES = load_host_types()


def write_facts(root, host: str, facts: dict) -> None:
    path = root / "_bastet" / "facts" / f"{host} facts.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_facts(host, facts, "2026-10-06T10:00:00Z"))


def lab(tmp_path):
    files = {
        "Homelab.md": "---\nbastet: lab\n---\n",
        "hosts/uxg.md": "---\nbastet: host\ntype: unifi-gateway\nip: 10.10.0.1\n---\n",
        "hosts/ap.md": "---\nbastet: host\ntype: unifi-ap\nip: 10.10.0.3\n---\n",
        "hosts/sw.md": "---\nbastet: host\ntype: unifi-switch\nip: 10.10.0.5\n---\n",
        "hosts/sanrio.md": "---\nbastet: host\ntype: proxmox-node\nip: 10.10.0.15\n---\n",
        "hosts/vm1.md": '---\nbastet: host\ntype: vm\nruns_on: "[[sanrio]]"\nip: 10.10.0.60\n---\n',
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    write_facts(tmp_path, "sanrio", {"interfaces": [{"name": "enp36s0", "mac": HOST_MAC}]})
    write_facts(tmp_path, "vm1", {"interfaces": [{"name": "eth0", "mac": GUEST_MAC}]})
    return load_inventory(tmp_path, TYPES)


def devices():
    return {"uxg": ("unifi-gateway", parse_mca(GATEWAY)), "ap": ("unifi-ap", parse_mca(AP)),
            "sw": ("unifi-switch", parse_mca(SWITCH))}


def test_unifi_to_unifi_link_goes_downstream(tmp_path):
    props, _ = propose_links(lab(tmp_path), TYPES, devices())
    assert ("ap", {"port": "eth0", "to": "[[uxg]]", "to_port": "4"}) in [(p.host, p.link) for p in props]


def test_host_link_from_mac_table(tmp_path):
    props = [(p.host, p.link) for p in propose_links(lab(tmp_path), TYPES, devices())[0]]
    assert ("sanrio", {"port": "enp36s0", "to": "[[sw]]", "to_port": "2"}) in props


def test_trunk_and_uplink_ports_ignored(tmp_path):
    props = [(p.host, p.link) for p in propose_links(lab(tmp_path), TYPES, devices())[0]]
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
    lab(tmp_path)
    (tmp_path / "hosts" / "ap.md").write_text("---\nbastet: host\ntype: unifi-ap\nip: 10.10.0.3\n---\n")
    write_facts(tmp_path, "ap", {"mac": "02:00:00:00:00:03"})
    inv = load_inventory(tmp_path, TYPES)
    props, _ = propose_links(inv, TYPES, {"uxg": ("unifi-gateway", parse_mca(GATEWAY))})
    assert not [p for p in props if p.link["to_port"] == "4"]


def test_bridge_sharing_the_nic_mac_links_the_nic(tmp_path):
    lab(tmp_path)
    write_facts(tmp_path, "sanrio", {"interfaces": [{"name": "enp36s0", "mac": HOST_MAC}, {"name": "vmbr0", "mac": HOST_MAC}]})
    props, _ = propose_links(load_inventory(tmp_path, TYPES), TYPES, devices())
    assert [p.link["port"] for p in props if p.host == "sanrio"] == ["enp36s0"]


def test_port_with_several_known_hosts_is_not_linked(tmp_path):
    import json
    from unifi_fixtures import SWITCH
    lab(tmp_path)
    (tmp_path / "hosts" / "nas.md").write_text("---\nbastet: host\ntype: server\nip: 10.10.0.20\n---\n")
    write_facts(tmp_path, "nas", {"interfaces": [{"name": "eno1", "mac": "02:00:00:00:10:02"}]})
    sw = json.loads(SWITCH)
    sw["port_table"][0]["mac_table"].append({"mac": "02:00:00:00:10:02"})
    props, notes = propose_links(load_inventory(tmp_path, TYPES), TYPES, {"sw": ("unifi-switch", parse_mca(json.dumps(sw)))})
    assert not [p for p in props if p.link["to_port"] == "2"]
    assert any("port 2" in n[1] and "unmanaged switch" in n[1] for n in notes)


def test_merge_links_keeps_hand_written_entries_and_reports_conflicts():
    existing = ["[[sw]] port 3", {"port": "eno1", "to": "[[other]]", "to_port": "1"}]
    merged, conflicts = merge_links(existing, [{"port": "eno1", "to": "[[sw]]", "to_port": "2"},
                                               {"port": "eno2", "to": "[[sw]]", "to_port": "5"}])
    assert merged == existing + [{"port": "eno2", "to": "[[sw]]", "to_port": "5"}]
    assert conflicts == ["eno1: seen on [[sw]] port 2, the file says [[other]] port 1"]
    assert merge_links("see rack photo", [{"port": "eno1", "to": "[[sw]]", "to_port": "2"}])[0] is None


def test_port_rows_both_directions(tmp_path):
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hardware").mkdir()
    (tmp_path / "hosts" / "sw.md").write_text(
        '---\nbastet: host\ntype: unifi-switch\nip: 10.0.0.5\n'
        'links:\n  - {port: "10", to: "[[gw]]", to_port: "4"}\n---\n# sw\n')
    write_facts(tmp_path, "sw", {"ports": [
        {"port": "1", "name": "eth0", "media": "GE"}, {"port": "2", "name": "eth1", "media": "GE"},
        {"port": "10", "name": "eth9", "media": "SFP+"},
    ]})
    (tmp_path / "hosts" / "nas.md").write_text(
        '---\nbastet: host\ntype: server\nlinks:\n  - {port: eno1, to: "[[sw]]", to_port: "2", speed: 1G, vlans: [20]}\n---\n# nas\n')
    (tmp_path / "hosts" / "pve.md").write_text("---\nbastet: host\ntype: proxmox-node\n---\n# pve\n")
    (tmp_path / "hardware" / "X540.md").write_text(
        '---\nbastet: hardware\ncategory: nic\ninstalled_in: "[[pve]]"\n'
        'links:\n  - {port: enp1s0f0, to: "[[sw]]", to_port: "1", note: storage}\n---\n# X540\n')
    rows = port_rows(load_inventory(tmp_path, TYPES), TYPES, "sw")
    assert [(r.port, r.peer, r.peer_port, r.direction) for r in rows] == [
        ("1", "pve", "enp1s0f0", "down"), ("2", "nas", "eno1", "down"), ("10", "gw", "4", "up")]
    assert rows[0].note == "storage" and rows[1].vlans == "20" and rows[1].speed == "1G"


BMC_MAC, BMC2_MAC, NAS_MAC, NAS_MAC2 = "02:00:00:00:20:01", "02:00:00:00:20:02", "02:00:00:00:10:02", "02:00:00:00:10:03"


def bmc_lab(tmp_path):
    """sanrio's BMC on its own cable (port 1); nas's BMC shares nas's eno1 (port 3); nas's two NICs both on port 5."""
    import json
    lab(tmp_path)
    (tmp_path / "hardware").mkdir()
    (tmp_path / "hardware" / "ASRock X470.md").write_text(
        f'---\nbastet: hardware\ncategory: server\ninstalled_in: "[[sanrio]]"\noob:\n  type: ipmi\n  mac: {BMC_MAC}\n---\n')
    (tmp_path / "hosts" / "nas.md").write_text("---\nbastet: host\ntype: server\nip: 10.10.0.20\n---\n")
    write_facts(tmp_path, "nas", {"interfaces": [{"name": "eno1", "mac": NAS_MAC}, {"name": "eno2", "mac": NAS_MAC2}]})
    (tmp_path / "hardware" / "Supermicro X11.md").write_text(
        f'---\nbastet: hardware\ncategory: server\ninstalled_in: "[[nas]]"\noob:\n  type: ipmi\n  mac: {BMC2_MAC}\n---\n')
    sw = json.loads(SWITCH)
    sw["port_table"] += [
        {"port_idx": 1, "name": "Port 1", "media": "GE", "is_uplink": False, "mac_table": [{"mac": BMC_MAC}]},
        {"port_idx": 3, "name": "Port 3", "media": "GE", "is_uplink": False, "mac_table": [{"mac": NAS_MAC}, {"mac": BMC2_MAC}]},
    ]
    return load_inventory(tmp_path, TYPES), {"sw": ("unifi-switch", parse_mca(json.dumps(sw)))}


def test_bmc_on_its_own_cable_is_linked_on_the_machine_note(tmp_path):
    inv, devs = bmc_lab(tmp_path)
    props = [(p.host, p.link) for p in propose_links(inv, TYPES, devs)[0]]
    assert ("ASRock X470", {"port": "bmc", "to": "[[sw]]", "to_port": "1"}) in props
    assert ("sanrio", {"port": "enp36s0", "to": "[[sw]]", "to_port": "2"}) in props


def test_shared_bmc_and_nic_on_one_port_both_linked(tmp_path):
    inv, devs = bmc_lab(tmp_path)
    props, notes = propose_links(inv, TYPES, devs)
    pairs = [(p.host, p.link) for p in props]
    assert ("nas", {"port": "eno1", "to": "[[sw]]", "to_port": "3"}) in pairs
    assert ("Supermicro X11", {"port": "bmc", "to": "[[sw]]", "to_port": "3"}) in pairs
    assert not any("port 3" in n[1] for n in notes)


def test_two_nics_of_one_host_on_one_port_is_a_warning(tmp_path):
    import json
    inv, _ = bmc_lab(tmp_path)
    sw = json.loads(SWITCH)
    sw["port_table"].append({"port_idx": 5, "name": "Port 5", "media": "GE", "is_uplink": False,
                             "mac_table": [{"mac": NAS_MAC}, {"mac": NAS_MAC2}]})
    props, notes = propose_links(inv, TYPES, {"sw": ("unifi-switch", parse_mca(json.dumps(sw)))})
    assert not [p for p in props if p.link["to_port"] == "5"]
    assert any("port 5" in n[1] and "eno1" in n[1] and "eno2" in n[1] for n in notes)


def test_port_rows_keep_every_link_on_a_shared_port(tmp_path):
    (tmp_path / "hosts").mkdir()
    (tmp_path / "hardware").mkdir()
    (tmp_path / "hosts" / "sw.md").write_text("---\nbastet: host\ntype: unifi-switch\nip: 10.0.0.5\n---\n# sw\n")
    (tmp_path / "hosts" / "nas.md").write_text(
        '---\nbastet: host\ntype: server\nlinks:\n  - {port: eno1, to: "[[sw]]", to_port: "3"}\n---\n# nas\n')
    (tmp_path / "hardware" / "Supermicro X11.md").write_text(
        '---\nbastet: hardware\ncategory: server\ninstalled_in: "[[nas]]"\n'
        'links:\n  - {port: bmc, to: "[[sw]]", to_port: "3"}\n---\n# X11\n')
    rows = port_rows(load_inventory(tmp_path, TYPES), TYPES, "sw")
    assert sorted((r.port, r.peer, r.peer_port) for r in rows) == [("3", "nas", "bmc"), ("3", "nas", "eno1")]
