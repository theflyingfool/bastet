from bastet.core.hwparse import (
    base_device, clean, machine_from_dmi, memory_size, parse_disk_ids, parse_dmidecode, parse_ipmi_lan,
    parse_lspci, parse_net_sysfs, parse_pve_guests, parse_smart, parse_zpool, slots_in_use, speed_label, strip_ids,
)
from gather_fixtures import LAPTOP, SERVER


def test_clean_placeholders():
    for junk in ("To Be Filled By O.E.M.", "Default string", "0123456789", "  ", "Not Specified", "None", "00000000"):
        assert clean(junk) is None, junk
    assert clean(" S123 ") == "S123"


def test_dmidecode_server_machine():
    m = machine_from_dmi(parse_dmidecode(SERVER["dmidecode"]))
    assert m["make"] == "Supermicro" and m["model"] == "SYS-5019C-MR" and m["serial"] == "S123456X"
    assert m["board"] == "Supermicro X11SCM-F"
    assert m["bios"] == "American Megatrends Inc. 3.4 (03/21/2023)"
    assert m["cpus"] == [{"socket": "CPU", "model": "Intel(R) Xeon(R) E-2236 CPU @ 3.40GHz", "cores": 6, "threads": 12}]
    assert m["memory"] == [
        {"slot": "DIMMA1", "size": "32 GB", "type": "DDR4", "speed": "2666 MT/s", "part": "M391A4G43MB1-CTD", "serial": "40A1B2C3"},
        {"slot": "DIMMB1", "size": "32 GB", "type": "DDR4", "speed": "2666 MT/s", "part": "M391A4G43MB1-CTD", "serial": "40A1B2C4"},
    ]
    assert m["memory_slots"] == "2 of 4 used"


def test_dmidecode_laptop_placeholders_and_mb():
    m = machine_from_dmi(parse_dmidecode(LAPTOP["dmidecode"]))
    assert m["serial"] == "5CD1234XYZ" and m["board"] == "HP 83BB"
    assert m["memory"] == [{"slot": "Onboard", "size": "16 GB", "type": "LPDDR3", "speed": "2133 MT/s"}]


def test_slots_and_memory_size():
    assert slots_in_use(parse_dmidecode(SERVER["dmidecode"])) == {"0000:01:00": "CPU SLOT6 PCI-E 3.0 X16"}
    assert memory_size("16384 MB") == "16 GB" and memory_size("No Module Installed") is None
    assert memory_size("512 MB") == "512 MB"


def test_lspci():
    devs = parse_lspci(SERVER["lspci"])
    assert len(devs) == 5 and devs[2]["class_code"] == "0200" and devs[2]["Slot"] == "0000:01:00.0"
    assert strip_ids(devs[2]["SDevice"]) == "Ethernet Converged Network Adapter X710-2"


def test_net_sysfs_and_speed():
    net = parse_net_sysfs(SERVER["net_sysfs"])
    assert net["eno1"] == {"speed": 1000, "pci": "0000:03:00.0"}
    assert net["enp1s0f1"] == {"speed": None, "pci": "0000:01:00.1"}
    assert net["vmbr0"] == {"speed": None, "pci": None}
    assert speed_label(1000) == "1G" and speed_label(2500) == "2.5G" and speed_label(100) == "100M"
    assert speed_label(None) is None


def test_ipmi():
    assert parse_ipmi_lan(SERVER["ipmi"]) == {"type": "ipmi", "address": "10.0.10.9", "mac": "3c:ec:ef:00:00:09", "source": "static"}
    assert parse_ipmi_lan("IP Address : 0.0.0.0\n") is None


def test_zpool_and_ids():
    [pool] = parse_zpool(SERVER["zpool"])
    assert pool["name"] == "tank" and pool["state"] == "ONLINE" and len(pool["devices"]) == 2
    ids = parse_disk_ids(SERVER["disk_ids"])
    assert ids["ata-WDC_WD40EFRX-68N32N0_WD-WCC4E1234567-part1"] == "sda1"
    assert base_device("sda1") == "sda" and base_device("nvme0n1p3") == "nvme0n1" and base_device("sda") == "sda"


def test_smart():
    smart = parse_smart(SERVER["smart"])
    assert smart["/dev/sda"] == {"model": "WDC WD40EFRX-68N32N0", "serial": "WD-WCC4E1234567", "firmware": "82.00A82",
                                 "health": "passed", "rotation": 5400, "bytes": 4000787030016}
    assert smart["/dev/nvme0n1"]["bytes"] == 1000204886016
    assert "/dev/zd0" not in smart
    assert parse_smart("not json") == {}


def test_pve_guests():
    assert parse_pve_guests(SERVER["pve_guests"]) == [
        {"vmid": 104, "name": "git1", "type": "lxc", "node": "pve1", "status": "running"},
        {"vmid": 105, "name": "media", "type": "qemu", "node": "pve1", "status": "stopped"},
        {"vmid": 106, "name": "dns", "type": "qemu", "node": "pve1", "status": "running"},
        {"vmid": 107, "name": "ghost", "type": "qemu", "node": "pve1", "status": "stopped"},
    ]


def test_clean_heuristics():
    for junk in ("123456789", "0000000000000000", "XXXXXXXX", "FFFFFFFF", "Not Present", "To Be Filled By O.E.M"):
        assert clean(junk) is None, junk
    assert clean("WD-WCC4E1234567") == "WD-WCC4E1234567"


def test_slot_ids():
    from bastet.core.hwparse import slot_designations
    assert slot_designations(parse_dmidecode(SERVER["dmidecode"])) == {"6": "CPU SLOT6 PCI-E 3.0 X16"}


def test_smart_tolerates_empty_entries():
    assert parse_smart('[,{"device":{"name":"/dev/sda"},"serial_number":"S1","model_name":"M"}]')["/dev/sda"]["serial"] == "S1"


def test_memory_in_gib_units_and_duplicate_locators():
    text = ("Handle 0x0011, DMI type 17, 40 bytes\nMemory Device\n\tSize: 4 GiB\n\tLocator: Bottom - on board\n"
            "\tBank Locator: BANK 0\n\tType: LPDDR3\n\tSpeed: 1867 MT/s\n\n"
            "Handle 0x0012, DMI type 17, 40 bytes\nMemory Device\n\tSize: 4 GiB\n\tLocator: Bottom - on board\n"
            "\tBank Locator: BANK 2\n\tType: LPDDR3\n\tSpeed: 1867 MT/s\n")
    m = machine_from_dmi(parse_dmidecode(text))
    assert [d["slot"] for d in m["memory"]] == ["Bottom - on board (BANK 0)", "Bottom - on board (BANK 2)"]
    assert [d["size"] for d in m["memory"]] == ["4 GB", "4 GB"] and m["memory_slots"] == "2 of 2 used"
    assert memory_size("512 MiB") == "512 MB" and memory_size("16384 MiB") == "16 GB" and memory_size("1 TiB") == "1 TB"


def test_board_subsystem_vendor_by_name():
    from bastet.core.hwparse import board_subsystem_id
    devices = [{"SVendor": "Advanced Micro Devices, Inc. [AMD] [1022]"}] * 10 + [
        {"SVendor": "ASRock Incorporation [1849]"}, {"SVendor": "Broadcom / LSI [1000]"}]
    assert board_subsystem_id(devices, ["ASRockRack", "ASRockRack"]) == "1849"
    assert board_subsystem_id([{"SVendor": "Super Micro Computer Inc [15d9]"}], ["Supermicro"]) == "15d9"
    assert board_subsystem_id([{"SVendor": "Hewlett-Packard Company [103c]"}], ["HP"]) == "103c"
    assert board_subsystem_id(devices, ["Unknown Vendor"]) is None


def test_guest_conf_and_neighbours():
    from bastet.core.hwparse import parse_guest_conf, parse_neigh
    conf = parse_guest_conf(SERVER["pve_guest_conf"])
    assert conf[104] == {"kind": "lxc", "macs": ["bc:24:11:00:01:04"], "ip": "10.0.20.21/24"}
    assert conf[105] == {"kind": "qemu", "macs": ["bc:24:11:00:01:05"], "ip": None}
    assert conf[106]["ip"] == "10.0.20.36/24"
    assert parse_neigh(SERVER["neigh"]) == {"bc:24:11:00:01:05": "10.0.20.25"}
    assert parse_guest_conf("### /etc/pve/lxc/9.conf\nnet0: name=eth0,ip=dhcp,hwaddr=AA:BB:CC:DD:EE:FF\n")[9]["ip"] == "dhcp"


def test_guest_conf_manual_and_second_nic_static():
    from bastet.core.hwparse import parse_guest_conf
    conf = parse_guest_conf("### /etc/pve/lxc/9.conf\nnet0: name=eth0,ip=dhcp,hwaddr=AA:BB:CC:DD:EE:01\n"
                            "net1: name=eth1,ip=10.0.30.9/24,hwaddr=AA:BB:CC:DD:EE:02\n"
                            "### /etc/pve/lxc/10.conf\nnet0: name=eth0,ip=manual,hwaddr=AA:BB:CC:DD:EE:03\n")
    assert conf[9]["ip"] == "10.0.30.9/24"
    assert conf[10]["ip"] is None


def test_templates_and_failed_neighbours_dropped():
    import json
    from bastet.core.hwparse import parse_neigh
    guests = parse_pve_guests(json.dumps([{"vmid": 9000, "name": "tpl", "type": "qemu", "node": "n", "template": 1},
                                          {"vmid": 101, "name": "a", "type": "lxc", "node": "n"}]))
    assert [g["name"] for g in guests] == ["a"]
    neigh = parse_neigh(json.dumps([{"dst": "10.0.0.5", "lladdr": "aa:aa:aa:aa:aa:aa", "state": ["FAILED"]},
                                    {"dst": "10.0.0.6", "lladdr": "bb:bb:bb:bb:bb:bb", "state": ["STALE"]}]))
    assert neigh == {"bb:bb:bb:bb:bb:bb": "10.0.0.6"}


def test_board_subsystem_prefers_most_used_matching_id():
    from bastet.core.hwparse import board_subsystem_id
    devices = [{"SVendor": "Hewlett Packard Enterprise [1590]"}] + [{"SVendor": "Hewlett-Packard Company [103c]"}] * 3
    assert board_subsystem_id(devices, ["HPE"]) == "103c"
